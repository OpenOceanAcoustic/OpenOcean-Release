# OpenOcean-Field-V1.0.0 Release Notes

**OpenOcean-Field-V1.0.0** 汇集 OpenOcean 声场计算组件，面向原生 C/C++、Python 和 MATLAB 用户提供按平台组织的安装包。本次发布覆盖 **Core、RayMode、NormalMode、PE、WI 和 Couple**，并提供配套的 **OpenOcean Field Toolbox**。

---

## ✨ 本次发布

- **原生计算组件**：Windows x64 提供六个组件的独立 SDK，包含动态库、静态库、开发头文件、CMake 配置及各模型提供的命令行程序。
- **Python wheel 合集**：Windows x64 与 Linux x86_64 分别提供安装包，包含 Core、RayMode、NormalMode、PE、WI、Couple 的 Python bindings，以及 `openocean-field` 工具箱接口。安装脚本根据当前 Python 环境选择兼容的 wheel。
- **MATLAB Toolbox**：Windows 安装包包含 `.mltbx`、原生运行程序、离线帮助和配套参考算例。

Toolbox 的 MATLAB / Python 统一 Builder 入口支持 Bellhop 2D / 3D / Nx2D、KRAKEN / KRAKENC、RAM / RAMGeo / RAMS、WI（OAST）和 Couple，共十个后端。WI 与 Couple 支持单模型调用、FieldCase 多模型编排及统一 FieldView 输出，同时提供原生 SDK 和各自的 Python bindings。

## 🛠 接口与使用体验

- 完善 Builder 输入、结果契约和 FieldView 接口。Toolbox 的 MATLAB / Python 完整声场维度为 `[frequency, source, bearing, depth, range]`，二维切片保持 `[depth, range]`，新增维度置于前面。
- MATLAB 默认将运行目录创建在当前工作目录的 `cache/` 下，每次运行使用独立子目录；可通过 `result.Directory` 查看位置，也可显式指定输出目录。支持相应文件输出的求解模式将 `.shd` 等结果保存在运行目录中。
- 附带组件清单、源码版本记录、测试摘要和 SHA-256 校验文件，便于核对所下载的发布包。

---

## 📦 下载选择

| 用途 | 下载附件 |
| --- | --- |
| Windows：Core 原生 SDK | `OpenOcean-Field-Core-1.0.0-windows-x86_64.zip` |
| Windows：RayMode 原生 SDK | `OpenOcean-Field-RayMode-1.0.0-windows-x86_64.zip` |
| Windows：NormalMode 原生 SDK | `OpenOcean-Field-NormalMode-1.0.0-windows-x86_64.zip` |
| Windows：PE 原生 SDK | `OpenOcean-Field-PE-1.0.0-windows-x86_64.zip` |
| Windows：WI 原生 SDK | `OpenOcean-Field-WI-1.0.0-windows-x86_64.zip` |
| Windows：Couple 原生 SDK | `OpenOcean-Field-Couple-1.0.0-windows-x86_64.zip` |
| Windows：Python wheel 合集 | `OpenOcean-Field-Python-1.0.0-windows-x86_64.zip` |
| Linux：Python wheel 合集 | `OpenOcean-Field-Python-1.0.0-linux-x86_64.tar.gz` |
| Windows：MATLAB Toolbox 与参考算例 | `OpenOcean-Field-Toolbox-1.0.0-win64.zip` |

Python 用户解压对应平台的合集后，在目标 Python 环境中执行 `python install.py`。合集中提供 OpenOcean wheels；NumPy 等第三方依赖由 pip 按需安装。

MATLAB 用户解压 Toolbox ZIP，安装其中的 `OpenOcean-Field-Toolbox-1.0.0-win64.mltbx`；参考算例位于同一 ZIP 的 `examples/reference/cases/` 目录。

同时提供 `SHA256SUMS`、`manifest.json`、`release-config.yaml`、`release-lock.yaml` 和 `test-summary.json`。

## 🧪 平台与兼容性

- **Windows 原生 SDK**：x64，MSVC 工具链；C++ 开发接口要求 C++17 或以上。
- **Python**：CPython 3.10–3.14，Windows x64 / Linux x86_64；以 wheel 标记的系统和 ABI 兼容性为准。
- **MATLAB**：Windows x64，R2023a 或以上；发布验收使用 R2025b。
- 本次 Linux 公开附件仅提供 Python wheel 合集。**Linux aarch64 及 x86 系列的原生库，请联系 [qianp3@mail.sysu.edu.cn](mailto:qianp3@mail.sysu.edu.cn)。**
- 本次沿用 Release 当前产品包形式，不单独发布 WASM 包或 FieldRunner 安装包。

`1.0.0` 为本次套件版本；各组件内部版本与 ABI 信息以包内清单为准。已有项目迁移时，请参照随包 API 文档核对输入与结果接口。

---

## 🙏 鸣谢

特别鸣谢 **OpenOceanAcoustic 实验室 @ 中山大学** 对本项目研发、测试与开源工作的支持。

欢迎通过 [Issues](https://github.com/OpenOceanAcoustic/OpenOcean-Release/issues) 提交使用反馈与功能建议。

—— OpenOcean 开发团队
