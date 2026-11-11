"""批量自动对局模拟器。

用途有两个：

1. **冒烟测试**：不启动界面、不依赖 tkinter，就能验证"地图生成 → 移动 →
   战斗 → 拾取 → 下楼 → 结算"整条链路是否跑通；
2. **数值平衡与图表素材**：跑几百局统计胜率与平均层数，
   并把结果写入 ``data/records.json``，作为实验报告中图表的初始数据。

用法::

    python tools/balance_sim.py --games 50
    python tools/balance_sim.py --games 30 --record
"""

from __future__ import annotations

import argparse
import sys
from collections import deque
from pathlib import Path

# 允许直接以脚本方式运行（把项目根目录加入模块搜索路径）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config  # noqa: E402
from dungeon.game_state import GameState, GameStatus  # noqa: E402
from dungeon.save_manager import SaveManager  # noqa: E402


class AutoPlayer:
    """一个贪心策略的自动玩家，用于数值验证。

    策略优先级：喝药保命 → 攻击相邻敌人 → 追击近处敌人 → 拾取道具 → 走向楼梯。

    为什么只追"近处"敌人（距离 ≤ 3）：早期版本让机器人无条件追击视野内
    所有敌人，会出现"追怪"和"找楼梯"两个目标互相拉扯、在相邻两格之间
    无限震荡的问题。加上距离阈值与震荡检测后行为才稳定。
    """

    CHASE_RANGE = 3          # 只追击这个距离内的敌人
    HISTORY_LEN = 40         # 位置历史长度，用于震荡检测
    EXPLORE_TURN_BUDGET = 350  # 每层最多花多少回合探索，超时就直奔楼梯

    def __init__(self, state: GameState) -> None:
        self.state = state
        self.history: deque[tuple[int, int]] = deque(maxlen=self.HISTORY_LEN)
        self.ignore_monsters_until = 0
        self._floor_start_turn = 0
        self._tracked_floor = 0
        self.last_action = ""

    def step(self) -> bool:
        """执行一个动作，返回 False 表示本局结束。"""
        state = self.state
        if state.is_finished:
            return False

        player = state.player
        self.history.append(player.pos)
        self._sync_floor_budget()

        # 0) 换上更好的武器/护甲（普通玩家都会做，早期版本漏了这一步导致胜率失真）
        upgrade = self._find_upgrade()
        if upgrade is not None:
            self.last_action = "equip"
            return state.use_item(upgrade)

        # 1) 血量低于 35% 且有药水，先喝药
        if player.hp / max(1, player.max_hp) < 0.35:
            for index, item in enumerate(player.inventory):
                if item.kind == "potion":
                    self.last_action = "potion"
                    return state.use_item(index)

        # 2) 站在红框里且**这一回合就要挨打** → 先躲；离落下还早的话照常输出
        if self._in_danger_now():
            escape = self._step_out_of_danger()
            if escape is not None:
                self.last_action = "dodge"
                return state.try_move(*escape)

        # 3) 能打就打：近战优先，够不到再换弓
        target = self._best_target()
        if target is not None:
            slot = self._usable_slot(target)
            if slot is not None:
                self.last_action = f"attack:{slot}:{target.name}"
                return state.attack_at(target.x, target.y, slot)

        visible = state.visible_monsters()

        # 4) 近处敌人 → 逼近。震荡检测触发时本阶段被跳过
        if visible and state.turn >= self.ignore_monsters_until:
            nearby = [m for m in visible if m.distance_to(player) <= self.CHASE_RANGE]
            if nearby:
                target = min(nearby, key=lambda m: m.distance_to(player))
                step = self._step_towards(target.pos)
                if step is not None:
                    if self._is_oscillating():
                        # 原地打转说明目标不可达或两个目标在拉扯，暂时放弃追击
                        self.ignore_monsters_until = state.turn + 60
                    else:
                        return state.try_move(*step)

        # 4) 脚下有物品 → 拾取（正常移动时会自动拾取，这里兜底）
        if state.item_at(*player.pos) is not None:
            return state.interact()

        # 5) 探索未知区域：找最近的"边界格"，走过去把迷雾推开
        if self._floor_spent_turns() < self.EXPLORE_TURN_BUDGET:
            frontier = self._nearest_frontier()
            if frontier is not None:
                step = self._step_towards(frontier)
                if step is not None and not self._is_oscillating():
                    return state.try_move(*step)
                self.ignore_monsters_until = state.turn + 60

        # 6) 已探索完 → 猎杀剩余敌人（BOSS 层必须清场才能通关）
        hunt = self._nearest_monster_pos()
        if hunt is not None:
            step = self._step_towards(hunt)
            if step is not None:
                return state.try_move(*step)

        # 7) 站在楼梯上 → 下楼
        if state.stairs_here:
            return state.descend()

        # 8) 走向楼梯
        if state.dungeon.stairs is not None:
            step = self._step_towards(state.dungeon.stairs)
            if step is not None:
                return state.try_move(*step)

        # 9) 兜底：在已知可走格里随便走一步
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = player.x + dx, player.y + dy
            if state.dungeon.is_walkable(nx, ny) and state.monster_at(nx, ny) is None:
                return state.try_move(dx, dy)
        return state.wait()

    # ------------------------------------------------------------ 内部工具
    def _in_danger_now(self) -> bool:
        """脚下是否压在"下一回合就会落下、而且值得躲"的预警里。

        两段判断，缺一不可：

        1. **时间**：只看 ``charge_left <= 1`` 的敌人。否则会陷入"敌人一起手
           就躲、躲完敌人又起手"的空转。
        2. **代价**：这一击预计会造成多少伤害。如果只是掉个零头，站着挨一下
           把这一刀砍出去更划算——真实玩家也是这么权衡的。只有可能打掉
           25% 以上生命（或直接致命）时才让位。

        只做第一段判断时，场上敌人一多就总有人"下回合出手"，机器人会
        整局都在躲，4000 回合都打不完一层。
        """
        player = self.state.player
        pos = player.pos
        defense = player.total_def()
        incoming = 0
        for m in self.state.monsters:
            if m.alive and pos in m.telegraph and m.charge_left <= 1:
                incoming += max(1, m.atk - defense)
        if incoming <= 0:
            return False
        if incoming >= player.hp:            # 会被打死，必躲
            return True
        return incoming >= player.hp * 0.25  # 重伤才让位，轻伤照打

    def _step_out_of_danger(self) -> tuple[int, int] | None:
        """找一个既不在红框、也不被占用的相邻格。"""
        state = self.state
        pos = state.player.pos
        danger = set()
        for monster in state.monsters:
            if monster.alive:
                danger |= monster.telegraph
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            cell = (pos[0] + dx, pos[1] + dy)
            if not state.dungeon.is_walkable(*cell):
                continue
            if state.monster_at(*cell) is not None or cell in danger:
                continue
            return dx, dy
        return None

    def _best_target(self):
        """挑一个当前就能打到的敌人。

        优先级：治疗怪 > 血少的。治疗怪每回合给同伴回血，放着不管会让
        整场战斗的输出被抵消掉，所以真实玩家也会先点它。
        """
        state = self.state
        reachable = [
            m for m in state.visible_monsters() if self._usable_slot(m) is not None
        ]
        if not reachable:
            return None
        return min(
            reachable,
            key=lambda m: (0 if m.is_support else 1, m.hp, m.distance_to(state.player)),
        )

    def _usable_slot(self, monster) -> str | None:
        """这只敌人能用哪个槽位打到；都打不到返回 None。"""
        state = self.state
        for slot in ("weapon", "ranged"):
            if state.player.equipment.get(slot) is None:
                continue
            ok, _ = state.can_attack_at(monster.x, monster.y, slot)
            if ok:
                return slot
        return None

    def _find_upgrade(self) -> int | None:
        """在背包里找一件比当前更好的装备，返回其下标。

        取装备槽必须走 ``item.equip_slot``：武器的 ``slot`` 是 melee/ranged，
        而装备字典的键是 weapon/ranged，直接拿 slot 当键会永远读到 None，
        于是机器人会一直以为"没装备武器"，反复尝试换装直到回合耗尽。
        """
        player = self.state.player
        for index, item in enumerate(player.inventory):
            if item.kind == "weapon":
                slot = getattr(item, "equip_slot", "weapon")
                current = player.equipment.get(slot)
                if current is None or item.atk_bonus > getattr(current, "atk_bonus", 0):
                    return index
            elif item.kind == "armor":
                current = player.equipment.get("armor")
                if current is None or item.def_bonus > getattr(current, "def_bonus", 0):
                    return index
        return None

    def _sync_floor_budget(self) -> None:
        """切层时重置本层探索预算。"""
        if self.state.floor != self._tracked_floor:
            self._tracked_floor = self.state.floor
            self._floor_start_turn = self.state.turn

    def _floor_spent_turns(self) -> int:
        return self.state.turn - self._floor_start_turn

    def _nearest_frontier(self) -> tuple[int, int] | None:
        """找最近的、尚未进入过视野的可走格。

        这就是自动玩家的"探索欲"：只要还有黑雾没掀开，就先去掀。
        """
        state = self.state
        distances = state.dungeon.bfs_distances(state.player.pos)
        explored = state.dungeon.explored
        candidates = [cell for cell in distances if cell not in explored]
        if not candidates:
            return None
        return min(candidates, key=lambda cell: distances[cell])

    def _nearest_monster_pos(self) -> tuple[int, int] | None:
        """找可达的最近怪物，用于清场。"""
        state = self.state
        if not state.monsters:
            return None
        distances = state.dungeon.bfs_distances(state.player.pos)
        reachable = [m for m in state.monsters if m.alive and m.pos in distances]
        if not reachable:
            return None
        return min(reachable, key=lambda m: distances[m.pos]).pos

    def _is_oscillating(self) -> bool:
        """最近一段时间内在同一位置反复出现，判定为原地打转。"""
        if len(self.history) < self.HISTORY_LEN:
            return False
        current = self.history[-1]
        return sum(1 for pos in self.history if pos == current) >= 10

    def _step_towards(self, target: tuple[int, int]) -> tuple[int, int] | None:
        """用 BFS 求到目标的最短路，返回第一步的方向；不可达返回 None。"""
        state = self.state
        distances = state.dungeon.bfs_distances(target)
        if not distances:
            return None
        origin = state.player.pos
        best: tuple[int, int] | None = None
        best_distance = distances.get(origin, 10**9)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (origin[0] + dx, origin[1] + dy)
            distance = distances.get(neighbor)
            if distance is None:
                continue
            # 目标格允许有怪物（走过去即攻击）
            if state.monster_at(*neighbor) is not None:
                distance -= 1
            if distance < best_distance:
                best_distance = distance
                best = (dx, dy)
        return best


