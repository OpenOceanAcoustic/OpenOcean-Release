"""Streaming logs, checksums, subprocesses, and resumable task state."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from typing import Iterable, Mapping, Sequence


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class EventLogger:
    def __init__(self, directory: Path, secret_values: Iterable[str] = ()) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.events_path = directory / "events.jsonl"
        self.summary_path = directory / "summary.log"
        self.secrets = tuple(sorted(
            {value for value in secret_values if value}, key=len, reverse=True
        ))
        self._lock = threading.Lock()

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return re.sub(
            r"(?i)\b(https?|socks5?)://[^\s/@:]+:[^\s/@]+@",
            r"\1://***@",
            text,
        )

    def _redacted_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self._redacted_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._redacted_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._redacted_value(item)
                for key, item in value.items()
            }
        return value

    def event(self, task: str, level: str, message: str, **fields: object) -> None:
        message = self.redact(message.rstrip("\n"))
        record = {
            "time": dt.datetime.now(dt.timezone.utc).isoformat(),
            "task": task,
            "level": level,
            "message": message,
            **{
                key: self._redacted_value(value)
                for key, value in fields.items()
            },
        }
        line = f"[{task}] {message}"
        with self._lock:
            print(line, flush=True)
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            if level in {"INFO", "WARNING", "ERROR"}:
                with self.summary_path.open("a", encoding="utf-8") as stream:
                    stream.write(line + "\n")

    def command(
        self,
        task: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
    ) -> None:
        display = subprocess.list2cmdline(list(command))
        self.event(task, "INFO", f"$ {display}")
        task_log = self.directory / f"{task.replace('/', '_').replace('.', '_')}.log"
        process = subprocess.Popen(
            list(command), cwd=cwd, env=dict(env) if env is not None else None,
            stdin=subprocess.PIPE if input_text is not None else None,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace", bufsize=1,
        )
        if input_text is not None:
            assert process.stdin is not None
            process.stdin.write(input_text)
            process.stdin.close()
        assert process.stdout is not None
        with task_log.open("a", encoding="utf-8") as log:
            for line in process.stdout:
                redacted = self.redact(line.rstrip("\n"))
                print(f"[{task}] {redacted}", flush=True)
                log.write(redacted + "\n")
        code = process.wait()
        if code:
            self.event(task, "ERROR", f"command failed with exit code {code}")
            raise subprocess.CalledProcessError(code, list(command))


@dataclass
class TaskState:
    path: Path
    document: dict[str, object]

    @classmethod
    def open(cls, path: Path, release_id: str) -> "TaskState":
        if path.is_file():
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("releaseId") != release_id:
                raise RuntimeError("state release ID does not match directory")
            return cls(path, document)
        return cls(path, {"schema": "openocean.release-state/v1", "releaseId": release_id, "tasks": {}})

    @property
    def tasks(self) -> dict[str, dict[str, object]]:
        value = self.document.setdefault("tasks", {})
        assert isinstance(value, dict)
        return value  # type: ignore[return-value]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def reusable(self, name: str, input_hash: str, outputs: Sequence[Path]) -> bool:
        record = self.tasks.get(name)
        if not record or record.get("status") != "succeeded" or record.get("inputSha256") != input_hash:
            return False
        saved = record.get("outputs")
        if not isinstance(saved, dict):
            return False
        return all(path.is_file() and saved.get(str(path)) == sha256_file(path) for path in outputs)

    def start(self, name: str, input_hash: str) -> None:
        self.tasks[name] = {
            "status": "running",
            "inputSha256": input_hash,
            "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.save()

    def succeed(self, name: str, outputs: Sequence[Path]) -> None:
        record = self.tasks[name]
        record["status"] = "succeeded"
        record["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["outputs"] = {str(path): sha256_file(path) for path in outputs}
        self.save()

    def fail(self, name: str, error: BaseException) -> None:
        record = self.tasks.setdefault(name, {})
        record["status"] = "failed"
        record["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
        record["error"] = str(error)
        self.save()
