# 地下城探险 · Dungeon Delve

Python 课程大作业：一个用 **纯 Python + tkinter** 实现的回合制地牢探险 Roguelike。
程序化生成地图、回合制战斗、道具与装备、JSON 存档、matplotlib 数据可视化统计。

---

## 快速开始

```bash
# 0) 克隆仓库
git clone https://github.com/Physi11/python_game.git
cd python_game

# 1) 安装依赖（只有图表功能需要，游戏本体仅依赖标准库）
pip install -r requirements.txt

# 2) 启动游戏
python main.py
```

Windows 用户也可以直接双击 `run.bat`。

> **注意**：本项目需要带 `tkinter` 的 Python。若启动时报"缺少 tkinter"，
> 请改用官方版 Python（安装时勾选 tcl/tk）运行，例如 `D:\python\python.exe main.py`。

---

## 玩法

你是踏入地下城的冒险者，目标是下到 **第 10 层** 击败 **深渊领主**。

- 撞向怪物即发起攻击（不需要单独的"攻击"键）
- 地图有战争迷雾：走过的地方会变暗，没走过的地方一片漆黑
- 每层至少有一瓶治疗药水，走遍全图再下楼能拿到更多装备
- 进入第 10 层时会自动回满生命——最终战是一场公平的决斗
- 死亡、通关或超时都会自动把本局数据写入 `data/records.json`，可在「查看 → 统计图表」里看分析

---

## 快捷键

| 按键 | 功能 |
|---|---|
| `↑ ↓ ← →` / `W A S D` | 移动；朝怪物方向移动即攻击 |
| `空格` | 原地等待一回合 |
| `G` | 拾取脚下道具；站在楼梯上则直接下楼 |
| `1` ~ `9` | 快速使用背包中对应编号的道具 |
| `I` | 打开 / 关闭背包 |
| `>` | 站在楼梯上时进入下一层（按 `G` 或点击脚下也可以） |
| `F5` / `Ctrl+S` | 保存到 1 号存档槽 |
| `F9` / `Ctrl+O` | 读取 1 号存档槽 |
| `N` | 开始新的一局 |
| `M` | 打开统计图表 |
| `F12` | 重载图标资源（换完 PNG 不用重启） |
| `Esc` | 从背包列表 / 日志区把焦点交还地图 |
| `?` | 操作说明 |
| 鼠标左键 | 点击相邻格移动或攻击；点击自己所在格拾取道具或下楼 |
| 鼠标悬停 | 查看该格的怪物或道具详情 |

---

## 项目结构

```
main.py                  程序入口（环境自检 + 顶层异常兜底）
run.bat                  双击启动游戏
auto_sync.bat            双击启动"自动提交推送"监听
.gitignore               版本库忽略规则
.gitattributes           二进制文件与换行符声明
dungeon/                 纯逻辑层，不依赖任何界面库
  config.py                全部常量与数值平衡参数
  rng.py                   随机数封装（种子 + 状态导出/恢复）
  dungeon.py               地形、房间、地图生成、视野、BFS
  entity.py                实体基类（坐标 / 生命 / 受伤 / 治疗）
  player.py                玩家（等级、背包、装备、统计计数）
  monster.py               怪物物种表与三种 AI
  item.py                  药水 / 武器 / 护甲 / 卷轴与掉落表
  combat.py                纯函数战斗结算（命中 / 暴击 / 伤害公式）
  game_state.py            回合状态机、事件队列、胜负判定
  save_manager.py          JSON 存档、版本迁移、原子写入、战绩追加
  stats.py                 对局数据聚合（纯 Python + 可选 pandas）
ui/                      表现层，只负责画和收输入
  theme.py                 配色、字体探测、DPI 感知
  map_view.py              Canvas 地图渲染（图元缓存 + 增量刷新）
  icons.py                 图标清单解析与键查找（纯数据，可无头单测）
  icon_set.py              图标图片加载、缩放、迷雾变暗版（tkinter + Pillow）
  panels.py                状态面板与日志面板
  dialogs.py               帮助 / 背包 / 结算 / 排行榜 / 图表窗口
  charts.py                matplotlib 图表构建
  app.py                   主窗口、菜单、键鼠绑定
assets/
  icons.json               图标资源清单（唯一需要改的配置文件）
  icons/                   图标 PNG 放这里，缺图自动回退字符
tools/                   辅助脚本
  auto_sync.py             监听代码改动，自动提交并推送（带变更日志）
  balance_sim.py           无界面批量自动对局（冒烟测试 + 平衡验证）
  make_charts.py           导出图表 PNG 到 data/charts/
  draw_flowchart.py        绘制三张流程图到 docs/flowcharts/
  capture_ui.py            自动驱动界面并截图到 docs/screenshots/
  export_icon_slots.py     按清单导出 24×24 占位图标模板（可选）
tests/                   单元测试（unittest，无需显示器）
data/                    运行时数据（存档、战绩、图表）
docs/                    实验报告、流程图、界面截图、提交规范
```

