from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from openocean_release.config import ConfigurationError
from openocean_release.github import GitHub
from openocean_release.plan import Model, Platform, ReleasePlan, config_for_request
from openocean_release.request_runner import _preview_runner, run_request, verify_sources


class PlanTest(unittest.TestCase):
    def test_arbitrary_and_multiple_native_models_use_only_selected_sources(self) -> None:
        plan = (ReleasePlan().ref(Model.PE, "feature/pe").ref(Model.WI, "feature/wi")
                .notes("# Two model update")
                .native(Model.WI, Model.PE, platforms=(Platform.LINUX, Platform.WINDOWS)))
        request = plan.request("release")
        config = config_for_request(request, "release")
        self.assertEqual(config.native_families, ("pe", "wi"))
        self.assertEqual({name for name, item in config.sources.items() if item.enabled}, {"pe", "wi", "toolbox"})
        self.assertEqual(config.sources["pe"].ref, "feature/pe")
        self.assertEqual(config.sources["wi"].ref, "feature/wi")
        self.assertFalse(config.products.python)
        self.assertFalse(config.products.matlab)
        self.assertEqual(config.notes_text, "# Two model update")

    def test_integrated_python_and_matlab_require_all_sources(self) -> None:
        for plan in (ReleasePlan().python(Platform.LINUX), ReleasePlan().matlab()):
            with self.subTest(plan=plan):
                config = config_for_request(plan.request("release"), "release")
                self.assertEqual(len([s for s in config.sources.values() if s.enabled]), 7)

    def test_changed_ref_requires_a_product_using_that_model(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "outside the selected products: toolbox"):
            ReleasePlan().ref(Model.TOOLBOX, "feature/docs").native(Model.PE).request("release")

    def test_publication_requires_explicit_switch_and_preview_forbids_it(self) -> None:
        plan = ReleasePlan().native(Model.FIELD_CORE)
        self.assertFalse(plan.request("release")["publish"])
        with self.assertRaises(ConfigurationError):
            plan.publish(True).request("preview")
        request = ReleasePlan().existing_release("2026.9.26.1").publish(True).request("release")
        self.assertFalse(request["build"])

    def test_local_plan_and_submit_do_not_load_runner_or_pass_credentials(self) -> None:
        import main
        with mock.patch("openocean_release.config.RunnerConfig.load", side_effect=AssertionError("runner loaded")):
            with mock.patch("main.load_local", return_value=ReleasePlan().native(Model.PE)):
                self.assertEqual(main.main(["plan"]), 0)
                with mock.patch("main.subprocess.run") as run:
                    self.assertEqual(main.main(["submit", "preview"]), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["gh", "workflow", "run"])
        payload = json.loads(command[-1].removeprefix("request="))
        self.assertEqual(payload["native"], ["pe"])
        self.assertFalse(any(word in json.dumps(payload).lower() for word in ("token", "ssh", "/mnt/", "runner")))


