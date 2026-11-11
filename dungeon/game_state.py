"""游戏状态机模块。

这是整个项目的"大脑"，也是逻辑层与界面层之间**唯一**的契约：

- 界面层只调用 ``try_move / wait / interact / use_item / descend`` 五个意图方法；
- 逻辑层通过 ``events`` 列表单向向界面层推送表现事件（飘字、震动、弹窗）；
- 界面层不判断任何规则，逻辑层也不知道 tkinter 的存在。

这样拆分的好处：``tools/balance_sim.py`` 可以在完全无界面的情况下
批量跑上万局对局，测试也不需要显示器。
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Callable, Iterable

from . import config
from .combat import resolve_attack
from .dungeon import FEATURE_GLYPHS, FEATURE_LABELS, ROOM_FEATURES, Dungeon, Tile
from .item import Item, item_from_dict, make_item, roll_item
from .monster import MONSTER_BY_KIND, Monster, roll_monster
from .patterns import chebyshev, pattern_tiles
from .player import Player
from .rng import Rng


class GameStatus:
    """一局游戏的状态常量。用字符串而非枚举，方便直接写进 JSON。"""

    PLAYING = "playing"
    DEAD = "dead"
    WIN = "win"
    TIMEOUT = "timeout"
    QUIT = "quit"

    FINISHED = (DEAD, WIN, TIMEOUT, QUIT)


# 日志分类，界面层据此上色
LOG_SYSTEM = "system"
LOG_COMBAT = "combat"
LOG_ITEM = "item"
LOG_LEVEL = "level"
LOG_DANGER = "danger"

LogEntry = tuple[str, str]   # (文本, 分类)


class GameState:
    """一局游戏的全部可变状态。"""

    def __init__(
        self,
        rng: Rng,
        player: Player,
        dungeon: Dungeon,
        monsters: list[Monster],
        items_on_floor: dict[tuple[int, int], Item],
        floor: int = 1,
        turn: int = 0,
        status: str = GameStatus.PLAYING,
        death_cause: str = "",
        started_at: str | None = None,
        max_floor: int = 1,
        floor_turns: dict[int, int] | None = None,
        used_features: set[tuple[int, int]] | None = None,
        adaptive_difficulty: bool = True,
        difficulty: str = config.DEFAULT_DIFFICULTY,
    ) -> None:
        self.rng = rng
        self.player = player
        self.dungeon = dungeon
        self.monsters = monsters
        self.items_on_floor = items_on_floor
        self.floor = floor
        self.turn = turn
        self.status = status
        self.death_cause = death_cause
        self.started_at = started_at or datetime.now().isoformat(timespec="seconds")
        self.max_floor = max_floor
        self.floor_turns: dict[int, int] = floor_turns or {str(floor): 0}  # type: ignore[assignment]
        # 已经触发过的趣味房间（一次性），按坐标记，换层时清空
        self.used_features: set[tuple[int, int]] = used_features or set()
        # 是否启用自适应难度（设置项，默认开；关掉后完全按剖面表走）
        self.adaptive_difficulty: bool = adaptive_difficulty
        # 难度预设（easy/normal/hard），只影响对手强度
        self.difficulty: str = (
            difficulty if difficulty in config.DIFFICULTY_PRESETS else config.DEFAULT_DIFFICULTY
        )

        self.log: deque[LogEntry] = deque(maxlen=200)
        self.events: list[dict[str, Any]] = []

    # ================================================================ 构造
    @classmethod
    def new_game(
        cls,
        seed: int | None = None,
        name: str = "冒险者",
        adaptive_difficulty: bool = True,
        difficulty: str = config.DEFAULT_DIFFICULTY,
    ) -> "GameState":
        """开一局新游戏。``seed`` 为 None 时由系统随机生成。"""
        rng = Rng(seed)
        player = Player.create_new(name)
        state = cls(
            rng=rng,
            player=player,
            dungeon=Dungeon(config.MAP_W, config.MAP_H),  # 占位，随即被 _build_floor 覆盖
            monsters=[],
            items_on_floor={},
            started_at=datetime.now().isoformat(timespec="seconds"),
            adaptive_difficulty=adaptive_difficulty,
            difficulty=difficulty,
        )
        state.floor_turns = {"1": 0}
        state._build_floor(1)
        state._log(f"你踏入了地下城第 1 层，种子 {rng.seed}", LOG_SYSTEM)
        state._log("方向键/WASD 移动；右键或 F 瞄准攻击；蓝色是你能打的格子，敌人锁定的区域各有颜色", LOG_SYSTEM)
        return state

    # ---------------------------------------------------------------- 楼层构建
    def _build_floor(self, floor: int) -> None:
        """生成一层地牢并放置玩家、楼梯、怪物与道具。

        难度不是线性递增，而是按 ``config.FLOOR_PROFILE`` 的**锯齿剖面**排布：
        尖峰层（3/7/9）之后紧跟释放层（4/8），释放层配一个恢复房间。
        这样玩家在每一段高压之后都有一段可呼吸的空间，符合 Schell 在
        《The Art of Game Design》里给出的"兴趣曲线 / 张弛"结构。
        """
        self.floor = floor
        self.player.floor = floor
        self.max_floor = max(self.max_floor, floor)
        self.floor_turns.setdefault(str(floor), 0)

        dungeon = Dungeon.generate(self.rng, floor)
        self.dungeon = dungeon

        start = dungeon.rooms[0].center
        self.player.move_to(*start)

        # 第 10 层是 BOSS 层，不设下行楼梯，必须击败 BOSS 才能通关
        if floor < config.MAX_FLOOR:
            dungeon.place_stairs(start)
        else:
            dungeon.stairs = None

        profile = self.floor_profile(floor)

        # 怪物不得出现在出生房间，否则开局就被围殴
        occupied: set[tuple[int, int]] = set()
        for cell in dungeon.rooms[0].inner_cells():
            occupied.add(cell)
        occupied.add(start)
        if dungeon.stairs is not None:
            occupied.add(dungeon.stairs)

        self.monsters = []
        preset = config.DIFFICULTY_PRESETS.get(
            self.difficulty, config.DIFFICULTY_PRESETS[config.DEFAULT_DIFFICULTY]
        )
        count = self._monster_count_for(profile)
        elites_left = round(profile.get("elites", 0) * preset["elite_mult"])
        if floor == config.BOSS_FLOOR:
            # BOSS 层只留少量杂兵，让最终战的主角是深渊领主本身
            count = profile.get("monsters", 6)
            elites_left = 0
        for index in range(count):
            proto = roll_monster(self.rng, floor)
            pos = dungeon.random_floor(self.rng, occupied)
            occupied.add(pos)
            # 治疗怪不做精英：它的价值是"优先击杀目标"，加血量反而更拖
            elite = (
                elites_left > 0
                and not proto.is_support
                and not proto.is_boss
                and proto.min_floor <= floor
            )
            if elite:
                elites_left -= 1
            self.monsters.append(
                Monster(
                    proto, pos[0], pos[1], floor,
                    elite=elite, hp_mult=preset["hp_mult"],
                )
            )

        # BOSS：放在离玩家最远的可走格
        if floor == config.BOSS_FLOOR:
            distances = dungeon.bfs_distances(start)
            far = max(distances.items(), key=lambda kv: kv[1])[0] if distances else start
            self.monsters.append(
                Monster(MONSTER_BY_KIND["demon_lord"], far[0], far[1], floor)
            )
            occupied.add(far)

        # 道具：第一件固定为药水，避免出现"全程无补给"的必死局
        self.items_on_floor = {}
        item_count = self.rng.randint(config.ITEM_COUNT_MIN, config.ITEM_COUNT_MAX)
        for index in range(item_count):
            pos = dungeon.random_floor(self.rng, occupied)
            occupied.add(pos)
            item = make_item("potion_small") if index == 0 else roll_item(self.rng, floor)
            self.items_on_floor[pos] = item

        # 趣味房间放在道具之后：宝库要额外塞道具，陷阱房要在中心放诱饵
        self.used_features = set()
        self._place_feature(profile.get("room", ""), occupied)

        dungeon.compute_fov(self.player.x, self.player.y)

    def floor_profile(self, floor: int) -> dict[str, Any]:
        """取某一层的难度剖面；表外楼层用"最后一档 + 线性递增"兜底。"""
        if floor in config.FLOOR_PROFILE:
            return config.FLOOR_PROFILE[floor]
        # 兜底：超过预设最深层的层数（例如以后扩展地图）继续小幅加压
        last = config.FLOOR_PROFILE[max(config.FLOOR_PROFILE)]
        step = max(0, floor - max(config.FLOOR_PROFILE))
        return {
            "monsters": min(
                config.MONSTER_COUNT_MAX, last["monsters"] + 2 * step
            ),
            "elites": min(3, last.get("elites", 0) + (1 if step % 2 else 0)),
            "room": "",
            "note": "预设表外的自动加压",
        }

    def _monster_count_for(self, profile: dict[str, Any]) -> int:
        """按剖面取怪物数量，并叠加可选的自适应难度。

        自适应部分刻意做得**很小且只增不减玩家实力**（Hunicke 2005 的核心
        约束：DDA 必须隐蔽、不能削弱玩家、不能破坏已建立的节奏）。这里最多
        只调整 ±2 只小怪，且不改变尖峰/释放的层间结构，所以玩家感知不到
        "游戏在偷偷放水"，但连续三层的极端体验会被拉回心流通道内。
        """
        count = int(profile.get("monsters", config.MONSTER_COUNT_BASE))
        preset = config.DIFFICULTY_PRESETS.get(
            self.difficulty, config.DIFFICULTY_PRESETS[config.DEFAULT_DIFFICULTY]
        )
        count = max(2, round(count * preset["monster_mult"]))
        if not self.adaptive_difficulty or self.floor == config.BOSS_FLOOR:
            return min(config.MONSTER_COUNT_MAX, count)
        hp_ratio = self.player.hp / max(1, self.player.max_hp)
        if hp_ratio >= config.DDA_HIGH_HP_RATIO and self.player.kills >= self.floor * 3:
            # 打得太顺：多放两只，但不超过上限
            count += min(config.DDA_MAX_DELTA, 2)
        elif hp_ratio <= config.DDA_LOW_HP_RATIO:
            # 快被打崩：少放两只，给一口气
            count -= min(config.DDA_MAX_DELTA, 2)
        return max(2, min(config.MONSTER_COUNT_MAX, count))

    def _place_feature(self, kind: str, occupied: set[tuple[int, int]]) -> None:
        """在非出生房间放置一个趣味玩法，并按类型补内容。"""
        if not kind:
            return
        spot = self.dungeon.assign_feature(kind, self.rng, occupied)
        if spot is None:
            return
        occupied.add(spot)
        label = FEATURE_LABELS.get(kind, kind)

        if kind == "vault":
            # 宝库：房间中心周围塞满道具，外加两名精英看守
            room = next((r for r in self.dungeon.rooms if r.center == spot), None)
            cells = list(room.inner_cells()) if room else [spot]
            self.rng.shuffle(cells)
            for cell in cells[: config.ROOM_VAULT_ITEMS]:
                if cell in occupied or cell in self.items_on_floor:
                    continue
                self.items_on_floor[cell] = roll_item(self.rng, self.floor + 1)
                occupied.add(cell)
            guards = 0
            # 轻松档承诺"没有精英"，宝库守卫也要遵守；其他档位守卫固定为精英
            guard_elite = config.DIFFICULTY_PRESETS.get(
                self.difficulty, config.DIFFICULTY_PRESETS[config.DEFAULT_DIFFICULTY]
            )["elite_mult"] > 0
            for cell in cells:
                if guards >= 2:
                    break
                if cell in occupied:
                    continue
                proto = roll_monster(self.rng, self.floor)
                if proto.is_support or proto.is_boss:
                    continue
                self.monsters.append(
                    Monster(
                        proto, cell[0], cell[1], self.floor, elite=guard_elite
                    )
                )
                occupied.add(cell)
                guards += 1
            self._log(f"你察觉到一间{label}：满地财宝，但有人守着", LOG_SYSTEM)
        elif kind == "trap":
            # 陷阱房：中心放一件好道具当诱饵，踩上去会触发机关
            if spot not in self.items_on_floor:
                self.items_on_floor[spot] = roll_item(self.rng, self.floor + 1)
            self._log(f"前方的{label}透着一股不安的气息", LOG_SYSTEM)
        else:
            self._log(f"这一层有一处{label}", LOG_SYSTEM)

    # ================================================================ 查询
    def monster_at(self, x: int, y: int) -> Monster | None:
        for monster in self.monsters:
            if monster.alive and monster.x == x and monster.y == y:
                return monster
        return None

    def item_at(self, x: int, y: int) -> Item | None:
        return self.items_on_floor.get((x, y))

    def visible_monsters(self) -> list[Monster]:
        """当前视野内的怪物。"""
        return [m for m in self.monsters if m.alive and (m.x, m.y) in self.dungeon.visible]

    @property
    def stairs_here(self) -> bool:
        return self.dungeon.stairs == self.player.pos

    @property
    def is_finished(self) -> bool:
        return self.status in GameStatus.FINISHED

    # ================================================================ 玩家意图
    def try_move(self, dx: int, dy: int) -> bool:
        """向 (dx, dy) 走一步。**移动就是这一回合的唯一行动。**

        新战斗规则下"撞向怪物即攻击"已被取消：撞到敌人只会提示而不会攻击，
        攻击必须显式选择目标区域（见 :meth:`attack_at`）。
        """
        if self.is_finished:
            return False
        if (dx, dy) not in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            self._log("无效的移动方向", LOG_SYSTEM)
            return False

        nx, ny = self.player.x + dx, self.player.y + dy
        if self.monster_at(nx, ny) is not None:
            self._log("那里站着敌人，攻击请用右键瞄准或按 F", LOG_SYSTEM)
            return False

        if not self.dungeon.is_walkable(nx, ny):
            self._log("前面是石墙，无法通行", LOG_SYSTEM)
            self._emit("bump", x=nx, y=ny)
            return False

        def act() -> bool:
            if self.player.charge_left > 0:
                # 移动会打断重武器的蓄力，这是一个真实的取舍
                self.player.charge_left = 0
                self.player.charge_tiles = set()
                self._log("你挪动脚步，蓄力被打断了", LOG_SYSTEM)
            self.player.move_to(nx, ny)
            self.player.steps += 1
            # 先触发房间机制，再拾取：陷阱房是"先挨一下，再拿到诱饵"
            self._trigger_feature()
            self._auto_pickup()
            return True

        return self._take_turn(act)

    # ---------------------------------------------------------------- 趣味房间
    def _trigger_feature(self) -> None:
        """玩家踏入某格时结算该格的趣味房间效果（每处只触发一次）。

        这些房间是难度曲线里的"节拍器"：治疗泉与宝库是**释放**，
        陷阱房与祭坛是**主动选择的尖峰**——玩家可以绕开，也可以为了收益
        承担风险，这正是 Schell 所说的"三角形"风险回报结构。
        """
        pos = self.player.pos
        kind = self.dungeon.feature_at(*pos)
        if not kind or pos in self.used_features:
            return
        if kind not in ROOM_FEATURES:
            return
        label = FEATURE_LABELS.get(kind, kind)

        if kind == "heal":
            amount = max(1, round(self.player.max_hp * config.ROOM_HEAL_RATIO))
            healed = self.player.heal(amount)
            self.used_features.add(pos)
            self._log(f"{label}泛起微光，你回复了 {healed} 点生命", LOG_LEVEL)
            self._emit("heal", x=pos[0], y=pos[1], text=f"+{healed}")
        elif kind == "trap":
            damage = max(1, round(self.player.hp * config.ROOM_TRAP_RATIO))
            actual = self.player.take_damage(damage)
            self.player.damage_taken += actual
            self.used_features.add(pos)
            self._log(f"{label}的机关弹出，你受到 {actual} 点伤害", LOG_DANGER)
            self._emit("damage", x=pos[0], y=pos[1], text=f"-{actual}", tone="hurt")
            if not self.player.alive:
                self.status = GameStatus.DEAD
                self.death_cause = f"{label}的机关"
        elif kind == "shrine":
            ratio = self.player.hp / max(1, self.player.max_hp)
            if ratio < config.ROOM_SHRINE_MIN_HP_RATIO:
                # 拒绝交易时不消耗这次机会：先养伤，回头还能再来
                self._log(
                    f"{label}拒绝了你：生命太虚弱，先养好伤再来", LOG_SYSTEM
                )
                return
            cost = max(1, round(self.player.hp * config.ROOM_SHRINE_HP_COST))
            self.player.take_damage(cost)
            self.player.atk += config.ROOM_SHRINE_ATK_BONUS
            self.used_features.add(pos)
            self._log(
                f"{label}吸走你 {cost} 点生命，作为交换，攻击永久 +"
                f"{config.ROOM_SHRINE_ATK_BONUS}",
                LOG_LEVEL,
            )
            self._emit("levelup", x=pos[0], y=pos[1], text="ATK UP")
        elif kind == "vault":
            self.used_features.add(pos)
            self._log(f"你踏入了{label}的中心，宝光刺眼", LOG_ITEM)

    # ---------------------------------------------------------------- 攻击
    def attack_tiles(self, x: int, y: int, slot: str = "weapon") -> frozenset[tuple[int, int]]:
        """预览：用 ``slot`` 槽位的武器打向 (x, y) 会覆盖哪些格子。

        界面用它画蓝色高亮，逻辑层用它判断命中，两边共用同一份计算。
        """
        weapon = self.player.equipment.get(slot)
        if weapon is None:
            return frozenset()
        return pattern_tiles(
            self.player.pos,
            (x, y),
            getattr(weapon, "pattern", "melee"),
            getattr(weapon, "reach", 1),
            getattr(weapon, "min_reach", 1),
            blocked=lambda cx, cy: not self.dungeon.is_walkable(cx, cy),
        )

    def can_attack_at(self, x: int, y: int, slot: str = "weapon") -> tuple[bool, str]:
        """攻击可行性校验，返回 (是否可行, 给玩家看的原因)。"""
        if self.is_finished:
            return False, "本局已经结束"
        weapon = self.player.equipment.get(slot)
        if weapon is None:
            return False, "没有装备这类武器" if slot == "ranged" else "没有装备近战武器"
        if (x, y) == self.player.pos:
            return False, "不能攻击自己脚下"
        if (x, y) not in self.dungeon.explored:
            return False, "那一格还没探索过"
        if getattr(weapon, "pattern", "melee") == "ranged":
            distance = chebyshev(self.player.pos, (x, y))
            min_reach = getattr(weapon, "min_reach", 1)
            reach = getattr(weapon, "reach", 1)
            if distance < min_reach:
                return False, f"{weapon.name}太近了，至少隔 {min_reach} 格"
            if distance > reach:
                return False, f"超出{weapon.name}的射程（{reach} 格）"
            if not self.dungeon.has_line_of_sight(
                self.player.x, self.player.y, x, y
            ):
                return False, "视线被墙挡住了"
        tiles = self.attack_tiles(x, y, slot)
        if not tiles:
            return False, "那个方向打不到"
        # 关键：点击的格子必须真的落在攻击形状里。
        # 否则"拿剑点远处"也会通过校验——方向上有格子就算合法，实际却打在空地上。
        if (x, y) not in tiles:
            return False, "那个位置不在攻击范围内"
        return True, ""

    def attack_at(self, x: int, y: int, slot: str = "weapon") -> bool:
        """向 (x, y) 方向发动一次攻击。这是玩家回合的另一种行动。

        - 轻武器：立即结算；
        - 重武器（``charge > 0``）：先进入蓄力，下一回合自动落下。
        """
        if self.is_finished:
            return False
        ok, reason = self.can_attack_at(x, y, slot)
        if not ok:
            self._log(reason, LOG_SYSTEM)
            return False

        weapon = self.player.equipment[slot]
        tiles = self.attack_tiles(x, y, slot)
        charge = int(getattr(weapon, "charge", 0))

        if charge > 0:
            def begin() -> bool:
                self.player.charge_left = charge
                self.player.charge_weapon = weapon.key
                self.player.charge_tiles = set(tiles)
                self._emit("charge", x=self.player.x, y=self.player.y, text=f"{charge}")
                self._log(
                    f"你举起{weapon.name}开始蓄力（{charge} 回合后落下）", LOG_COMBAT
                )
                return True

            return self._take_turn(begin)

        return self._take_turn(lambda: self._resolve_player_attack(weapon, tiles))

    def _resolve_player_attack(self, weapon: "Item", tiles: frozenset[tuple[int, int]]) -> bool:
        """把一次攻击结算到区域内所有敌人身上。"""
        targets = [
            monster
            for monster in list(self.monsters)
            if monster.alive and (monster.x, monster.y) in tiles
        ]
        power = self.player.attack_power(weapon)
        if not targets:
            self._log(f"{weapon.name}挥空，没有打到任何东西", LOG_COMBAT)
            return True

        for monster in targets:
            result = resolve_attack(power, monster.total_def(), self.rng)
            if not result.hit:
                self._log(f"{monster.name}闪身躲开了{weapon.name}", LOG_COMBAT)
                self._emit("miss", x=monster.x, y=monster.y, text="MISS")
                continue
            actual = monster.take_damage(result.damage)
            self.player.damage_dealt += actual
            tone = "crit" if result.crit else "player"
            self._emit("damage", x=monster.x, y=monster.y, text=f"-{actual}", tone=tone)
            prefix = "暴击！" if result.crit else ""
            self._log(f"{prefix}{weapon.name}命中{monster.name}，造成 {actual} 点伤害", LOG_COMBAT)
            if not monster.alive:
                self._kill_monster(monster)
        return True

    def _tick_player_charge(self) -> None:
        """回合开始时推进玩家蓄力；归零则落下。"""
        if self.player.charge_left <= 0:
            return
        self.player.charge_left -= 1
        if self.player.charge_left > 0:
            self._log(f"蓄力中……还需 {self.player.charge_left} 回合", LOG_COMBAT)
            return
        weapon = self.player.equipment.get("weapon") or self.player.equipment.get("ranged")
        tiles = frozenset(self.player.charge_tiles)
        self.player.charge_tiles = set()
        self.player.charge_weapon = ""
        if weapon is not None and tiles:
            self._resolve_player_attack(weapon, tiles)

    def wait(self) -> bool:
        """原地等待一回合，用于诱敌或回血节奏。"""
        if self.is_finished:
            return False
        return self._take_turn(lambda: True)

    def interact(self) -> bool:
        """拾取脚下道具或查看楼梯。不消耗回合，属于"无风险操作"。"""
        if self.is_finished:
            return False
        item = self.item_at(*self.player.pos)
        if item is not None:
            ok, message = self.player.pick_up(item)
            if ok:
                del self.items_on_floor[self.player.pos]
                self._log(message, LOG_ITEM)
                self._emit("pickup", x=self.player.x, y=self.player.y, text=item.name)
            else:
                self._log(message, LOG_DANGER)
            return ok
        if self.stairs_here:
            self._log("脚下是向下的楼梯：按 > 键、按 G 键，或直接点击自己所在格都能下楼", LOG_SYSTEM)
        else:
            self._log("这里没有可以拾取的东西", LOG_SYSTEM)
        return False

    def use_item(self, index: int) -> bool:
        """使用背包第 index 格道具，成功后消耗一个回合。"""
        if self.is_finished:
            return False
        if index < 0 or index >= len(self.player.inventory):
            self._log("这个格子里没有道具", LOG_SYSTEM)
            return False
        item = self.player.inventory[index]

        def act() -> bool:
            ok, message = self.player.use_item(index, self)
            self._log(message, LOG_ITEM if ok else LOG_DANGER)
            if ok:
                self._emit("item", x=self.player.x, y=self.player.y, text=item.name)
                self.dungeon.compute_fov(self.player.x, self.player.y)
            return ok

        return self._take_turn(act)

    def descend(self) -> bool:
        """走上楼梯，进入下一层。换层不触发怪物回合。"""
        if self.is_finished:
            return False
        if self.dungeon.stairs is None:
            self._log("这里是地下城的最深处，没有再往下的路了", LOG_SYSTEM)
            return False
        if not self.stairs_here:
            self._log("这里没有向下的楼梯", LOG_SYSTEM)
            return False

        self._build_floor(self.floor + 1)
        self.turn += 1
        self.player.turns = self.turn
        # 换了地图，之前锁定的打击点已经失效，蓄力必须清空
        self.player.charge_left = 0
        self.player.charge_tiles = set()
        self.player.charge_weapon = ""
        self._log(f"你沿着石阶下到了第 {self.floor} 层", LOG_SYSTEM)
        if self.floor == config.BOSS_FLOOR:
            # 进入最终层时回满生命：否则玩家往往带着残血和空药水进场，
            # BOSS 战就变成"比谁先掉血"的算术题，而不是一场公平的决斗
            healed = self.player.heal(self.player.max_hp)
            self._log("你在通往深渊的石阶上稍作休整，体力恢复如初", LOG_LEVEL)
            if healed:
                self._emit("heal", x=self.player.x, y=self.player.y, text=f"+{healed}")
            self._log("空气骤然变冷……深渊领主就在这一层！", LOG_DANGER)
            self._emit("danger")
        self.dungeon.compute_fov(self.player.x, self.player.y)
        return True

    # ================================================================ 卷轴辅助
    def teleport_player(self) -> tuple[int, int]:
        """随机传送到本层另一个可走格，返回新坐标。"""
        occupied = {(m.x, m.y) for m in self.monsters if m.alive}
        occupied.add(self.player.pos)
        pos = self.dungeon.random_floor(self.rng, occupied)
        self.player.move_to(*pos)
        self.dungeon.compute_fov(self.player.x, self.player.y)
        return pos

    def damage_visible_monsters(self, power: int) -> int:
        """对视野内所有怪物造成固定伤害（无视防御），返回受影响的数量。"""
        targets = self.visible_monsters()
        for monster in targets:
            actual = monster.take_damage(power)
            self.player.damage_dealt += actual
            self._emit("damage", x=monster.x, y=monster.y, text=f"-{actual}", tone="magic")
            if not monster.alive:
                self._kill_monster(monster)
        self.dungeon.compute_fov(self.player.x, self.player.y)
        return len(targets)

    # ================================================================ 回合流水线
    def _take_turn(self, action: Callable[[], bool]) -> bool:
        """执行一次完整回合：结算蓄力 → 玩家行动 → 怪物行动 → 刷新视野 → 判定状态。"""
        if self.is_finished:
            return False

        # 先推进玩家自己的蓄力：重武器是这一回合开始落下的
        self._tick_player_charge()
        if self.is_finished:
            return False

        if not action():
            return False

        self.turn += 1
        self.player.turns = self.turn
        self.floor_turns[str(self.floor)] = self.floor_turns.get(str(self.floor), 0) + 1

        self._monster_phase()
        self.dungeon.compute_fov(self.player.x, self.player.y)
        self._check_status()
        return True

    def _kill_monster(self, monster: Monster) -> None:
        """统一处理击杀：移除、给经验、给金币、判定通关。"""
        monster.alive = False
        if monster in self.monsters:
            self.monsters.remove(monster)
        self.player.kills += 1
        self.player.gold += monster.gold_reward
        self._log(
            f"你击败了{monster.name}（+{monster.exp_reward} 经验，+{monster.gold_reward} 金币）",
            LOG_COMBAT,
        )
        for message in self.player.gain_exp(monster.exp_reward):
            self._log(message, LOG_LEVEL)
            self._emit("levelup", x=self.player.x, y=self.player.y, text="LEVEL UP")

        if monster.is_boss:
            self.status = GameStatus.WIN
            self._log("深渊领主轰然倒下，地下城的诅咒解除了——你通关了！", LOG_LEVEL)

    def _monster_phase(self) -> None:
        """所有存活怪物依次行动，每只怪物每回合也只有一个行动。"""
        for monster in list(self.monsters):
            if not monster.alive or self.player.hp <= 0:
                break
            self._monster_turn(monster)

    def _monster_turn(self, monster: Monster) -> None:
        """单只怪物的回合：治疗兵先走治疗逻辑，其余按"蓄力→起手→走位"顺序。"""
        # 0) 治疗怪：不攻击，只回血；没人可治时后退拉开距离
        if monster.is_support:
            self._support_turn(monster)
            return

        # 1) 已经锁定了打击区域：原地维持，计数归零就落下
        if monster.charge_left > 0:
            monster.charge_left -= 1
            if monster.charge_left == 0:
                self._enemy_strike(monster)
            return

        # 2) 玩家已经落在攻击形状里 → 起手蓄力（这就是红色预警的来源）
        tiles = self._enemy_pattern(monster)
        if self.player.pos in tiles:
            monster.begin_charge(tiles)
            self._log(
                f"{monster.name}开始蓄力（{monster.range_text}），"
                f"{monster.charge_turns} 回合后出手——离开它标记的区域！",
                LOG_DANGER,
            )
            self._emit("telegraph", x=monster.x, y=monster.y)
            return

        # 3) 够不到就走位
        if monster.ai == "guard":
            return
        if monster.ai == "wander":
            if self.rng.chance(0.35):
                step = monster.wander_step(self.dungeon, self.rng)
                if step is not None and not self._blocked_by_actor(monster, *step):
                    monster.move_to(*step)
            return

        step = monster._greedy_step(self.dungeon, self.player)
        if step is not None and not self._blocked_by_actor(monster, *step):
            monster.move_to(*step)

    def _support_turn(self, monster: Monster) -> None:
        """治疗兵的回合：优先给最虚弱的同伴回血，没得治就后退。

        "后退"而不是"发呆"是有意为之：如果它站着不动，玩家可以把它留到最后
        慢慢砍；让它主动拉开距离，才会形成"先杀治疗"的真实压力。
        """
        allies = [
            other
            for other in self.monsters
            if other.alive
            and other is not monster
            and chebyshev((monster.x, monster.y), (other.x, other.y)) <= monster.reach
            and self.dungeon.has_line_of_sight(
                monster.x, monster.y, other.x, other.y
            )
        ]
        picked = monster.heal_target(allies)
        if picked is not None:
            target, amount = picked
            healed = target.heal(amount)
            if healed > 0:
                self._log(
                    f"{monster.name}为{target.name}注入暗影愈合，回复 {healed} 点生命",
                    LOG_DANGER if target is not monster else LOG_COMBAT,
                )
                self._emit("heal", x=target.x, y=target.y, text=f"+{healed}")
                return
        self._retreat(monster)

    def _retreat(self, monster: Monster) -> None:
        """朝"离玩家更远"的方向退一步；无路可退就原地不动。"""
        current = chebyshev((monster.x, monster.y), self.player.pos)
        best: tuple[int, int] | None = None
        best_distance = current
        for nx, ny in Dungeon.neighbors4(monster.x, monster.y):
            if not self.dungeon.is_walkable(nx, ny) or self._blocked_by_actor(monster, nx, ny):
                continue
            distance = chebyshev((nx, ny), self.player.pos)
            if distance > best_distance:
                best_distance = distance
                best = (nx, ny)
        if best is not None:
            monster.move_to(*best)

    def _blocked_by_actor(self, mover: Monster, x: int, y: int) -> bool:
        """目标格是否被玩家或别的怪物占着。"""
        if (x, y) == self.player.pos:
            return True
        return any(m.alive and m is not mover and (m.x, m.y) == (x, y) for m in self.monsters)

    def _enemy_pattern(self, monster: Monster) -> frozenset[tuple[int, int]]:
        """怪物朝玩家方向的攻击形状（远程还要检查视线）。

        治疗兵没有攻击形状：``pattern_tiles`` 只认四种攻击形态，
        把 ``support`` 传进去会直接抛错，所以这里必须提前返回空集。
        """
        if monster.is_support:
            return frozenset()
        if monster.pattern == "ranged" and not self.dungeon.has_line_of_sight(
            monster.x, monster.y, self.player.x, self.player.y
        ):
            return frozenset()
        return pattern_tiles(
            monster.pos,
            self.player.pos,
            monster.pattern,
            monster.reach,
            monster.min_reach,
            blocked=lambda cx, cy: not self.dungeon.is_walkable(cx, cy),
        )

    def _enemy_strike(self, monster: Monster) -> None:
        """蓄力完成，对锁定区域结算一次打击。"""
        tiles = frozenset(monster.telegraph)
        monster.telegraph = set()
        if self.player.pos not in tiles:
            self._log(f"{monster.name}的攻击落空了——你已离开那片区域", LOG_COMBAT)
            self._emit("miss", x=monster.x, y=monster.y, text="落空")
            return

        result = resolve_attack(monster.total_atk(), self.player.total_def(), self.rng)
        if not result.hit:
            self._log(f"{monster.name}的攻击被你躲开", LOG_COMBAT)
            return
        actual = self.player.take_damage(result.damage)
        self.player.damage_taken += actual
        self._emit("damage", x=self.player.x, y=self.player.y, text=f"-{actual}", tone="hurt")
        self._log(f"{monster.name}命中你，造成 {actual} 点伤害", LOG_DANGER)

        if not self.player.alive:
            self.status = GameStatus.DEAD
            self.death_cause = monster.name
            self._log(f"你被{monster.name}击倒了……", LOG_DANGER)

    def _check_status(self) -> None:
        """回合结束后统一判定死亡与超时。"""
        if self.player.hp <= 0 and self.status == GameStatus.PLAYING:
            self.status = GameStatus.DEAD
            if not self.death_cause:
                self.death_cause = "未知原因"
        if self.turn > config.FLOOR_TURN_LIMIT and self.status == GameStatus.PLAYING:
            self.status = GameStatus.TIMEOUT
            self.death_cause = "在地下城中迷失了方向"
            self._log("你在迷宫深处耗尽了时间……", LOG_DANGER)

    def _auto_pickup(self) -> None:
        """踩到道具时自动拾取，减少玩家操作负担。"""
        item = self.item_at(*self.player.pos)
        if item is None:
            return
        ok, message = self.player.pick_up(item)
        if ok:
            del self.items_on_floor[self.player.pos]
            self._log(message, LOG_ITEM)
            self._emit("pickup", x=self.player.x, y=self.player.y, text=item.name)
        else:
            self._log(message, LOG_DANGER)

    # ================================================================ 事件与日志
    def _emit(self, kind: str, **payload: Any) -> None:
        """推入一个表现事件，等界面层取走。"""
        payload["kind"] = kind
        self.events.append(payload)

    def drain_events(self) -> list[dict[str, Any]]:
        """取走全部待处理事件（取走后清空）。"""
        events = self.events
        self.events = []
        return events

    def _log(self, text: str, tag: str = LOG_SYSTEM) -> None:
        self.log.append((text, tag))

    def recent_log(self, count: int = 20) -> list[LogEntry]:
        return list(self.log)[-count:]

    # ================================================================ 结算
    def build_record(self, now: datetime | None = None) -> dict[str, Any]:
        """生成一条对局记录，写入 records.json 供统计分析。"""
        now = now or datetime.now()
        try:
            started = datetime.fromisoformat(self.started_at)
            duration = max(0, int((now - started).total_seconds()))
        except (ValueError, TypeError):
            duration = 0
        record_id = f"{now.strftime('%Y%m%d-%H%M%S')}-{self.rng.seed % 10000:04d}"
        return {
            "id": record_id,
            "started_at": self.started_at,
            "ended_at": now.isoformat(timespec="seconds"),
            "seed": self.rng.seed,
            "result": self.status,
            "death_cause": self.death_cause,
            "max_floor": self.max_floor,
            "turns": self.turn,
            "kills": self.player.kills,
            "gold": self.player.gold,
            "damage_dealt": self.player.damage_dealt,
            "damage_taken": self.player.damage_taken,
            "items_used": self.player.items_used,
            "duration_sec": duration,
            "player_level": self.player.level,
            "floor_stay": dict(self.floor_turns),
        }

    # ================================================================ 序列化
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": config.SAVE_VERSION,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "meta": {
                "seed": self.rng.seed,
                "floor": self.floor,
                "turn": self.turn,
                "status": self.status,
                "preview": f"第 {self.floor} 层 · HP {self.player.hp}/{self.player.max_hp} · 回合 {self.turn}",
            },
            "rng": {"seed": self.rng.seed, "state": self.rng.get_state()},
            "player": self.player.to_dict(),
            "dungeon": {
                "width": self.dungeon.width,
                "height": self.dungeon.height,
                "rows": self.dungeon.to_rows(),
                "stairs": list(self.dungeon.stairs) if self.dungeon.stairs else None,
                "explored": sorted(f"{x},{y}" for x, y in self.dungeon.explored),
                # 房间几何不存，只存"坐标 → 玩法"的映射，读档后依然能触发
                "features": [
                    {"x": pos[0], "y": pos[1], "kind": kind}
                    for pos, kind in sorted(self.dungeon.features.items())
                ],
            },
            "monsters": [m.to_dict() for m in self.monsters],
            "items": [
                dict(item.to_dict(), x=pos[0], y=pos[1])
                for pos, item in self.items_on_floor.items()
            ],
            "log": [{"text": text, "tag": tag} for text, tag in self.recent_log(40)],
            "progress": {
                "status": self.status,
                "death_cause": self.death_cause,
                "started_at": self.started_at,
                "max_floor": self.max_floor,
                "floor_turns": self.floor_turns,
                "turn": self.turn,
                "floor": self.floor,
                "adaptive_difficulty": self.adaptive_difficulty,
                "difficulty": self.difficulty,
                "used_features": [
                    f"{x},{y}" for x, y in sorted(self.used_features)
                ],
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        """从存档字典还原。

        任何字段缺失或类型错误都会抛出 ``ValueError``，
        由 ``SaveManager`` 统一包装成 ``SaveError``。
        """
        try:
            rng_data = data["rng"]
            rng = Rng(int(rng_data.get("seed") or data["meta"]["seed"]))
            rng.set_state(rng_data["state"])

            player = Player.from_dict(data["player"])

            dungeon_data = data["dungeon"]
            explored = {
                (int(pair.split(",")[0]), int(pair.split(",")[1]))
                for pair in dungeon_data.get("explored", [])
            }
            stairs_raw = dungeon_data.get("stairs")
            stairs = (int(stairs_raw[0]), int(stairs_raw[1])) if stairs_raw else None
            dungeon = Dungeon.from_rows(dungeon_data["rows"], stairs, explored)
            # 旧存档（v2 及更早）没有 features 字段，读回来就是"这一层没有趣味房间"
            for entry in dungeon_data.get("features", []):
                kind = str(entry.get("kind", ""))
                if kind in ROOM_FEATURES:
                    dungeon.features[(int(entry["x"]), int(entry["y"]))] = kind

            monsters = [Monster.from_dict(d) for d in data.get("monsters", [])]
            items: dict[tuple[int, int], Item] = {}
            for entry in data.get("items", []):
                items[(int(entry["x"]), int(entry["y"]))] = item_from_dict(entry)

            progress = data.get("progress", {})
            used_features = {
                (int(pair.split(",")[0]), int(pair.split(",")[1]))
                for pair in progress.get("used_features", [])
            }
            state = cls(
                rng=rng,
                player=player,
                dungeon=dungeon,
                monsters=monsters,
                items_on_floor=items,
                floor=int(progress.get("floor") or data["meta"].get("floor") or 1),
                turn=int(progress.get("turn") or data["meta"].get("turn") or 0),
                status=str(progress.get("status", GameStatus.PLAYING)),
                death_cause=str(progress.get("death_cause", "")),
                started_at=progress.get("started_at"),
                max_floor=int(progress.get("max_floor", 1)),
                floor_turns={str(k): int(v) for k, v in (progress.get("floor_turns") or {}).items()},
                used_features=used_features,
                adaptive_difficulty=bool(progress.get("adaptive_difficulty", True)),
                difficulty=str(progress.get("difficulty", config.DEFAULT_DIFFICULTY)),
            )
            for entry in data.get("log", []):
                state.log.append((str(entry.get("text", "")), str(entry.get("tag", LOG_SYSTEM))))
            dungeon.compute_fov(player.x, player.y)
            return state
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"存档内容不完整：{exc}") from exc

    # ================================================================ 调试辅助
    def ascii_view(self) -> str:
        """把当前层渲染成文本，供命令行调试与自动模拟检查。"""
        lines: list[str] = []
        for y in range(self.dungeon.height):
            row: list[str] = []
            for x in range(self.dungeon.width):
                if (x, y) == self.player.pos:
                    row.append("@")
                    continue
                monster = self.monster_at(x, y)
                if monster is not None and (x, y) in self.dungeon.visible:
                    row.append(monster.glyph)
                    continue
                tile = self.dungeon.tile_at(x, y)
                if (x, y) in self.dungeon.visible:
                    row.append(tile.char if tile is not Tile.WALL else "#")
                elif (x, y) in self.dungeon.explored:
                    row.append("," if tile.walkable else " ")
                else:
                    row.append(" ")
            lines.append("".join(row))
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<GameState floor={self.floor} turn={self.turn} status={self.status}>"
