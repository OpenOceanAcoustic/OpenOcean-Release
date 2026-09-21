# CI 服务器与发布包格式 审计报告

日期：2026-09-21
审计对象：本机 CI 服务器（`/home/ci_server`）的 Linux 编译环境、Windows VM 环境，以及 OpenOcean Field 发布包格式
方法：只读审计。未修改任何文件、未启动或停止任何服务、未使用提权

## 一、结论摘要

| 审计轴 | 结论 |
| --- | --- |
| Linux 编译环境 | **满足**。已验证镜像即发布镜像，40/40 验收对发布直接有效 |
| VM 环境 | **满足**。VM 运行中、SSH 可达，契约四项前置条件全部经 preflight 断言通过 |
| 发布包格式 —— 编排层 | **满足**。契约描述的驱动/封装机制是真实代码且多数强制生效 |
| 发布包格式 —— 内容层 | **部分满足**。多个内容保证只停留在配置断言，未端到端验证 |

一句话：**环境侧已就绪，包格式侧"外壳完整、内核待证"。**

**并且：审计期间正在进行的发布 `2026.9.21.3` 已通过全部 16 个前期任务，
仅剩 `windows.matlab` 在跑 —— 成功后即为该流水线第一次成功 seal。**
换言之，"发布包格式是否满足"这个问题的最终答案，正取决于这一次的结果。

## 一补、现场实测（本报告最重要的证据来源）

审计期间 `/mnt/repo/ci/releases/2026.9.21.3` 正在运行一次真实全量发布，其运行日志提供了
比静态检查强得多的证据。截至 2026-09-21 19:00 的任务状态：

```
succeeded   checkout.{field_core,normal_mode,pe,ray_mode,toolbox}
succeeded   resolve
succeeded   linux.native.{field_core,normal_mode,pe,ray_mode}
succeeded   linux.python
succeeded   windows.native.{field_core,normal_mode,pe,ray_mode}
succeeded   windows.python
succeeded   windows.stage-sources
running     windows.matlab      ← 唯一未完成项，也是历史唯一失败项
```

**这一条同时确证了多件静态检查无法证明的事**：

- **VM 环境实际可用** —— 四个 `windows.native.*`、`windows.python`、`windows.stage-sources` 全部 succeeded，
  说明 VM 可达、可构建、MSVC 与 Python 工具链正常。这比任何静态检查都有力。
- **发布镜像就是已验收的镜像** —— `logs/summary.log` 中记录的实际命令尾部为
  `openocean/ci-wheel@sha256:ca93b681…`，与 `validation-summary.json` 中通过的 wheel 镜像 id 一致。
- **runner 路由正确** —— `openocean-release` 标签由专用 runner `d407-release` 承接，任务实际在此运行。

### 已定位并已修复的故障：MATLAB 版本断言

历史失败根因：Toolbox 适配器断言 `Expected MATLAB R2025b, found 2025b` ——
`version('-release')` 返回 `2025b` 无 `R` 前缀，而适配器直接比对 `R2025b`。

**已修复**：commit `0a8d195 fix: normalize MATLAB release label`（2026-09-21 18:40:05），
在比对前剥离 `^[Rr]` 前缀。本次发布解析到的 toolbox SHA 为 `dcc331e`，**包含该修复**
（`resolved-sources.json` 写于 18:42:11，早于 `windows.matlab` 的 18:45:21 启动），
且当前 `windows_matlab.log` 已推进至 CMake install 阶段、无断言报错。修复生效。

### 已确证具备

#### Linux 编译环境

- `ci-image` 三个镜像已构建并通过一轮环境验收，`images.lock.json` 记 `review_status: approved`，base 全部锁定到 `@sha256:` digest
- 验收覆盖 Core / RayMode / NormalMode / PE 的 native shared+static、ASan/UBSan、cp310–cp314 wheel，共 40/40 本机通过（另有 5 个单模型 cp313 wheel）
- **发布路径使用的镜像与验收镜像一致 —— 已由运行日志实证**（非推测）：
  实际发布的 `logs/summary.log` 中命令尾部为 `openocean/ci-wheel@sha256:ca93b681…`，
  与 `validation-summary.json` 中已通过的 wheel 镜像 id 一致。故那次验收对发布路径**直接有效**
