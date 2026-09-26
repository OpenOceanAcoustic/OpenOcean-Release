# ci_server 运行环境

日常 `init`、`plan`、`submit` 在发布者电脑运行，不需要本机 `runner.yaml`。两个手动 Actions 工作流在 ci_server 的 self-hosted runner 上运行，默认读取 `/home/ci_server/.config/openocean/runner.yaml`。该文件由 `ci_server` 用户持有，仅管理员在机器路径、镜像、VM 或密钥文件位置变化时维护，无需迁移或一次性 setup。仓库不再提供 `runner.example.yaml`，也不需要发布者创建任何 runner 配置。

当前服务器产物根目录是 `/mnt/repo/ci`。预览在 `previews/<run-id>/<release-id>/assets/`，正式封存在 `release/<release-id>/assets/`。运行摘要会打印实际路径和校验和。预览默认保留 7 天；正式封存不受预览清理影响。构建缓存、暂存和 Windows 共享目录仍以服务器配置文件中的实际路径为准。

ci_server 用户持有 Docker、自托管 Actions runner、Windows VM 和 SSH 密钥。VM 是 `ci_server` 的用户态会话，必须以该账户运行编译。VM 私钥和 `OOA_FIELD_READ_TOKEN` 不给普通发布者。Release 仓库的 Actions Secret `OOA_FIELD_READ_TOKEN` 需要对七个私有源码库有 Contents 读取、Actions 读取和查询仓库权限所需的 Metadata 读取权限。发布 job 使用自己的 `GITHUB_TOKEN` 与 `contents: write`。每个普通发布者还必须用自己的 GitHub 身份拥有本次依赖私有库的读取权限。

Windows 构建通过配置的控制器、PowerShell runner 和私有 SSH 通道；MATLAB 使用配置的 R2025b。Linux 构建使用按 digest 固定的 Docker 镜像。编译前的预检会检查所选产物需要的环境。

## 服务器配置字段（仅管理员参考）

已有服务器配置的 `schema` 是 `openocean.runner/v1`，下面的字段由 [RunnerConfig](../openocean_release/config.py) 校验。凭据字段填写环境变量名称，密钥字段填写服务器上的文件路径，不填写 token 或密钥正文。

| 区域 | 字段 | 用途 |
| --- | --- | --- |
| `execution` | `build_user`、`require_initial_sudo` | 构建账户及旧服务器命令的账户切换要求 |
| `storage` | `root`、`linux`、`windows`、`cache`、`staging`、`releases` | 服务器根目录、构建缓存、暂存及正式封存目录 |
| `linux` | `engine`、`image`、`inherit_proxy` | Docker 引擎、带 `@sha256:` 的固定镜像及代理继承 |
| `windows` 控制与目录 | `vm_controller`、`powershell_runner`、`shared_host_root`、`shared_guest_root`、`restore_previous_vm_state` | VM 控制器、命令执行器、主机/客机目录及运行结束后的状态恢复 |
| `windows` SSH | `ssh_host`、`ssh_port`、`ssh_user`、`ssh_private_key`、`ssh_known_hosts` | 私有 SSH 通道及服务器持有的密钥文件 |
| `windows` 编译工具 | `build_python`、`wheelhouse`、`cibuildwheel_cache`、`matlab`、`inherit_proxy` | 已配置的 Python、离线依赖、缓存、MATLAB 及代理继承 |
| `credentials` | `source_read_token_env`、`github_publish_token_env` | 当前分别为 `OOA_FIELD_READ_TOKEN`、`GH_TOKEN`；值由工作流提供 |
| `logging`（可选） | `live`、`text`、`jsonl`、`redact_environment` | 日志选项与需要隐藏值的环境变量名称 |
