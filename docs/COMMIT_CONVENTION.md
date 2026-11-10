# 提交信息规范

本仓库统一使用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 格式。
自动同步脚本生成的提交也遵循这套规则，因此 `git log` 里的历史是**机器可读、可分组**的。

---

## 一、格式

```
<类型>(<范围>): <一句话说明>

<正文：说明改了什么、为什么改>

<脚注：可选，如 BREAKING CHANGE、Refs>
```

### 标题行（必填）

- **类型**必须是下面之一：

  | 类型 | 含义 | 例子 |
  |---|---|---|
  | `feat` | 新增功能 | `feat(item): 增加传送卷轴` |
  | `fix` | 修复缺陷 | `fix(ui): 修复点过背包后方向键失效` |
  | `refactor` | 重构，不改行为 | `refactor(game_state): 抽出回合流水线` |
  | `perf` | 性能优化 | `perf(map_view): 增量刷新改为签名比对` |
  | `test` | 测试相关 | `test(save): 补充随机数复现用例` |
  | `docs` | 文档 | `docs(readme): 补充图标替换说明` |
  | `style` | 格式调整（不影响逻辑） | `style: 统一类型注解写法` |
  | `build` | 构建 / 依赖 | `build: 锁定 matplotlib 版本` |
  | `chore` | 杂项（脚本、配置） | `chore(sync): 自动同步 3 个文件` |

- **范围**用模块名，和目录结构对齐：`dungeon`、`ui`、`tools`、`tests`、`docs`、`assets`。
- **说明**用中文，动词开头，不超过 50 字，句末不加句号。

### 正文（推荐）

回答两个问题：**改了什么**、**为什么改**。一行一条要点即可。

### 脚注（可选）

- `BREAKING CHANGE: <说明>` —— 存档格式、配置字段等不兼容改动。
- `Refs: #12` —— 关联 Issue。

---

## 二、自动同步脚本生成的提交

`tools/auto_sync.py` 在检测到文件变化并静默若干秒后，会自动生成一条这样的提交：

```
chore(sync): 同步 3 个文件（ui、tools）

改动明细：
- 修改  ui/app.py            +12 -4
- 新增  tools/auto_sync.py   +168 -0
- 删除  data/saves/old.json  -3 -0

涉及模块：ui、tools
合计：3 个文件，+177 -4
目的：把焦点回收逻辑抽成 _focus_map()
```

| 部分 | 来源 | 说明 |
|---|---|---|
| 标题 | 自动 | `chore(sync): 同步 N 个文件（模块列表）` |
| 改动明细 | `git diff --cached --numstat` | 新增 / 修改 / 删除 + 增删行数 |
| 涉及模块 | 变更文件的一级目录 | 便于回溯改了哪一块 |
| 目的 | `--note` 参数或 `SYNC_NOTE.txt` | **建议写一句人话**，否则填"例行保存自动提交" |

> 想让自动提交也带上一句有意义的目的，只要在项目根目录放一个 `SYNC_NOTE.txt`
> 写上这一轮改动的原因，脚本会读走并删除它；也可以在启动脚本时用
> `python tools/auto_sync.py --note "把焦点回收抽成 _focus_map()"`。

---

## 三、手动提交示例

```
feat(icons): 新增可替换的图标资源清单

把地图图标抽成 assets/icons.json 描述 + 两级查找（专属→类别→通用），
用户把 PNG 放到 assets/icons/ 下即可替换，缺图自动回退字符。
支持 F12 热重载。

Refs: #8
```

```
fix(ui): 修复点过背包后键盘全失效

Tk 的 listbox.tcl 在 Button-1 时无条件抢焦点，_on_key 的守卫把 Listbox
整个拉黑，导致方向键、I、> 全部失效。改为"控件 + 按键白名单"，
并在使用道具、点击地图、关闭弹窗、按 Esc 时主动回收焦点。
```

---

## 四、提交前自检

1. `python -m unittest discover -s tests` 全绿（当前 64 个用例）；
2. 没有把 `data/saves/*.json`、`data/records.json` 这类运行时状态提交上去
   （`.gitignore` 已拦截，但 `git add -f` 会绕过）；
3. 没有提交任何令牌、密码、绝对路径里带用户名的临时文件。