- 各源仓库 `.github/workflows/ci.yml` 显式固定同一 digest，未漂移
- 镜像内工具链经 manifest 与实跑双重确认：gcc/g++/gfortran 14.2.1、cmake 3.31.10、ninja 1.13.0、
  ccache 3.7.7、auditwheel 6.6.0，`/opt/python` 下 cp310–cp314 齐全

### Linux runner 与服务

- 两个 runner 均已配置为 systemd 服务且正在运行（本次由子代理核实）：
  - `actions.runner.OpenOceanAcoustic.d407-ci.service` —— **组织级**，标签 `self-hosted,Linux,X64`
  - `actions.runner.OpenOceanAcoustic-OpenOcean-Release.d407-release.service` —— **仓库级**，
    标签含 `openocean-release`，正是 `release.yml` 所要求
- `openocean-release` 标签路由已被实际运行中的发布任务证实
- docker 守护进程 running + enabled
- `OOA_FIELD_READ_TOKEN` 已配置为仓库 secret（`created_at` 2026-09-21T06:00:08Z）
- 存储根 **`/mnt/repo/ci`** 存在，五个子目录（`linux/ win/ cache/ staging/ releases/`）齐全且可写，
  与契约布局一致

### 2.2 发布包格式 —— 编排层

以下契约条款经代码核对为实现且强制生效：

- 源 ref 在 checkout 前解析为不可变 SHA，并在 checkout 后校验 `git rev-parse HEAD` 与工作区洁净度（`orchestrator.py:376-403`），不符则强制重取或抛错
- sealed 目录九项文件全部真实写入（非文档描述）
- `--resume` 仅当输入与输出哈希**双双匹配**时复用任务（`runtime.py:149-156`）
- WI / Couple 启用时**确实抛错**而非静默忽略（`config.py:174-175`），四种探测路径均验证
- 全量 profile 产物集精确为 4 native/OS + 2 Python bundle + 1 MATLAB toolbox，与契约无出入
- 发布拒绝已存在的 tag 与 Release（`github.py:59-70`）；日志结构化地排除在上传集之外
- 密钥脱敏完整覆盖持久日志、实时输出、结构化事件三条路径，配置缺失时**失败即报错**
- 编排器自带 20 个 unittest 全通过

### 2.3 Toolbox 适配器

源仓库 `OpenOcean-Field-Toolbox` 提供编排器要求的两个适配器脚本，接口无缺失：
`scripts/build_python_sdk.py`、`scripts/build_matlab_release.ps1`

## 三、缺口清单（按风险排序）

### 高风险

1. **验证树比 main 落后 30–32 个 commit。** 9 月 9 日的验收点在 `ci/self-hosted-linux-images` 分支，
   而 `release.yaml` 所有源的 `ref` 指向 `main`。验证点确为 main 直系祖先（未丢失），但落后的 commit 含实质改动：
   `json_support.hpp`(+780)、`bellhop_shd.hpp`(+186)、`bellhop_2d_migration.cpp`(+191/-188)，
   以及整套分发打包脚手架 —— 恰好压在"打包格式"这一审计目标上。
   **建议：对当前 main HEAD 重跑一轮镜像验收。**

2. **发布内容层保证未被端到端验证。** 编排器把 Python bundle 的 CPython 矩阵、facade wheel、四个 native wheel
   与 `install.py` 全部委托给私有适配器，且**不传递不校验**（仅检查目标文件存在，`orchestrator.py:706`）。
   MATLAB 的 UUID / R2023a 下限同样是配置断言 —— 编排器既不传 UUID 也不检查产出的 `.mltbx`。
   `minimum_release`、`embed_native_runtime`、`toolbox_identifier` 在 `config.py` 之外**零引用**。

3. **契约的消费者构建门禁与 dist 测试门禁不在 Release 仓库内。** 编排器调用
   `bash tools/linux_dist.sh --no-wheel`（cwd 为源仓库），门禁逻辑住在各 Field 源仓库内。
   该脚本自带 build+validate，`VALIDATION.md` 亦记录 NormalMode/PE "六组 SDK 通过 CTest、打包和消费者验证"。
   **需在源仓库侧确认门禁实际执行**，Release 侧无法证明。

### 中等风险

4. **`--rebuild` 对未知任务名静默无效且不级联**（`cli.py:24`、`orchestrator.py:84,296`）。
   拼写错误（如 `windows.pythn`）会"成功"复用陈旧产物。且只失效指定任务，下游任务因输入哈希
   基于已解析 SHA 而非上游输出，既不被失效也不重跑。
