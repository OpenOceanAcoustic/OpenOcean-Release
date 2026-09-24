# OpenOcean-Field-V1.0.1 Release Notes

**OpenOcean-Field-V1.0.1** 在 V1.0.0 的基础上重打 MATLAB Toolbox，核心变化是**离线帮助文档全面双语化**，并补齐参数检索与角度个数（Nbeams）文档。原生运行时沿用与 V1.0.0 相同的一组源码 commit，本次不重编译数值后端。

## ✨ 本次变化（MATLAB Toolbox）

- **中英文切换**：所有帮助页默认中文，右上角 `中文 / English` 切换并记忆选择。8 个手写指南（入门、单模型、参数参考、多模型、结果绘图、算例、故障排查、首页）与自动生成的 API/参数页全部双语。
- **参数检索**：新增 `openocean.parameters("angle")`，在命令窗口按关键词检索 setter 与参数，中英文关键词均可匹配。
- **参数索引 / Parameter index**：新增可即时过滤的参数索引页，列出全部 setter 的名称、签名、默认值、单位与约束；参数表头与说明双语。
- **角度个数（Bellhop Nbeams）文档修正**：明确 `Source.setLaunchAngleGridDeg(first, last, count)` 的第三个参数是**个数**而非步长，默认 ±20°、121 条；修正原先 “start, step, stop” 的错误说明。
- **三维对等 setter**：新增 `Options.setElevationAngleGridDeg` 与 `Options.setRayBearingAngleGridDeg`。
- **新算例与工具**：新增可运行的 `bellhop2d_angles`（61/121/401 条射线传播损失对比）；源码根目录新增 `Setup`，一键加入路径并运行 `openocean.doctor()`。
- **排障**：明确 `Unrecognized function or variable 'openocean.bellhop2d'` 的四类原因，关键是必须把包父目录 `toolbox` 加入路径。

## 🔒 平台与资产

- 平台：Windows x64；MATLAB R2023a 或更高（测试 R2025b）。
- MATLAB 包：`OpenOcean-Field-Toolbox-1.0.1-win64.zip`，内含 `OpenOcean-Field-Toolbox-1.0.1-win64.mltbx` 与 `examples/reference/cases/`。
- 其余产品资产（原生 SDK、Python wheel 合集）保持 V1.0.0 不变。

---

# OpenOcean-Field-V1.0.1 Release Notes (English)

V1.0.1 rebuilds the MATLAB Toolbox on top of V1.0.0. The main change is a fully **bilingual offline help system**, together with keyword parameter search and corrected beam-angle (Nbeams) documentation. The native runtime is built from the same source commits as V1.0.0; no numerical backend was changed.

## ✨ Changes (MATLAB Toolbox)

- **Chinese/English toggle** on every help page, defaulting to Chinese and remembered across pages. Eight hand-written guides plus all generated API/parameter pages ship both languages.
- **Parameter search**: new `openocean.parameters("angle")` command-window search over setters and their parameters; Chinese and English keywords both match.
- **Parameter index**: a filterable page listing every setter with signature, defaults, units and constraints; bilingual headers and descriptions.
- **Angle-count (Bellhop Nbeams) documentation** corrected: the third argument of `Source.setLaunchAngleGridDeg(first, last, count)` is a **count**, not a step; default is 121 angles over ±20°.
- **3-D parity setters**: `Options.setElevationAngleGridDeg` and `Options.setRayBearingAngleGridDeg`.
- **New example and helper**: runnable `bellhop2d_angles` (61/121/401 rays) and a source-checkout `Setup` helper.
- **Troubleshooting**: the four causes of `Unrecognized function or variable 'openocean.bellhop2d'`, with the package-parent `toolbox` path requirement.

## 🔒 Platform and assets

- Windows x64, MATLAB R2023a or later (tested with R2025b).
- MATLAB asset: `OpenOcean-Field-Toolbox-1.0.1-win64.zip`, containing `OpenOcean-Field-Toolbox-1.0.1-win64.mltbx` and `examples/reference/cases/`.
- The other product assets (native SDKs, Python wheel bundles) are unchanged from V1.0.0.