class GateTest(unittest.TestCase):
    def test_freezes_sha_and_checks_only_required_exact_sha_workflows(self) -> None:
        config = config_for_request(ReleasePlan().native(Model.PE).ref(Model.PE, "feature").request("release"), "release")
        github = mock.Mock(spec=GitHub)
        github.resolve_ref.return_value = "a" * 40
        github.successful_workflow_run.side_effect = lambda repo, workflow, sha: f"https://github.com/{repo}/actions/runs/1"
        frozen = verify_sources(config, github, "lyy-cn", check_ci=True)
        github.require_read_permission.assert_called_once_with("OpenOceanAcoustic/OpenOcean-Field-PE", "lyy-cn")
        self.assertEqual([call.args[1] for call in github.successful_workflow_run.call_args_list], ["ci.yml", "tests.yml"])
        self.assertTrue(all(call.args[2] == "a" * 40 for call in github.successful_workflow_run.call_args_list))
        self.assertEqual(frozen.sources["pe"].ref, "a" * 40)
        self.assertEqual(frozen.document["verification"]["sources"]["pe"]["requestedRef"], "feature")

    def test_permission_or_ci_failure_stops_before_build(self) -> None:
        config = config_for_request(ReleasePlan().native(Model.PE).request("release"), "release")
        github = mock.Mock(spec=GitHub)
        github.require_read_permission.side_effect = RuntimeError("no read permission")
        with self.assertRaisesRegex(RuntimeError, "no read permission"):
            verify_sources(config, github, "another-person", check_ci=True)
        github.require_read_permission.side_effect = None
        github.resolve_ref.return_value = "b" * 40
        github.successful_workflow_run.side_effect = RuntimeError("CI failed")
        with self.assertRaisesRegex(RuntimeError, "CI failed"):
            verify_sources(config, github, "another-person", check_ci=True)

    def test_preview_accepts_unchecked_branch_but_still_requires_source_access(self) -> None:
        config = config_for_request(ReleasePlan().native(Model.PE).ref(Model.PE, "feature/docs").request("preview"), "preview")
        github = mock.Mock(spec=GitHub)
        github.resolve_ref.return_value = "e" * 40
        frozen = verify_sources(config, github, "lyy-cn", check_ci=False)
        github.require_read_permission.assert_called_once()
        github.successful_workflow_run.assert_not_called()
        self.assertEqual(frozen.sources["pe"].ref, "e" * 40)

    def test_ci_run_must_match_exact_sha_and_latest_run_must_succeed(self) -> None:
        sha = "c" * 40
        repo = "OpenOceanAcoustic/OpenOcean-Field-PE"
        github = GitHub("hidden")
        github._request = mock.Mock(return_value={"workflow_runs": [
            {"head_sha": "d" * 40, "status": "completed", "conclusion": "success", "created_at": "2026-09-26T10:00:00Z"},
            {"head_sha": sha, "status": "completed", "conclusion": "success", "created_at": "2026-09-26T09:00:00Z", "html_url": f"https://github.com/{repo}/actions/runs/1"},
            {"head_sha": sha, "status": "completed", "conclusion": "failure", "created_at": "2026-09-26T11:00:00Z", "html_url": f"https://github.com/{repo}/actions/runs/2"},
        ]})
        with self.assertRaisesRegex(RuntimeError, "CI is not successful"):
            github.successful_workflow_run(repo, "ci.yml", sha)
        self.assertIn(f"head_sha={sha}", github._request.call_args.args[0])


class PreviewRetentionTest(unittest.TestCase):
    def test_preview_releases_are_under_root_and_formal_releases_are_untouched(self) -> None:
        from openocean_release.config import RunnerConfig
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            formal = root / "release" / "2026.9.26.1"
            formal.mkdir(parents=True)
            old_preview = root / "previews" / "111"
            old_preview.mkdir(parents=True)
            os.utime(old_preview, (time.time() - 8 * 86400, time.time() - 8 * 86400))
            runner = RunnerConfig(root / "runner.yaml", {"storage": {"root": str(root), "releases": str(root / "release")}})
            preview = _preview_runner(runner, "12345")
            self.assertEqual(preview.storage("releases"), root / "previews" / "12345")
            self.assertTrue(formal.exists())
            self.assertFalse(old_preview.exists())


class ServerRequestTest(unittest.TestCase):
    def test_seal_stage_never_publishes_even_when_publication_was_requested(self) -> None:
        from openocean_release.config import RunnerConfig
        request = ReleasePlan().native(Model.FIELD_CORE).publish(True).request("release")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = RunnerConfig(root / "runner.yaml", {
                "storage": {"root": str(root), "releases": str(root / "release")},
                "credentials": {"source_read_token_env": "OOA_FIELD_READ_TOKEN"},
            })
            with mock.patch.dict(os.environ, {"OOA_FIELD_READ_TOKEN": "hidden", "GITHUB_ACTOR": "lyy-cn"}, clear=True), \
                    mock.patch("openocean_release.request_runner.RunnerConfig.load", return_value=runner), \
                    mock.patch("openocean_release.request_runner.verify_sources", side_effect=lambda config, *_args, **_kwargs: config), \
                    mock.patch("openocean_release.request_runner.Orchestrator") as orchestrator, \
                    mock.patch("openocean_release.request_runner._summary"), \
                    mock.patch("openocean_release.request_runner.publish_release") as publish:
                orchestrator.return_value.build.return_value = "2026.9.26.1"
                self.assertEqual(run_request("release", json.dumps(request)), "2026.9.26.1")
                publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