5. **`--resume <未知 id>` 不报错**（`runtime.py:132`），会静默新建一次发布。
6. **发布溯源无法自证**：`SHA256SUMS` 含 `release-notes.md` 条目，但该文件从未作为资产上传；
   `release-config.yaml` 既未上传也未校验，而已发布的 `release-lock.yaml` 携带其 `configSha256`。
7. **`containers/linux-release.Dockerfile` 是死代码/陷阱。** 它定义 manylinux_2_28 + `d5f19b59…`，
   与实际发布路径的 `ca93b681…` 无关，且 `tools/build_linux_release_image.sh` 无任何引用。
   两份定义漂移，将来照它构建即偏离验收基线。
8. **发布非原子**：先建 tag 再建 Release，中间失败会留下无 Release 的 tag，且该 ID 永久被拒。
9. **CI 不跑测试。** `release.yml` 只有 build/publish 两个 job，无任何测试调用；
   `tests/` 缺 `__init__.py`/`conftest.py`，`unittest discover -t .` 会失败。

### 低风险

10. **Toolbox 从未进过镜像验收**（`reports/` 与 `validation/` 中无其条目），
    且它是唯一没有 `.github/workflows/` 的 Field 仓库。适配器存在，但界面未经镜像验证。
11. **WASM 抑制不对称**：Windows 显式传 `-DOPENOCEAN_FIELD_DIST_WASM=OFF`，
    Linux 仅传 `--no-wheel`。不会实际泄漏（只复制一个归档），但 Linux 侧的抑制依赖私有脚本默认值。
12. **契约未说明五个源中哪四个产出 native 包**（Toolbox 有源无 native family），读者须从代码反推。
13. **`resolved-sources.json` 是 sealed 目录的第十个文件**，契约列表读作穷举但实际写十个。

## 三补、Windows VM 环境

**结论：满足契约。** VM 真实存在、正在运行、SSH 可达，且工具链满足契约全部要求 ——
由编排器自己的 Windows preflight 于 `2026-09-21T10:42:06Z`（即当前这次发布）**通过**所证实。

### VM 实例详情（自主机 QEMU 进程与运行日志重建）

| 属性 | 值 |
| --- | --- |
| 域名 | `windows-ci` |
| UUID | `bbd057b3-0f0b-400a-998d-7e055a5a6668` |
| 状态 | **运行中**（qemu PID 40521，启动于 9月20） |
| 固件 | OVMF UEFI |
| 机型 | `pc-q35-10.2`，`-accel kvm`，`-cpu host` 带 Hyper-V enlightenments |
| vCPU / 内存 | 6 vCPU / 16 GiB |
| 网络 | 用户态 NAT，`hostfwd tcp:127.0.0.1:22225-:22` |
| 沙箱 | `-sandbox on,obsolete=deny,elevateprivileges=deny,spawn=deny` |

### 一个重要且隐蔽的部署事实

**VM 不在系统 libvirt 域中，而运行在 `ci_server` 的用户态 libvirtd 会话里。**

- `virsh -c qemu:///system list --all` → **空**（连接正常，域列表确实为空）
- 实际 VM 位于 `/run/user/1008/libvirt/`，该目录 `drwx------`，属 `ci_server`

因此 `d407` 虽然在 `libvirt`(972) 与 `kvm`(991) 组内，但**那些组只够访问系统实例**，
看不到也控制不了该域。运维含义：**以 `d407` 身份运行流水线会发现 VM 不可见**；
流水线能跑通，仅因为 `actions-runner-release`（进而编排器）以 `ci_server` 身份运行，
而该会话拥有此 VM。**这一耦合是承重设计，且 `docs/runner-environment.md` 未记录** ——
文档描述的是 `sudo -u <service-account>` 调用控制器，却没说明 VM 根本不在系统 libvirt 域中。

### preflight 逐项断言结果（契约要求，全部通过）

