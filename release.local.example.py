"""全量编译 + 全量公开发布示例。

gh auth login                 # 本机使用自己的 GitHub 登录，无需 export token
python3 main.py init           # 生成 Git 忽略的 release.local.py
# 在 release.local.py 中修改 ref、产物、版本和发布文字
python3 main.py plan           # 本机查看计划，不需要 runner.yaml
python3 main.py submit release # ci_server 编译、测试、封存并公开发布

如果只想预览：先把最后的 publish(True) 改为 publish(False)，
再执行 python3 main.py submit preview。
本机不填 runner.yaml、服务器路径或 SSH 密钥；编译和取源码在 ci_server 执行。
实际产物路径与校验和见 Actions 运行摘要。
"""

from openocean_release.plan import Model, Platform, ReleasePlan

plan = ReleasePlan()

# 1. 源码：七个库都列出来，方便逐项修改。
# ref 可以是精确 SHA、tag 或分支（例如 "main"、"feature/docs"）。
# 下面是已有的固定基线；只改需要更新的库，其余沿用固定 SHA。
# 正式发布要求实际使用的每个 SHA 都通过各源码库自己的 CI。
# 当前 NormalMode、PE 的旧 SHA 缺少所需 CI 记录；正式全量发布前，
# 请替换为 CI 成功的 ref，或在源码库补齐这些 SHA 的 CI。
# 注释某一行 ref()，该库便沿用 ReleasePlan 中的默认固定 SHA。
plan.ref(Model.FIELD_CORE, "1a2d384f478b321d7311a32ee293e076ee5fb5ba")
plan.ref(Model.RAY_MODE, "cb36802e869b022e0a4e9dc90a1162811f7a9b84")
plan.ref(Model.NORMAL_MODE, "b9c74d61a03c973ff8a201d1d1455523213e1c4e")
plan.ref(Model.PE, "b9efda4bc1c09de6a00d80d9dcaabe1dda06433d")
plan.ref(Model.TOOLBOX, "6a051ca3ea338f0b426ccca25f2b04428186ed1b")
plan.ref(Model.WI, "5028741e9827729cd1b8394da545843c141ea627")
plan.ref(Model.COUPLE, "c7f6ce321e4a017070b101979a4b11e92d5c4089")

# 2. 本次执行编译、测试和封存。
plan.build(True)

# 3. 六个模型库的原生包：Linux + Windows，包含 shared/static 库。
# 只要单库包时，保留所需 Model，并注释下面的 Python、MATLAB 选择。
# 不参与构建的库若改过 ref，其 ref() 行也要注释，恢复默认值。
# native() 每次调用都会替换原生库选择；platforms 决定编译哪些平台。
plan.native(
    Model.FIELD_CORE,
    Model.RAY_MODE,
    Model.NORMAL_MODE,
    Model.PE,
    Model.WI,
    Model.COUPLE,
    platforms=(Platform.LINUX, Platform.WINDOWS),
)

# 4. Python 集成包：Linux + Windows，CPython 3.10–3.14 全部 ABI。
# 不需要 Python 包就注释这一行；只要 Linux 可改成 plan.python(Platform.LINUX)。
# Python 集成包会自动使用全部七个源码库。
plan.python(Platform.LINUX, Platform.WINDOWS)

# 5. MATLAB 集成包：Windows x64，完整重编并在 R2025b 测试。
# 不需要 MATLAB 包可改成 False 或注释这一行。
# MATLAB 集成包同样会自动使用全部七个源码库。
plan.matlab(True)

# 6. 发布版本。"auto" 自动分配 YYYY.M.D.N；也可改为 "1.2.3"。
# 新编译应使用尚未封存的新版本。
plan.version("auto")

# 7. GitHub Release 的 Markdown 发布正文，会随构建一起封存。
# 把下面的文字替换成自己的更新说明；留空字符串则生成自动说明。
plan.notes(
    """# OpenOcean Field 全量发布

## 更新内容
- 在这里填写各模型库的改动。
- 在这里填写 Python SDK、MATLAB Toolbox 和文档的改动。

## 本次产物
- FieldCore、RayMode、NormalMode、PE、WI、Couple：Linux / Windows 原生包。
- Python SDK：Linux / Windows，支持 CPython 3.10–3.14。
- MATLAB Toolbox：Windows x64，支持 MATLAB R2023a 及以上。

## 验证
- 各源码库在本次锁定 SHA 上的 CI 已通过。
- 本次所选产物的编译和测试结果随封存版本保存。
"""
)

# 8. 这是“全量公开发布”示例，所以显式开启公开发布。
# True：submit release 封存成功后创建公开 tag 和 GitHub Release。
# False：只编译、测试、封存；也用于 submit preview。
# ReleasePlan 自身的默认值仍是 False，只有这一行显式开启。
plan.publish(True)

# 另一个独立用法：以后公开已封存版本，不重新编译。
# 如需使用，把上面的整个 plan 配置替换为：
# plan = ReleasePlan().existing_release("2026.9.26.1").publish(True)
