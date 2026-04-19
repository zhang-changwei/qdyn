# Contributing Guide

本文件定义 QDYN 的日常开发与提交规范。目标是让代码保持一致、易读、易维护，并尽量减少无关重构。

## General Principles

- 优先保持与现有模块风格一致，再考虑个人偏好。
- 修改应聚焦问题本身，避免顺手修复无关逻辑。
- 对外暴露接口优先保证可读性、类型清晰、文档完整。
- 复杂逻辑优先拆成私有辅助函数，减少嵌套层级。

## Naming

- 变量、函数、模块使用 `snake_case`。
- 类使用驼峰命名，如 `MainWorkflow`、`NVTInputT`。
- 常量使用全大写，如 `MAX_NVT_RETRIES`。
- 专业缩写可保留全大写，如 `VBM`、`CBM`。
- 单字符变量仅限简单索引 `i`、`j` 和哑变量 `_`。
- 模块内辅助函数、内部变量、内部方法统一使用单下划线前缀，如 `_parse_value_string()`。

## Size and Layout

- 90% 的代码行应控制在 90 列以内，99% 应控制在 100 列以内。
- 单个 Python 文件建议少于 1000 行；超过后应优先考虑拆分模块。
- 超长函数应拆分为几个语义明确的私有函数，而不是继续增加分支和缩进。

## Typing

- 统一使用现代类型标注：
  - 用 `X | None`，不用 `Optional[X]`
  - 用 `list[T]`、`dict[K, V]`、`tuple[T1, T2]`，不用 `List`、`Dict`、`Tuple`
- 对外暴露函数必须完整标注参数和返回值。
- 内部辅助函数若逻辑简单可适度放宽，但新增或重构代码仍推荐补全类型。
- 类型优先表达真实语义，避免无意义的 `Any` 扩散。

## Docstring

- 对外暴露接口必须提供完整 docstring，统一使用 Google 风格。
- 若函数已有完善类型标注，docstring 中不重复书写类型。
- `Args:`、`Returns:`、`Raises:` 只描述语义，不重复类型声明。
- 参数说明应直接说明“这个参数控制什么”，不要写空泛废话。
- 对复杂返回类型，docstring 中只写基础类型，便于编辑器解析。例如：
  - 类型标注：`dict[str, Any]`
  - docstring：`Returns: dict: Parsed MD data.`
- 若函数本身没有参数说明，保持简洁，不强行扩写空说明。
- 推荐写法示例：

```python
def run_nvt(
    temperature: float,
    plot: bool = False,
) -> dict[str, Any]:
    """Run an NVT simulation.

    Args:
        temperature: Target MD temperature in Kelvin.
        plot: Whether to write summary plots after the run.

    Returns:
        dict: Output metadata and generated file paths.
    """
```

## Recommended Workflow

- 安装依赖：`uv sync`
- 运行测试：`uv run pytest`
- 建议在提交前至少完成：
  - 相关测试通过
  - 新增公共接口具备类型标注与 docstring
  - 无明显超长函数、超长文件、超宽代码行
- 推荐后续引入 `ruff` 作为统一的 lint / import 排序工具，但当前阶段不作为硬性门禁。

## Git Commits

- 推荐使用 Conventional Commits，并带模块 scope：
  - `feat(workflow): add fused scf prenamd flow`
  - `fix(input): handle missing stru_format`
  - `refactor(tools): split namd resource helpers`
- 当提交中包含重要背景、兼容性说明、后续动作或影响面时，使用多行提交模式补充正文。例如：

```text
feat(workflow): add fused scf prenamd flow

- reuse SCF worker resources for fused dispatch
- keep single-node override for fused execution
- preserve existing pre_namd output contract
```

- 推荐类型：
  - `feat`：新功能
  - `fix`：缺陷修复
  - `refactor`：重构但不改变行为
  - `style`：纯风格调整
  - `tests`：测试相关
  - `docs`：文档修改
  - `chore`：杂项维护
- 提交标题建议使用英文短句，聚焦单一改动，不要把多个不相关改动混入一次提交。
- 提交正文建议补充以下信息中的 1-3 项：
  - 改动动机
  - 核心实现点
  - 兼容性或配置迁移提示
  - 未覆盖的后续事项