---

## 开发者命令

```bash
# 跑全部单元测试（64 个用例）
python -m unittest discover -s tests -v

# 批量自动对局（验证数值平衡，并把结果写入战绩文件）
python tools/balance_sim.py --games 30 --record

# 生成统计图表到 data/charts/
python tools/make_charts.py

# 生成三张流程图到 docs/flowcharts/
python tools/draw_flowchart.py

# 自动驱动界面并截图到 docs/screenshots/
python tools/capture_ui.py

# 按图标清单导出 24×24 占位图标模板（可选，想自己画图标时用）
python tools/export_icon_slots.py
```

实验报告由 `docs/report_source.md` 生成（需要本机运行 WorkBuddy 的本地 Office 服务）：

```bash
python tools/build_report.py     # 组装 docs/Python程序设计课程报告.docx
python tools/preview_docx.py     # 借助 Word 导出 PDF 再逐页渲染，用于校版
```

---

## 版本控制与自动同步

### 仓库约定

`.gitignore` 已经排除掉"不该进版本库"的三类东西：

| 排除项 | 原因 |
|---|---|
| `__pycache__/`、`*.pyc` | 字节码，每台机器都不一样 |
| `data/saves/*.json`、`data/records.json` | 存档与战绩是**本机运行时状态**，会随每次游玩变化 |
| `.workbuddy/`、`*.log`、`*.tmp`、`docs/report_preview/` | 本机工作数据与临时产物 |

> 图表 `data/charts/*.png`、报告 `docs/*.docx`、截图 `docs/screenshots/*.png`
> 是**交付物**，正常提交。仓库总大小约 3.5 MB，不需要 Git LFS。

### 提交信息规范

完整规则见 [`docs/COMMIT_CONVENTION.md`](docs/COMMIT_CONVENTION.md)，核心是 Conventional Commits：

```
<类型>(<范围>): <一句话说明>

<正文：改了什么、为什么改>
```

类型用 `feat` / `fix` / `refactor` / `perf` / `test` / `docs` / `style` / `build` / `chore`，
范围用模块名（`dungeon`、`ui`、`tools`、`tests`、`docs`、`assets`）。

### 首次关联远程仓库

```bash
# 1) 登录 GitHub（只需一次，会打开浏览器）
gh auth login

# 2) 关联远程仓库
git remote add origin https://github.com/<你的用户名>/<仓库名>.git

# 3) 首次推送并建立上游关联
git push -u origin main
```

登录后 `gh` 会自动配好 git 的凭据助手，之后 `git push` 不再需要输密码。

### 自动提交推送

```bash
python tools/auto_sync.py                # 常驻监听，Ctrl+C 退出
python tools/auto_sync.py --once         # 只同步一次（适合定时任务）
python tools/auto_sync.py --dry-run      # 只打印将要提交的内容，不落盘
python tools/auto_sync.py --note "修了什么"   # 给这次提交写一句目的
```

Windows 下直接双击 **`auto_sync.bat`** 即可常驻。

工作方式：每 3 秒看一眼 `git status`，一旦发现改动，**等它静默 20 秒**
（避免改一个函数就提交一次）再 `add → commit → push`。用 `git status` 而不是
自己遍历文件，是为了自动遵守 `.gitignore`，也能正确处理删除、重命名和二进制文件。

自动生成的提交长这样：

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

**想让自动提交也带上"为什么改"**，有两种方式（都不需要改代码）：

1. 启动时加 `--note "..."`，这条说明只用于**下一次**提交；
2. 在项目根目录放一个 `SYNC_NOTE.txt` 写上目的，脚本会在提交时读走并删除它，
   适合"边写代码边记一笔"的场景。

监听日志写在 `.git/auto_sync.log`（在 `.git` 内部，不会被提交）。

---

## 图标资源替换

地图上的玩家、怪物、道具、楼梯、门都支持换成自己的图片，**不需要改任何代码**。

### 三步替换

1. 准备一张 **24 × 24 像素、带透明通道的 PNG**（尺寸不符也能用，程序会自动缩放；
   但没有透明通道的话会带一个白底方块）。
2. 按 `assets/icons.json` 里登记的路径放进去，例如
   `assets/icons/player.png`、`assets/icons/monster/goblin.png`。
3. 回到游戏按 **F12**（或菜单「查看 → 重载图标资源」），立即生效，不用重启。