def run_one_game(seed: int, max_steps: int = 4000) -> tuple[GameState, int]:
    """跑完一整局，返回最终状态与消耗的步数。"""
    state = GameState.new_game(seed=seed)
    bot = AutoPlayer(state)
    steps = 0
    while not state.is_finished and steps < max_steps:
        if not bot.step():
            break
        steps += 1
    if not state.is_finished:
        state.status = GameStatus.TIMEOUT
        state.death_cause = "模拟步数超限"
    return state, steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="地下城探险 —— 批量自动对局模拟")
    parser.add_argument("--games", type=int, default=20, help="模拟局数（默认 20）")
    parser.add_argument("--start-seed", type=int, default=1000, help="起始种子")
    parser.add_argument("--record", action="store_true", help="把结果写入 data/records.json")
    args = parser.parse_args(argv)

    results: list[GameState] = []
    for index in range(args.games):
        seed = args.start_seed + index
        state, steps = run_one_game(seed)
        results.append(state)
        print(
            f"[{index + 1:>3}/{args.games}] 种子={seed:<8} "
            f"结果={state.status:<8} 层数={state.max_floor:<2} "
            f"回合={state.turn:<5} 击杀={state.player.kills:<3} "
            f"等级={state.player.level}"
        )

    wins = sum(1 for r in results if r.status == GameStatus.WIN)
    avg_floor = sum(r.max_floor for r in results) / max(1, len(results))
    avg_turns = sum(r.turn for r in results) / max(1, len(results))
    avg_kills = sum(r.player.kills for r in results) / max(1, len(results))
    print("-" * 72)
    print(f"总局数 {len(results)} ｜ 通关 {wins} ｜ 胜率 {wins / max(1, len(results)):.1%}")
    print(f"平均到达层数 {avg_floor:.2f} ｜ 平均回合 {avg_turns:.0f} ｜ 平均击杀 {avg_kills:.1f}")

    if args.record:
        manager = SaveManager(ROOT / config.DATA_DIR_NAME)
        for state in results:
            manager.append_record(state.build_record())
        print(f"已写入 {len(results)} 条记录到 {manager.records_path}")

    # 展示一局的地图，确认渲染与地图生成正常
    sample = results[0]
    print("-" * 72)
    print(f"第 {sample.floor} 层地图预览（探索过的区域用 ',' 表示）")
    print(sample.ascii_view())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