| 要求 | 状态 | 佐证 |
| --- | --- | --- |
| MSVC 构建工具（拒绝 MinGW） | **具备** | vswhere + VC.Tools.x86.x64 通过；`MSVC 19.44.35228.0`；原生构建 **152/152 测试通过**；产物中 `libgcc\|libstdc++\|libwinpthread\|mingw` **零匹配** |
| MATLAB R2023a+，以 R2025b 测试 | **具备** | `version('-release')` = `2025b` |
| PATH 之外的构建 venv，含 cibuildwheel 3.4.0 | **具备** | preflight 精确断言版本并通过 |
| 持久 wheelhouse，cp310–cp314 离线依赖 | **具备且可用** | `C:\actions-runner\wheelhouse`，标记 `openocean-v2.complete` 存在；`windows.python` 本次成功构建五档 ABI，`--no-index --find-links` 验证有效 |

### 历史失败的根因与修复

两次失败**均为 Toolbox 侧缺陷，非 VM 问题**：

1. `2026.9.21.1` / `.2` 失败于 `windows.python`（superbuild CMake configure 失败）→ 修复于 `abe07b1`
2. `windows.matlab` 失败于版本断言 `Expected MATLAB R2025b, found 2025b` → 修复于 `0a8d195`

**趋势是收敛而非退化。** `.3` 已清过 `windows.python` 并推进到 MATLAB。

### 一处代码脆弱点

`orchestrator.py::_ensure_vm` 用**子串匹配**判断 VM 状态：
`vm_was_running = "running" in text.lower() and "not running" not in text.lower()`。
控制器输出格式一旦措辞变化（例如含 "not running" 或缺少 "running"）即翻转判断。
控制器实际输出格式本次无法核实。

## 四、无法核实项（授权边界内）

以下项目**不是"缺失"，而是"本次审计够不着"**，不应据此判定不满足：

1. **`/home/ci_server/.config/openocean/runner.yaml`** —— mode `600`，owner `ci_server`。
   此隔离由 `docs/runner-environment.md` 明文要求（"VM 私钥只有该服务账号可读"），
   属刻意设计而非配置疏漏。**审计未使用提权手段绕过该边界。**
   *实际影响有限*：其中原本最关键的 `linux.image` 值，已由运行日志独立确证（见"一补"）。
   仍无法直接核实的是各路径字面值，但均可由日志间接推得。
2. **VM 的直连视角** —— `/home/ci_server/runner-vm` 全目录（qcow2 磁盘、`OVMF_VARS.fd`、控制器脚本）、
   私有 SSH 密钥 `private/ci_ed25519`、ci_server 会话语 libvirt、`/run/user/1008`，均 `drwx------`。
   因此**未能直接核实**：Windows 版本（Server Core vs Desktop Experience 仍未确定）、
   磁盘剩余空间、guest `PATH`、**MinGW 是否安装**（只能说"未被使用且产物中无 MinGW DLL"，
   未观察到契约所述的"拒绝"行为本身）。
3. ~~**本地 docker 镜像清单**~~ —— **已补齐**，见"七、授权核查补录"。
4. **org 级 GitHub secrets / variables** —— `gh` 账号 `lyy-cn` 非 org admin（HTTP 403）。
   仓库级已确认：`OOA_FIELD_READ_TOKEN` 存在，`vars.OPENOCEAN_RUNNER_CONFIG` 未设置（走 `$HOME` 回落，正常）。

## 四补、两项需要你注意的偏差（非阻塞，但应知情）

1. **`/mnt/repo/ci` 授予了 `d407` 默认 ACL 写权限。** `getfacl` 显示 `user:d407:rwx` 与
   `default:user:d407:rwx`。契约措辞是"专属服务账号拥有发布存储"，
   该授权比措辞更宽。是否保留由你决定 —— 它让调试方便，但也意味着发布产物可被非服务账号改写。

2. **`containers/linux-release.Dockerfile` 与实际使用的镜像分属两套。** 详见缺口 7。
   另有一处细节：该 Dockerfile 声明的 `eigen3-devel` 在实际使用的 ci-wheel 镜像中**不存在**，
   今天不出问题**仅仅因为** Eigen 在各源仓库内 vendored。若将来有源仓库改用系统 Eigen，会踩空。

## 五、建议的下一步

按优先级：

