"""策略战斗的单元测试：攻击形状、蓄力规则、敌人预告。

这些用例全部不依赖 tkinter：战斗内核都是纯函数或纯状态机，
用一块手写的小地图就能把"打哪儿""什么时候落下"钉死。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon.dungeon import Dungeon
from dungeon.game_state import GameState
from dungeon.item import make_item
from dungeon.monster import MONSTER_BY_KIND, MONSTER_TABLE, Monster
from dungeon.patterns import chebyshev, facing, pattern_tiles
from dungeon.player import Player
from dungeon.rng import Rng

# 9×9 的空房间，四周一圈墙
ROOM = ["#########"] + ["#.......#"] * 7 + ["#########"]


def empty_state(px: int = 2, py: int = 4) -> GameState:
    dungeon = Dungeon.from_rows(ROOM, None, set())
    player = Player.create_new()
    player.move_to(px, py)
    state = GameState(
        rng=Rng(11), player=player, dungeon=dungeon, monsters=[], items_on_floor={}
    )
    dungeon.compute_fov(px, py)
    return state


class TestPatterns(unittest.TestCase):
    """攻击形状是纯几何，可以逐格断言。"""

    def test_facing_is_eight_directional(self) -> None:
        self.assertEqual(facing((5, 5), (8, 5)), (1, 0))
        self.assertEqual(facing((5, 5), (5, 2)), (0, -1))
        self.assertEqual(facing((5, 5), (7, 3)), (1, -1))
        self.assertEqual(facing((5, 5), (5, 5)), (0, 0))

    def test_melee_hits_only_front_tile(self) -> None:
        tiles = pattern_tiles((4, 4), (5, 4), "melee", reach=1)
        self.assertEqual(tiles, {(5, 4)})

    def test_line_extends_and_stops_at_wall(self) -> None:
        # 无遮挡：一直捅到第 3 格
        self.assertEqual(
            pattern_tiles((4, 4), (4, 5), "line", reach=3),
            {(4, 5), (4, 6), (4, 7)},
        )
        # 第 6 行是墙：只到第 5 格
        blocked = lambda x, y: y == 6  # noqa: E731
        self.assertEqual(
            pattern_tiles((4, 4), (4, 5), "line", reach=3, blocked=blocked),
            {(4, 5)},
        )

    def test_arc_covers_front_and_both_wings(self) -> None:
        tiles = pattern_tiles((4, 4), (4, 5), "arc", reach=2)
        self.assertEqual(tiles, {(4, 5), (3, 5), (5, 5), (4, 6)})

    def test_ranged_is_single_tile_with_range_check(self) -> None:
        self.assertEqual(pattern_tiles((2, 4), (5, 4), "ranged", reach=4), {(5, 4)})
        # 超出射程
        self.assertEqual(pattern_tiles((2, 4), (7, 4), "ranged", reach=4), frozenset())
        # 太近
        self.assertEqual(
            pattern_tiles((2, 4), (3, 4), "ranged", reach=4, min_reach=2), frozenset()
        )

    def test_target_on_self_has_no_area(self) -> None:
        self.assertEqual(pattern_tiles((4, 4), (4, 4), "melee", reach=1), frozenset())

    def test_unknown_pattern_rejected(self) -> None:
        with self.assertRaises(ValueError):
            pattern_tiles((0, 0), (1, 0), "circle", reach=1)

    def test_chebyshev_counts_diagonal_as_one(self) -> None:
        self.assertEqual(chebyshev((0, 0), (1, 1)), 1)
        self.assertEqual(chebyshev((0, 0), (3, 1)), 3)


class TestEnemyDesign(unittest.TestCase):
    """兵种设计与"伤害越高蓄力越长"的全局约束。"""

    def test_required_enemy_types_exist(self) -> None:
        for kind, pattern in (
            ("spearman", "line"),
            ("archer", "ranged"),
            ("swordsman", "arc"),
        ):
            self.assertIn(kind, MONSTER_BY_KIND, f"缺少兵种 {kind}")
            self.assertEqual(MONSTER_BY_KIND[kind].pattern, pattern)

    def test_spear_is_long_and_narrow(self) -> None:
        proto = MONSTER_BY_KIND["spearman"]
        self.assertEqual(proto.pattern, "line")
        self.assertGreaterEqual(proto.reach, 3)

    def test_three_named_enemies_scale_damage_and_charge(self) -> None:
        """点名要求的三种敌人：伤害严格递增，蓄力也严格递增。"""
        archer = MONSTER_BY_KIND["archer"]
        spearman = MONSTER_BY_KIND["spearman"]
        swordsman = MONSTER_BY_KIND["swordsman"]
        self.assertLess(archer.atk, spearman.atk)
        self.assertLess(spearman.atk, swordsman.atk)
        self.assertLess(archer.charge, spearman.charge)
        self.assertLess(spearman.charge, swordsman.charge)

    def test_charge_is_non_decreasing_with_damage(self) -> None:
        """全表约束：攻击力更高的一方，蓄力回合不能反而更短。"""
        ordered = sorted(MONSTER_TABLE, key=lambda p: p.atk)
        for weaker, stronger in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(
                stronger.charge,
                weaker.charge,
                f"{stronger.name}(atk={stronger.atk}) 蓄力 {stronger.charge} "
                f"短于 {weaker.name}(atk={weaker.atk}) 的 {weaker.charge}",
            )


class TestPlayerAttack(unittest.TestCase):
    """玩家攻击：必须有武器、要瞄准、重武器要蓄力。"""

    def test_cannot_attack_without_weapon(self) -> None:
        state = empty_state()
        state.player.equipment["weapon"] = None
        ok, reason = state.can_attack_at(3, 4, "weapon")
        self.assertFalse(ok)
        self.assertIn("没有装备", reason)

    def test_cannot_attack_unexplored_tile(self) -> None:
        state = empty_state(px=2, py=2)
        outside = (7, 7)
        state.dungeon.visible.discard(outside)
        state.dungeon.explored.discard(outside)
        ok, reason = state.can_attack_at(*outside, "weapon")
        self.assertFalse(ok)
        self.assertIn("探索", reason)

    def test_light_weapon_resolves_immediately(self) -> None:
        state = empty_state()
        goblin = Monster(MONSTER_BY_KIND["goblin"], 3, 4, 1)
        state.monsters = [goblin]
        before = goblin.hp
        self.assertTrue(state.attack_at(3, 4, "weapon"))
        self.assertLess(goblin.hp, before)
        self.assertEqual(state.turn, 1)

    def test_heavy_weapon_charges_then_lands(self) -> None:
        state = empty_state()
        state.player.equipment["weapon"] = make_item("greatsword")
        goblin = Monster(MONSTER_BY_KIND["goblin"], 3, 4, 1)
        state.monsters = [goblin]
        before = goblin.hp

        self.assertTrue(state.attack_at(3, 4, "weapon"))
        self.assertEqual(state.player.charge_left, 1, "重武器应当先进入蓄力")
        self.assertEqual(goblin.hp, before, "蓄力回合不应该立刻造成伤害")

        # 下一回合：蓄力落下
        state.wait()
        self.assertEqual(state.player.charge_left, 0)
        self.assertLess(goblin.hp, before, "蓄力完成后应当造成伤害")

    def test_moving_cancels_long_charge(self) -> None:
        """蓄力超过 1 回合时，移动会打断它（现有武器最短是 1，这里手工加长来验证分支）。"""
        state = empty_state()
        heavy = make_item("greatsword")
        heavy.charge = 3
        state.player.equipment["weapon"] = heavy
        state.monsters = [Monster(MONSTER_BY_KIND["goblin"], 3, 4, 1)]

        state.attack_at(3, 4, "weapon")
        self.assertEqual(state.player.charge_left, 3)
        state.try_move(0, -1)
        self.assertEqual(state.player.charge_left, 0)
        self.assertEqual(state.player.charge_tiles, set())

    def test_ranged_weapon_respects_min_range(self) -> None:
        state = empty_state()
        state.player.equipment["ranged"] = make_item("bow_short")
        ok, reason = state.can_attack_at(3, 4, "ranged")   # 距离 1，太近
        self.assertFalse(ok)
        self.assertIn("太近", reason)


class TestEnemyTelegraph(unittest.TestCase):
    """敌人蓄力预告：区域锁定、可躲避、到点结算。"""

    def _state_with_spearman(self) -> tuple[GameState, Monster]:
        state = empty_state()
        spearman = Monster(MONSTER_BY_KIND["spearman"], 4, 4, 1)
        state.monsters = [spearman]
        return state, spearman

    def test_enemy_starts_charging_when_player_in_pattern(self) -> None:
        state, spearman = self._state_with_spearman()
        state.wait()
        self.assertEqual(spearman.charge_left, spearman.charge_turns)
        self.assertIn(state.player.pos, spearman.telegraph)

    def test_telegraph_area_is_locked(self) -> None:
        state, spearman = self._state_with_spearman()
        state.wait()
        locked = set(spearman.telegraph)
        state.try_move(0, -1)          # 玩家横向挪开
        self.assertEqual(spearman.telegraph, locked, "锁定后不能跟着玩家改")

    def test_standing_still_takes_damage(self) -> None:
        state, _ = self._state_with_spearman()
        state.wait()
        for _ in range(spearman_turns(state)):
            state.wait()
            if state.player.hp < state.player.max_hp:
                break
        self.assertLess(state.player.hp, state.player.max_hp)

    def test_dodging_avoids_damage(self) -> None:
        state, _ = self._state_with_spearman()
        state.wait()
        state.try_move(0, -1)          # 脱离直线
        hp_before = state.player.hp
        for _ in range(6):
            state.wait()
            if state.player.hp < hp_before:
                break
        self.assertEqual(state.player.hp, hp_before, "已经躲开就不该再挨这一下")


def spearman_turns(state: GameState) -> int:
    """理论上要等几个回合才会挨打：蓄力回合数 + 1 的余量。"""
    if not state.monsters:
        return 2
    return state.monsters[0].charge_turns + 2


class TestSaveCompatibility(unittest.TestCase):
    """数据结构兼容性：旧思路的字段不能因为改战斗而丢失。"""

    def test_player_roundtrip_keeps_equipment_slots(self) -> None:
        player = Player.create_new()
        player.equipment["ranged"] = make_item("bow_short")
        restored = Player.from_dict(player.to_dict())
        self.assertEqual(restored.equipment["weapon"].key, player.equipment["weapon"].key)
        self.assertEqual(restored.equipment["ranged"].key, "bow_short")
        self.assertIsNone(restored.equipment["armor"])

    def test_monster_roundtrip_keeps_charge(self) -> None:
        monster = Monster(MONSTER_BY_KIND["swordsman"], 3, 3, 5)
        monster.begin_charge(frozenset({(3, 4)}))
        restored = Monster.from_dict(monster.to_dict())
        self.assertEqual(restored.charge_left, monster.charge_left)
        self.assertEqual(restored.telegraph, {(3, 4)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
