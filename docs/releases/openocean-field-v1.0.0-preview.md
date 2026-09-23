# OpenOcean-Field-V1.0.0 发布预览

状态：**用户已确认补齐 WI / Couple Toolbox 后发布；集成验收中，尚未创建远端 tag 或 Release。**

本文件记录待审阅的发布形式与实施范围；对外正文见 [Release Notes 草稿](openocean-field-v1.0.0.md)。正文描述的是本次目标交付内容，不能作为全部构建和验收已经完成的证明。

## 发布身份

| 项目 | 计划值 |
| --- | --- |
| 发布仓库 | `OpenOceanAcoustic/OpenOcean-Release` |
| Release 标题 | `OpenOcean-Field-V1.0.0` |
| Git tag | `OpenOcean-Field-V1.0.0` |
| 套件 / 外层产品包版本 | `1.0.0` |
| 类型 | 正式 Release |
| 文案风格 | 参考 [RayMode v1.1.0](https://github.com/OpenOceanAcoustic/OpenOcean-Field-RayMode/releases/tag/v1.1.0)，使用中文说明、功能列表、下载说明、兼容性与鸣谢 |

沿用现有 `组件-版本-平台` 文件名，不合并成单一大 ZIP。套件版本不强制覆盖各原生组件自身的版本、SONAME、CMake 包版本或 wheel 依赖约束。

## 产品范围

用户已确认：Windows 全量包含 WI 和 Couple，补齐发布适配后一起发布。

| 产品 | Windows x64 | Linux x86_64 |
| --- | --- | --- |
| Core / RayMode / NormalMode / PE / WI / Couple 原生 SDK | 六个 ZIP，包含 shared / static 交付 | 不公开上传 |
| Python | 一个 ZIP wheel 合集，覆盖六组件及 Toolbox Python facade | 一个 tar.gz wheel 合集，覆盖同样组件 |
| MATLAB Toolbox | 一个 ZIP，包含 `.mltbx` 与参考算例 | 不发布 |

合计 **9 个产品附件 + 5 个校验 / 追溯附件**。GitHub 自动提供的源码 ZIP / tar.gz 是 Release 仓库源码快照，不计入产品包，也不代表全部模型源码合集。

Linux 的 tar.gz 仅是 wheel 合集的压缩容器，里面的 OpenOcean 二进制分发形式仍为 `.whl`。没有独立 Linux SDK / CLI 附件；wheel 自身携带运行需要的本机二进制。

当前没有 Linux aarch64 wheel 产品矩阵。本次公开 wheels 面向 x86_64；aarch64 与 x86 系列 Linux 原生库的联系说明统一使用 `qianp3@mail.sysu.edu.cn`。

WASM 和独立 FieldRunner 沿用现有 Release 契约，不列为本次公开产品附件。各模型的 WASM CI 不因此取消。

## 压缩包内部形式

Windows 原生 SDK 沿用各模型的 dist 结构：`shared/`、`static/` 和组件清单；保留模型自身提供的元数据与附加目录。头文件、库、CMake 配置及适用的 CLI 位于相应安装树内，并随包提供许可证说明。Core 不因此被承诺具有模型求解 CLI。

Python 两个平台保持相同的目录形式：

```text
install.py
README.md
manifest.json
wheels/
  openocean_field-...whl
  openocean_field_core-...whl
  openocean_field_bellhop-...whl
  openocean_field_normal_mode-...whl
  openocean_field_pe-...whl
  openocean_field_wi-...whl
  openocean_field_couple-...whl
```

覆盖 CPython 3.10–3.14。带 FieldCore provider 的原生 wheels 均按 CPython ABI 构建，包括 Couple；Couple 的 standalone ctypes-only 构建仍保留 `py3-none` 形式。第三方运行依赖由 pip 安装，不将开发 wheelhouse 宣称为随包离线依赖集。

MATLAB 形式保持为：

```text
OpenOcean-Field-Toolbox-1.0.0-win64.mltbx
examples/reference/cases/
```

WI / Couple 同时接入 MATLAB / Python Toolbox：单模型 `oast()`、`couple()`，多模型 FieldCase，以及统一 `[frequency, source, bearing, depth, range]` FieldView。

## 已核对的源码基线

以下为 2026-09-23 预览时核对的基线，后续发布适配改动需要记录新的不可变 SHA，最终以 `release-lock.yaml` 为准。

| 仓库 | 基线 commit | 状态 |
| --- | --- | --- |
| Release | `bfc6be0247c428c95430761c92363401e3e29e9c` | 当前 main；需支持本次版本与 tag 形式，并接入 WI / Couple |
| Core | `11e2e68e96f776636eb68d270de785dd52c2ba0a` | main |
| RayMode | `0d17aaef1fd425d704b83077aa24c551340f257f` | main，包含 PR #85 |
| NormalMode | `b9c74d61a03c973ff8a201d1d1455523213e1c4e` | main，包含 PR #18 |
| PE | `b9efda4bc1c09de6a00d80d9dcaabe1dda06433d` | main，包含 PR #16 |
| WI | `41e67c44a51f751aa67fa4d9d95c3744517e5728` | main，包含 PR #6 |
| Couple | `e8778f7197c64f5ed8e79396b8dd2dc5b161b4f9` | main，包含 PR #10 |
| Toolbox | `4f0f3910dc5d1cf6c806161ed4ec3f4e93dea3f3` | PR #6 尚未合并；包含 `pwd/cache` 修复，Linux 与 Windows MATLAB CI 均通过 |

Toolbox 的缓存修复必须包含在发布源码中，不能继续使用当前 `release.yaml` 的旧 pin；可以锁定已验收提交，不以预览为由自行合并 PR。

## 发布验收

发布适配器已扩展到六组件与十后端，支持版本 `1.0.0` 和精确 tag。
必须使用集成提交的不可变 SHA 构建 Windows 六组件 SDK、两平台五种 CPython ABI
的 wheel 合集和 Windows MATLAB Toolbox。全部产物门禁通过后生成配置、源码锁、
manifest、测试摘要和 SHA-256，再创建正式 Release。实际验收结果以最终随包
`test-summary.json` 为准。