1. 对当前 main HEAD（各仓库）重跑一轮 `ci-image` 验收 —— 消解缺口 1
2. ~~以 `ci_server` 身份执行 `docker images`~~ —— **已完成**，见"七"
3. 阅读各源仓库 `tools/linux_dist.sh` 与 `build_dist.py`，确认消费者构建与测试门禁的真实执行 —— 消解缺口 3
4. 给 Toolbox 补 CI workflow 并纳入镜像验收 —— 消解缺口 10
5. 修复 `--rebuild` 校验与 `--resume` 未知 id（缺口 4、5）—— 成本低、防误操作价值高
6. 决定 `containers/linux-release.Dockerfile` 的去留 —— **已定：删除**（见"七"）

## 七、授权核查补录（2026-09-21 晚）

应所有者明确授权，以只读方式补齐了前述权限边界内的项目。**未修改任何文件、未删除任何引用。**

### 7.1 docker 镜像清单 —— 三个验收镜像逐一吻合

```
openocean/ci-wheel:manylinux228-v1        ca93b68104a8   ← 发布实际使用的镜像
openocean/ci-native:ubuntu22.04-v1        0c7a6ef9bbdd
openocean/ci-wasm-web:emsdk6.0.8-node22.22.1-v1   eed4e55b976b
openocean/ci-dist:emsdk6.0.8-node22.22.1-eigen3-v1   c5097573d6b8
quay.io/pypa/manylinux_2_28_x86_64:2026.03.01-1      d5f19b5957cf
```

三个镜像的 id 与 `ci-image/validation-summary.json` 记录的 id **完全一致**。
**结论：验收时的镜像与当前机器上的镜像是同一个**，镜像漂移的疑虑彻底排除。

### 7.2 `openocean/field-release:2026.09` 从未被构建过

`docker images` 中**不存在**该镜像。库中只有它的 base
`quay.io/pypa/manylinux_2_28_x86_64:2026.03.01-1`（`d5f19b59`）。

**这加强了缺口 7 的结论**：`containers/linux-release.Dockerfile` 不仅无引用、且其产物从未存在。
它不是"备用镜像"，是一份从未兑现的定义。

### 7.3 `ci-dist:...-eigen3-v1` 与 Field 发布无关

带 `eigen3` 的镜像是 `ci-dist`（`c5097573d6b8`），从命名与用途看属 **WASM / 网站**那条线。
**它不是发布镜像，因此其 eigen3 不构成"发布镜像缺依赖"** —— 缺口 7 中关于 `eigen3-devel`
的最后一层疑虑就此闭合。

### 7.4 包结构实测（纠正审计时的推断）

**Windows 原生包为 4 段式**（实测 PE，147 条目，反斜杠路径）：

```
archives/            OpenOcean-Field-PE-2.0.0-windows-amd64-{shared,static}.zip
shared\bin\          DLL 与 standalone exe
shared\include\      openocean\field\pe\...
metadata\            DEPENDENCIES.md / LICENSE-DECLARATION.txt /
                     licenses\LICENSE / licenses\third-party\{eigen,nlohmann}\
```

契约的 `standalone_executables: true` 在此为实物
（`OpenOcean-Field-PE-{RAM,RAMGeo,RAMS}.exe`）。
`licenses/third-party/eigen/` 下有 Apache/BSD/GPL/LGPL/MINPACK/MPL2 六种许可文本，
`nlohmann/LICENSE.MIT` 亦在。

**纠正**：审计时基于 Linux 包推断的"`archives/ + static/ + shared/` 三段式"**不准确** ——
Windows 包有独立的顶层 `metadata/`，Linux 包没有。

**MATLAB toolbox 为标准 OOXML 包**：

```
[Content_Types].xml            _rels/.rels
_xmlsignatures/_rels/origin.sigs.rels
fsroot/+openocean/+builders/   Bellhop2D/3D/Nx2D, Kraken, Krakenc,
                               RAM, RAMGeo, RAMS, FieldCaseBuilder,
                               BellhopRun, NormalModeRun, PERun
fsroot/+openocean/+config/     FieldBellhopOptions, FieldExecution, ...
```

8 个后端各有 Builder 类，与 Python SDK 的 8 个 backend 对应。

**Windows Python bundle** 同为 26 条目结构，21 个 wheel（`win_amd64` 平台标签）。

### 7.5 仍存在的观察

`assets/` 下 Windows 产物权限为 `-rw-------`（600，且带 ACL `+`），
Linux 产物为 `-rw-rw-r--`（664）。两者不一致，成因是 Windows 包经 `scp` 从客机拷回、
Linux 包本地生成。**不构成功能缺陷**，已列入修复计划（A6，统一为 640）。
