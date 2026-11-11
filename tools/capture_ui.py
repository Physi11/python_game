"""自动截图工具。

用途：在没有人工操作的情况下，自动驱动界面跑一段流程并把关键界面截成
PNG，供实验报告「实验结果与界面展示」一章直接插图。

实现要点：tkinter 必须在主线程里跑，所以这里不用 ``mainloop()``，
而是反复调用 ``update()`` 手动推进事件循环；截图用 Pillow 的 ``ImageGrab``
抓取窗口在屏幕上的矩形区域。

用法::

    python tools/capture_ui.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from dungeon.game_state import GameState, GameStatus  # noqa: E402
from ui import dialogs  # noqa: E402
from ui.app import App  # noqa: E402

OUT_DIR = ROOT / "docs" / "screenshots"


def pump(app: App, times: int = 8, delay: float = 0.03) -> None:
    """手动推进 Tk 事件循环若干次，让界面完成布局与重绘。"""
    for _ in range(times):
        app.update_idletasks()
        app.update()
        time.sleep(delay)


def grab(window, path: Path, app: App) -> None:
    """截取窗口在屏幕上的实际区域。"""
    pump(app, times=6, delay=0.05)
    # 窗口刚创建时 winfo_width() 可能是 1（尚未完成映射），等它真正有尺寸再截
    for _ in range(60):
        window.update_idletasks()
        app.update()
        if window.winfo_width() > 16 and window.winfo_height() > 16:
            break
        time.sleep(0.03)
    x = window.winfo_rootx()
    y = window.winfo_rooty()
    w = window.winfo_width()
    h = window.winfo_height()
    if w <= 16 or h <= 16:      # 兜底：宁可不截图，也不要写一张 1×1 的坏图进报告
        print(f"  [跳过] {path.name} 窗口尚未就绪（{w}×{h}）")
        return
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"已保存 {path.relative_to(ROOT)}  ({image.width}×{image.height})")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    app = App(seed=20261025, show_start=False)
    app.attributes("-topmost", True)
    app.lift()
    pump(app)

    # 1) 开局界面
    grab(app, OUT_DIR / "01_开局界面.png", app)

    # 2) 自动探索一段时间，让地图与日志丰富起来
    from tools.balance_sim import AutoPlayer

    bot = AutoPlayer(app.state)
    for _ in range(160):
        if app.state.is_finished:
            break
        try:
            bot.step()
        except Exception:  # pragma: no cover - 截图工具不应因战斗细节中断
            break
    app.state.player.hp = app.state.player.max_hp   # 保证截图时血条好看
    app._refresh()
    pump(app)
    grab(app, OUT_DIR / "02_探索与战斗.png", app)

    # 2.5) 策略战斗：逐敌配色的预告 + 右上角倒计时 + 蓝色瞄准范围
    from dungeon.monster import MONSTER_BY_KIND, Monster
    from dungeon.patterns import pattern_tiles

    st = app.state
    hero = st.player
    # 清掉原有杂兵，只摆演示用的几只：一张图要同时讲清"逐敌配色""精英""治疗怪"
    st.monsters = []
    demo = (
        ("spearman", 2, 0, False),
        ("archer", -2, 1, False),
        ("swordsman", 0, 2, True),      # 精英：金色描边
        ("shaman", -1, 2, False),       # 治疗怪：青绿描边
    )
    for kind, dx, dy, elite in demo:
        spot = (hero.x + dx, hero.y + dy)
        if not st.dungeon.is_walkable(*spot):
            continue
        extra = Monster(MONSTER_BY_KIND[kind], spot[0], spot[1], 1, elite=elite)
        if not extra.is_support:
            extra.begin_charge(
                pattern_tiles(
                    extra.pos, hero.pos, extra.pattern, extra.reach,
                    extra.min_reach,
                    blocked=lambda cx, cy: not st.dungeon.is_walkable(cx, cy),
                )
            )
        st.monsters.append(extra)
    # 顺带摆两个趣味房间，让截图能看出房间字符
    for (fx, fy), kind in (((hero.x + 3, hero.y), "heal"), ((hero.x - 3, hero.y), "vault")):
        if st.dungeon.is_walkable(fx, fy):
            st.dungeon.features[(fx, fy)] = kind
    st.dungeon.compute_fov(hero.x, hero.y)
    app._refresh()
    app._enter_aim("weapon")
    app._update_aim((hero.x + 1, hero.y))
    pump(app)
    grab(app, OUT_DIR / "08_策略战斗.png", app)
    app._exit_aim()

    # 3) 帮助窗口
    help_win = dialogs.show_help(app, app.theme)
    pump(app, times=10, delay=0.05)
    grab(help_win, OUT_DIR / "03_操作说明.png", app)
    help_win.destroy()
    pump(app)

    # 4) 背包窗口
    inv_win = dialogs.show_inventory(app, app.theme, app.state)
    pump(app, times=10, delay=0.05)
    grab(inv_win, OUT_DIR / "04_背包.png", app)
    inv_win.destroy()
    pump(app)

    # 5) 结算窗口（构造一个"阵亡"的展示用局面）
    demo = GameState.new_game(seed=20261025)
    demo.max_floor = 7
    demo.turn = 1863
    demo.player.level = 9
    demo.player.kills = 78
    demo.player.gold = 412
    demo.player.damage_dealt = 2450
    demo.player.damage_taken = 1380
    demo.status = GameStatus.DEAD
    demo.death_cause = "骷髅兵"
    over_win = dialogs.show_game_over(app, app.theme, demo)
    pump(app, times=10, delay=0.05)
    grab(over_win, OUT_DIR / "05_结算.png", app)
    over_win.destroy()
    pump(app)

    # 6) 统计图表
    from dungeon.stats import StatsAnalyzer

    analyzer = StatsAnalyzer(app.save_manager.load_records())
    charts_win = dialogs.show_charts(app, app.theme, analyzer)
    if charts_win is not None:
        pump(app, times=18, delay=0.08)
        grab(charts_win, OUT_DIR / "06_统计图表.png", app)
        charts_win.destroy()
        pump(app)
    else:
        print("暂无战绩数据，跳过图表截图（请先运行 tools/balance_sim.py --record）")

    # 7) 排行榜
    leader_win = dialogs.show_leaderboard(app, app.theme, app.save_manager.load_records())
    pump(app, times=10, delay=0.05)
    grab(leader_win, OUT_DIR / "07_排行榜.png", app)
    leader_win.destroy()
    pump(app)

    # 8) 设置面板
    settings_win = dialogs.show_settings(app, app.theme, app.settings)
    pump(app, times=10, delay=0.05)
    grab(settings_win, OUT_DIR / "09_设置.png", app)
    settings_win.destroy()
    pump(app)

    # 9) 开始界面：最后再盖上去，盖住游戏画面
    app.show_start_screen()
    pump(app, times=12, delay=0.05)
    grab(app, OUT_DIR / "10_开始界面.png", app)
    app.hide_start_screen()

    app.destroy()
    print("截图完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
