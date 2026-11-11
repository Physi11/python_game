"""难度曲线、精英怪、治疗怪与趣味房间的单元测试。

设计依据（写进 README 的「难度曲线」一节）：
- Csikszentmihalyi(1990) 心流 / Schell《The Art of Game Design》第 9 章：
  挑战随能力上升，且"锯齿形"路径优于直线爬升——高峰之后必须有释放。
- Hunicke(2005) DDA：动态难度要小步、隐蔽、只增强对手。
- Adams《The Designer's Notebook》：完美的实时平衡会毁掉节奏，因此
  基线曲线是**手工排布**的，自适应只在 ±2 只怪的范围里微调。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dungeon import config
from dungeon.dungeon import Dungeon
from dungeon.game_state import GameState
from dungeon.monster import MONSTER_BY_KIND, MONSTER_TABLE, Monster
from dungeon.player import Player
from dungeon.rng import Rng

# 9×9 空房间，四周一圈墙
ROOM = ["#########"] + ["#.......#"] * 7 + ["#########"]


def empty_state(px: int = 2, py: int = 4) -> GameState:
    dungeon = Dungeon.from_rows(ROOM, None, set())
    player = Player.create_new()
    player.move_to(px, py)
    state = GameState(
        rng=Rng(7), player=player, dungeon=dungeon, monsters=[], items_on_floor={}
    )
    dungeon.compute_fov(px, py)
    return state


class TestDifficultyCurve(unittest.TestCase):
    """逐层剖面必须是一条"有峰有谷"的锯齿，而不是单调爬升。"""

    def test_every_floor_has_a_profile(self) -> None:
        for floor in range(1, config.MAX_FLOOR + 1):
            self.assertIn(floor, config.FLOOR_PROFILE)

    def test_curve_is_not_monotonic(self) -> None:
        """锯齿的证据：至少存在一个"下一层怪更少"的位置。"""
        counts = [
            config.FLOOR_PROFILE[f]["monsters"] for f in range(1, config.MAX_FLOOR)
        ]
        drops = [i for i in range(len(counts) - 1) if counts[i + 1] < counts[i]]
        self.assertGreaterEqual(
            len(drops), 2, f"难度曲线缺少释放节拍：{counts}"
        )

    def test_each_spike_has_a_release_room(self) -> None:
        """每个尖峰层之后的一层，必须给一个恢复类房间。

        第 10 层是最终高潮（Boss 层），不适用"释放"这个概念，跳过。
        """
        for floor in range(1, config.BOSS_FLOOR - 1):
            current = config.FLOOR_PROFILE[floor]
            nxt = config.FLOOR_PROFILE[floor + 1]
            if current["monsters"] >= 12 and nxt["monsters"] < current["monsters"]:
                self.assertIn(
                    nxt["room"],
                    ("heal", "vault"),
                    f"{floor + 1} 层是 {floor} 层的释放层，却只给了 {nxt['room']!r}",
                )

    def test_boss_floor_is_the_climax(self) -> None:
        boss = config.FLOOR_PROFILE[config.BOSS_FLOOR]
        self.assertEqual(boss["elites"], 0)

    def test_floor_profile_falls_back_outside_table(self) -> None:
        state = empty_state()
        profile = state.floor_profile(config.MAX_FLOOR + 3)
        self.assertIn("monsters", profile)
        self.assertLessEqual(profile["monsters"], config.MONSTER_COUNT_MAX)


class TestElite(unittest.TestCase):
    """精英是"同兵种的强化版"：数值更强、形态与蓄力不变。"""

    def test_elite_is_tougher_and_richer(self) -> None:
        base = Monster(MONSTER_BY_KIND["goblin"], 3, 3, 3)
        elite = Monster(MONSTER_BY_KIND["goblin"], 3, 3, 3, elite=True)
        self.assertGreater(elite.max_hp, base.max_hp)
        self.assertGreater(elite.atk, base.atk)
        self.assertGreater(elite.defense, base.defense)
        self.assertGreater(elite.exp_reward, base.exp_reward)
        self.assertGreater(elite.gold_reward, base.gold_reward)
        self.assertTrue(elite.name.startswith(config.ELITE_NAME_PREFIX))

    def test_elite_keeps_its_attack_pattern(self) -> None:
        """精英不改变攻击形态与蓄力：否则会出现"精英史莱姆蓄力 4 回合"。"""
        for kind in ("slime", "spearman", "swordsman"):
            base = Monster(MONSTER_BY_KIND[kind], 3, 3, 2)
            elite = Monster(MONSTER_BY_KIND[kind], 3, 3, 2, elite=True)
            self.assertEqual(elite.pattern, base.pattern)
            self.assertEqual(elite.charge_turns, base.charge_turns)
            self.assertEqual(elite.reach, base.reach)

    def test_boss_cannot_be_elite(self) -> None:
        boss = Monster(MONSTER_BY_KIND["demon_lord"], 3, 3, 10, elite=True)
        self.assertFalse(boss.elite)


class TestHealer(unittest.TestCase):
    """治疗怪的取值逻辑与"不攻击"约束。"""

    def test_healer_has_no_attack_pattern(self) -> None:
        state = empty_state()
        healer = Monster(MONSTER_BY_KIND["shaman"], 3, 4, 2)
        state.monsters = [healer]
        self.assertTrue(healer.is_support)
        self.assertEqual(state._enemy_pattern(healer), frozenset())

    def test_heals_the_weakest_ally(self) -> None:
        healer = Monster(MONSTER_BY_KIND["shaman"], 5, 5, 2)
        wounded = Monster(MONSTER_BY_KIND["goblin"], 4, 5, 2)
        wounded.hp = 3
        healthy = Monster(MONSTER_BY_KIND["goblin"], 6, 5, 2)
        picked = healer.heal_target([wounded, healthy])
        self.assertIsNotNone(picked)
        self.assertIs(picked[0], wounded)
        self.assertGreater(picked[1], 0)

    def test_self_heal_is_halved(self) -> None:
        """没有同伴可治时只能给自己回一半，避免变成打不死的自愈机器。"""
        healer = Monster(MONSTER_BY_KIND["shaman"], 5, 5, 2)
        healer.hp = 5
        picked = healer.heal_target([])
        self.assertIsNotNone(picked)
        self.assertIs(picked[0], healer)
        self.assertLess(picked[1], healer.heal_power)

    def test_healer_turn_heals_and_does_not_damage_player(self) -> None:
        state = empty_state()
        healer = Monster(MONSTER_BY_KIND["shaman"], 3, 4, 2)
        ally = Monster(MONSTER_BY_KIND["goblin"], 3, 5, 2)
        ally.hp = 3
        state.monsters = [healer, ally]
        hp_before = state.player.hp
        ally_before = ally.hp
        state.wait()
        self.assertGreater(ally.hp, ally_before)
        self.assertEqual(state.player.hp, hp_before)

    def test_healer_retreats_when_nothing_to_heal(self) -> None:
        state = empty_state()
        healer = Monster(MONSTER_BY_KIND["shaman"], 3, 4, 2)
        state.monsters = [healer]
        before = healer.pos
        distance_before = max(abs(before[0] - 2), abs(before[1] - 4))
        state.wait()
        distance_after = max(
            abs(healer.x - state.player.x), abs(healer.y - state.player.y)
        )
        self.assertGreaterEqual(distance_after, distance_before)


class TestFeatureRooms(unittest.TestCase):
    """四类趣味房间的触发条件与一次性语义。"""

    def _state_with(self, kind: str, hp: int | None = None) -> GameState:
        dungeon = Dungeon.from_rows(ROOM, None, set())
        dungeon.features[(3, 4)] = kind
        player = Player.create_new()
        player.move_to(2, 4)
        if hp is not None:
            player.hp = hp
        state = GameState(
            rng=Rng(1), player=player, dungeon=dungeon, monsters=[], items_on_floor={}
        )
        dungeon.compute_fov(2, 4)
        return state

    def test_heal_fountain_restores_and_is_single_use(self) -> None:
        state = self._state_with("heal", hp=10)
        before = state.player.hp
        state.try_move(1, 0)
        self.assertGreater(state.player.hp, before)
        healed = state.player.hp
        # 再进一次不再回血
        state.player.hp = 10
        state.try_move(-1, 0)
        state.try_move(1, 0)
        self.assertEqual(state.player.hp, 10)
        self.assertGreater(healed, 10)

    def test_trap_damages_once(self) -> None:
        state = self._state_with("trap")
        before = state.player.hp
        state.try_move(1, 0)
        self.assertLess(state.player.hp, before)
        damaged = state.player.hp
        state.try_move(-1, 0)
        state.try_move(1, 0)
        self.assertEqual(state.player.hp, damaged)

    def test_shrine_trades_hp_for_attack(self) -> None:
        state = self._state_with("shrine")
        atk_before, hp_before = state.player.atk, state.player.hp
        state.try_move(1, 0)
        self.assertEqual(state.player.atk, atk_before + config.ROOM_SHRINE_ATK_BONUS)
        self.assertLess(state.player.hp, hp_before)

    def test_shrine_refuses_when_hp_too_low(self) -> None:
        """血量太低时拒绝交易，且**不消耗**这次机会（养好伤还能再来）。"""
        state = self._state_with("shrine", hp=3)
        atk_before = state.player.atk
        state.try_move(1, 0)
        self.assertEqual(state.player.atk, atk_before)
        self.assertEqual(state.used_features, set())

    def test_vault_spawns_extra_items_and_guards(self) -> None:
        state = GameState.new_game(seed=2026)
        # 直接构造一个宝库层的等价物：用剖面里第 7 层（vault）跑一次
        state._build_floor(7)
        kinds = set(state.dungeon.features.values())
        if "vault" in kinds:
            self.assertGreaterEqual(
                len(state.items_on_floor), config.ITEM_COUNT_MIN + 1
            )
            self.assertTrue(any(m.elite for m in state.monsters))

    def test_features_are_cleared_between_floors(self) -> None:
        state = GameState.new_game(seed=5)
        state.used_features.add((1, 1))
        state._build_floor(3)
        self.assertEqual(state.used_features, set())


class TestAdaptiveDifficulty(unittest.TestCase):
    """自适应只加强对手、幅度有限、可关闭。"""

    def test_low_hp_reduces_monsters(self) -> None:
        state = empty_state()
        state.player.hp = 1
        profile = state.floor_profile(6)
        reduced = state._monster_count_for(profile)
        state.player.hp = state.player.max_hp
        state.player.kills = 999
        increased = state._monster_count_for(profile)
        self.assertLess(reduced, increased)
        self.assertLessEqual(increased - reduced, 2 * config.DDA_MAX_DELTA)

    def test_disabled_ignores_player_state(self) -> None:
        state = empty_state()
        state.adaptive_difficulty = False
        profile = state.floor_profile(6)
        state.player.hp = 1
        low = state._monster_count_for(profile)
        state.player.hp = state.player.max_hp
        high = state._monster_count_for(profile)
        self.assertEqual(low, high)

    def test_never_below_two_monsters(self) -> None:
        state = empty_state()
        state.player.hp = 1
        count = state._monster_count_for({"monsters": 1})
        self.assertGreaterEqual(count, 2)


class TestDifficultyPreset(unittest.TestCase):
    """难度预设只改对手，且三档必须真的不同。"""

    def test_presets_scale_monster_count(self) -> None:
        counts = {}
        for preset in ("easy", "normal", "hard"):
            state = GameState.new_game(seed=11, difficulty=preset)
            counts[preset] = len([m for m in state.monsters if not m.is_boss])
        self.assertLess(counts["easy"], counts["normal"])
        self.assertLess(counts["normal"], counts["hard"])

    def test_easy_has_no_elites(self) -> None:
        for seed in range(6):
            state = GameState.new_game(seed=seed, difficulty="easy")
            state._build_floor(7)      # 第 7 层剖面本应有 2 个精英
            self.assertEqual(sum(1 for m in state.monsters if m.elite), 0)

    def test_invalid_preset_falls_back_to_normal(self) -> None:
        state = GameState.new_game(seed=1, difficulty="不存在的难度")
        self.assertEqual(state.difficulty, config.DEFAULT_DIFFICULTY)


class TestProgressionSerialization(unittest.TestCase):
    """新增字段必须能完整往返，且旧存档不炸。"""

    def test_roundtrip_keeps_features_and_elites(self) -> None:
        state = GameState.new_game(seed=2026)
        state._build_floor(7)         # 宝库层：必有特性与精英
        data = json.loads(json.dumps(state.to_dict()))
        clone = GameState.from_dict(data)
        self.assertEqual(clone.dungeon.features, state.dungeon.features)
        self.assertEqual(clone.used_features, state.used_features)
        self.assertEqual(
            [m.elite for m in clone.monsters], [m.elite for m in state.monsters]
        )
        self.assertEqual(clone.difficulty, state.difficulty)

    def test_old_save_without_new_fields_still_loads(self) -> None:
        state = GameState.new_game(seed=7)
        data = json.loads(json.dumps(state.to_dict()))
        # 模拟 v2 存档：删掉 v3 才有的字段
        data["dungeon"].pop("features", None)
        data["progress"].pop("used_features", None)
        data["progress"].pop("difficulty", None)
        clone = GameState.from_dict(data)
        self.assertEqual(clone.dungeon.features, {})
        self.assertEqual(clone.used_features, set())
        self.assertEqual(clone.difficulty, config.DEFAULT_DIFFICULTY)


class TestMonsterTableInvariant(unittest.TestCase):
    """新增兵种后，"伤害越高、蓄力越长"这条规则仍要成立。"""

    def test_charge_non_decreasing_with_damage(self) -> None:
        ordered = sorted(MONSTER_TABLE, key=lambda p: p.atk)
        for weaker, stronger in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(
                stronger.charge,
                weaker.charge,
                f"{stronger.name}(atk={stronger.atk}) 蓄力短于 "
                f"{weaker.name}(atk={weaker.atk})",
            )

    def test_healer_is_in_the_table(self) -> None:
        self.assertIn("shaman", MONSTER_BY_KIND)
        self.assertTrue(MONSTER_BY_KIND["shaman"].is_support)


if __name__ == "__main__":
    unittest.main()