删掉某个 PNG，对应图标就自动回退成原来的字符（`@`、`g`、`/`、`↓`…），
所以**整个 `assets/icons/` 是空的也不影响运行**，开箱就是纯字符外观。

### 清单文件的结构

`assets/icons.json` 是唯一需要关心的配置文件：

```json
{
  "version": 1,
  "base_dir": "assets/icons",
  "entries": {
    "player":          { "label": "玩家",     "file": "player.png" },
    "monster.goblin":  { "label": "哥布林",   "file": "monster/goblin.png" },
    "monster":         { "label": "怪物通用", "file": "monster/_default.png" },
    "item.potion":     { "label": "药水通用", "file": "item/potion.png" },
    "stair":           { "label": "下行楼梯", "file": "object/stairs.png" }
  }
}
```

| 字段 | 说明 |
|---|---|
| `version` | 清单格式版本，目前只接受 `1` |
| `base_dir` | 图片根目录，相对项目根；也可以用绝对路径 |
| `entries.<键>.file` | 相对 `base_dir` 的 PNG 路径。**必须是相对路径且以 `.png` 结尾**，否则该条被忽略 |
| `entries.<键>.label` | 中文名，只用于文档与提示，不影响渲染 |

### 三级回退

某个格子要画图标时，按下面的顺序找第一个存在的文件：

| 格子 | 查找顺序 |
|---|---|
| 玩家 | `player` |
| 怪物 | `monster.<种类>` → `monster` |
| 道具 | `item.<道具名>` → `item.<类别>` → `item` |
| 楼梯 / 门 | `stair` / `door` |

所以只画一张 `item/potion.png` 就能覆盖全部药水；想给「符文长剑」单独做图，
就再放一张 `item/sword_rune.png` 即可覆盖。

### 为什么墙和地板不做成图片

墙和地板承担着战争迷雾的三态显示（未探索 / 已探索 / 当前可见），现在只改
一个填充色就能完成；换成图片后每层 1000 个格子都要切换贴图，还要为迷雾再准备
一套压暗版本，收益几乎为零。楼梯、门属于"物件"，所以支持。

### 想要一套空白素材

```bash
python tools/export_icon_slots.py
```

按清单把所有条目渲染成 24×24 占位 PNG（透明底 + 当前字符），之后直接在这些文件上
改画。想恢复纯字符外观，把生成的 PNG 删掉即可。

---

## 设计说明

### 为什么逻辑层不碰 tkinter

`dungeon/` 目录严禁导入任何界面库，这条约定由 `tests/test_architecture.py`
自动扫描源码来保证。收益有三点：

1. 单元测试不需要显示器，64 个用例 0.3 秒跑完；
2. `tools/balance_sim.py` 能在没有界面的环境里跑上百分局验证数值；
3. 将来把界面换成网页或终端，业务代码一行都不用改。

### 为什么要专门做"焦点回收"

Tk 的 `listbox.tcl` 与 `text.tcl` 在鼠标按下时会无条件执行 `focus $w`，
`-takefocus 0` 拦不住（它只影响 Tab 遍历）。焦点一旦停在右侧背包列表或底部日志上，
主窗口的 `<Key>` 绑定虽然仍会触发，却会被"文本控件不处理按键"的守卫挡掉——
表现为方向键不动、`I` 打不开背包、`>` 下不了楼。

因此本项目做了三件事：

1. 守卫从"控件黑名单"细化成"控件 + 按键白名单"——列表只独占它真正会消费的
   方向键、空格等，其余按键照常交给游戏；
2. 在使用道具后、点击地图后、关闭弹窗后、按 `Esc` 时主动把焦点还给地图画布；
3. 点击日志区后用 `after_idle` 延迟一拍回收焦点，不打断日志自身的定位。

`ui/dialogs.py` 的 `<Destroy>` 钩子还必须用 `event.widget is win` 过滤，
因为 Tk 会为每个子控件各触发一次销毁事件；同时要吞掉 `TclError`，
否则主窗口退出时控制台会冒 traceback。

### 为什么存档用 JSON 而不是 pickle

- **安全**：`pickle.load` 会执行任意代码，存档一旦被替换就是后门；
- **可移植**：pickle 绑定"模块路径 + 类名"，重命名类老存档就报废；
- **可读**：JSON 能直接打开看、手工改，也能贴进实验报告。

### 读档后为什么行为完全一致

存档同时保存 `seed`（可复现整局）和 `getstate()` 的 625 个整数状态快照——
后者才能回到"当前这一刻"。读档后怪物 AI 的每一次随机判定都与存档时一致，
这条性质由 `test_rng_state_reproducible` 兜底。
