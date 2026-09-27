# OpenOcean Release

源码库各自运行 CI；这个仓库负责把指定源码 SHA 编译成包、在 ci_server 封存，并按需公开发布。日常操作在任意已获仓库权限的账户下进行，不必在这台电脑上编译，也不用修改 YAML 或提交一次性配置。

## 日常操作

首次使用先在仓库目录执行 `python3 -m pip install -r requirements.txt`；本机只需 Python、PyYAML 和 GitHub CLI。

```bash
gh auth login                      # 每位操作者只需登录自己的 GitHub 账户
python3 main.py init               # 首次生成 Git 忽略的全量公开发布示例 release.local.py
# 在 IDE 中编辑 release.local.py
python3 main.py plan               # 只显示计划，无需 runner.yaml、token 或服务器连接
python3 main.py submit preview     # 先设置 publish(False)；可反复预览
python3 main.py submit release     # 正式封存；publish(True) 时公开发布
```

`release.local.example.py` 是完整的全量编译、全量公开发布案例：列出全部七个库的 ref，选择六库的 Linux/Windows 原生包、双平台 Python 包和 Windows MATLAB 包，并显式设置 `publish(True)`。通过 `init` 复制后，按注释修改即可；只预览或只封存时，把它改成 `publish(False)`。

`release.local.py` 使用 [`Model`、`Platform` 和 `ReleasePlan`](release.local.example.py)。下面是局部编译、不公开发布的例子：

```python
from openocean_release.plan import Model, Platform, ReleasePlan

plan = ReleasePlan()
plan.ref(Model.PE, "my-branch-or-exact-sha")
plan.native(Model.PE, platforms=(Platform.WINDOWS,))
plan.version("auto")
plan.notes("# PE update\n\n说明改动和测试结果。")
plan.publish(False)
```

`ref()` 可以调用多次，为任意一个或多个库选择 ref。未指定的库沿用仓库内固定 SHA。`native()` 选择单库或多库原生包（Windows WI 构建还需 Toolbox 中的 Eigen 定位脚本）；`python()` 和 `matlab()` 选择集成包，自动包含全部七个源码库。正式 MATLAB 包完整重编。`plan.build(False)` 只用于以后公开已经封存的版本：

```python
plan = ReleasePlan().existing_release("2026.9.26.1").publish(True)
```

提交的 Actions 参数只含 ref、产物选择、版本、发布文字及公开开关。`submit` 使用当前用户的 `gh` 登录；每次发布无需修改 YAML 或创建配置 commit。计划及发布文字会出现在工作流输入中，切勿把凭据写进去。

## 找到构建结果

预览工作流接受开发分支，不创建 tag、不公开发布，也不上传 Actions artifact。运行摘要打印每个文件的**服务器绝对路径和 SHA256**。预览默认位于 `/mnt/repo/ci/previews/<Actions-run-id>/<release-id>/assets/`，超过 7 天的预览目录由下一次预览清理。文件仍需现有服务器权限获取。

正式封存位于 `/mnt/repo/ci/release/<release-id>/assets/`；摘要同样打印目录、文件名和校验和，封存目录不会被预览清理。`ReleasePlan()` 默认 `publish(False)`，完整示例显式开启了 `publish(True)`。只有 `submit release` 且显式 `publish(True)` 才创建公开 tag 和 GitHub Release。发布已有封存版本也使用正式工作流。旧版封存版本保持可发布。

正式封存前，工作流把本次依赖库的 ref 锁定为 SHA，核验各库在**相同 SHA** 上的 CI 成功，并核验启动者本人能读取这些私有库。Core 和 Toolbox 要求 `ci.yml`；RayMode、NormalMode、PE、WI、Couple 同时要求 `ci.yml` 与 `tests.yml`。CI 由源码库维护，Release 只查询结果。预览可在 CI 尚未完成时构建，但仍核验操作者源码读取权限。

当前默认固定的 NormalMode、PE 旧 SHA 没有这些 CI 运行记录；选择集成包时，需先让它们的目标 SHA 跑完源码库 CI，再在 `release.local.py` 指向该 SHA。门禁会在编译前列出缺少的仓库和工作流。

## 凭据、配置和权限

| 位置/角色 | 需要什么 | 用途 |
| --- | --- | --- |
| 普通发布者的电脑 | 自己的 `gh auth login`，对 Release 仓库的写权限和本次依赖私有源码库的读权限 | 提交任务；不需要手动 `export` token，也不需要 SSH 密钥或 `runner.yaml` |
| Release 仓库的 Actions Secret | `OOA_FIELD_READ_TOKEN` | ci_server 读取私有源码、查询源码库 CI 与操作者权限；本轮沿用由 `lyy-cn` 配置的凭据，其他操作者无需知道其值 |
| 正式公开发布的工作流 | 该次工作流自带的 `GITHUB_TOKEN`，`contents: write` | 仅在 `publish(True)` 时创建 tag 和公开 GitHub Release |
| ci_server 管理员 | `/home/ci_server/.config/openocean/runner.yaml` 及其中指向的服务器/Windows VM 路径和 SSH 文件 | 机器配置；仅机器路径变化时维护 |

**本机没有 `runner.yaml` 完全正常。**两个手动 Actions 工作流运行在 ci_server 的 self-hosted runner，默认读取其账户拥有的 `/home/ci_server/.config/openocean/runner.yaml`。只有这份服务器配置需要保留，管理员按 [字段说明](docs/runner-environment.md) 维护，普通发布者无需复制填写。凭据和机器配置不进入提交参数；运行摘要会显示产物的服务器路径。`OPENOCEAN_RUNNER_CONFIG` 仅供管理员在服务器上调整位置。

管理员负责保持 runner、Windows VM、固定 Docker 镜像、服务器配置和 Actions Secret 可用。普通发布者负责选择有成功 CI 的 ref、检查 `plan`、查看 Actions 摘要并凭现有服务器权限取包。源码仓库的 CI 配置由各源码库维护。

## 兼容入口和技术文档

仓库根目录不再提供 `release.yaml` 或 `runner.example.yaml`。计划由 Python 代码生成内部配置；默认 ref 与固定产物合同位于 [defaults.py](openocean_release/defaults.py)，日常只修改 `release.local.py`。

旧封存目录里的 `release-config.yaml`、`release-lock.yaml` 等记录继续读取和校验，发布旧封存版本不依赖已经删除的根目录文件。管理员的 `python3 main.py publish --release-id ...` 命令，以及自行提供旧 YAML 的高级构建入口仍保留。产物和校验规则见 [release contract](docs/release-contract.md)；服务器机器依赖见 [runner environment](docs/runner-environment.md)。
