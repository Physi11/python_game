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
from .dungeon import Dungeon, Tile
from .item import Item, item_from_dict, make_item, roll_item
from .monster import MONSTER_BY_KIND, Monster, MonsterAction, roll_monster
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

        self.log: deque[LogEntry] = deque(maxlen=200)
        self.events: list[dict[str, Any]] = []

    # ================================================================ 构造
    @classmethod
    def new_game(cls, seed: int | None = None, name: str = "冒险者") -> "GameState":
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
        )
        state.floor_turns = {"1": 0}
        state._build_floor(1)
        state._log(f"你踏入了地下城第 1 层，种子 {rng.seed}", LOG_SYSTEM)
        state._log("方向键/WASD 移动，撞向怪物即可攻击，走上楼梯按 > 下楼", LOG_SYSTEM)
        return state

    # ---------------------------------------------------------------- 楼层构建
    def _build_floor(self, floor: int) -> None:
        """生成一层地牢并放置玩家、楼梯、怪物与道具。"""
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

        # 怪物不得出现在出生房间，否则开局就被围殴
        occupied: set[tuple[int, int]] = set()
        for cell in dungeon.rooms[0].inner_cells():
            occupied.add(cell)
        occupied.add(start)
        if dungeon.stairs is not None:
            occupied.add(dungeon.stairs)

        self.monsters = []
        count = min(
            config.MONSTER_COUNT_BASE + config.MONSTER_COUNT_PER_FLOOR * (floor - 1),
            config.MONSTER_COUNT_MAX,
        )
        if floor == config.BOSS_FLOOR:
            # BOSS 层只留少量杂兵，让最终战的主角是深渊领主本身，
            # 而不是"先被十几只小怪耗光药水，再去打 BOSS"
            count = 6
        for _ in range(count):
            proto = roll_monster(self.rng, floor)
            pos = dungeon.random_floor(self.rng, occupied)
            occupied.add(pos)
            self.monsters.append(Monster(proto, pos[0], pos[1], floor))

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

        dungeon.compute_fov(self.player.x, self.player.y)

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
        """向 (dx, dy) 走一步；若目标格有怪物则改为攻击。

        返回 True 表示动作成功（消耗了一个回合），False 表示被墙挡住等无效操作。
        """
        if self.is_finished:
            return False
        if (dx, dy) not in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            self._log("无效的移动方向", LOG_SYSTEM)
            return False

        nx, ny = self.player.x + dx, self.player.y + dy
        target = self.monster_at(nx, ny)
        if target is not None:
            return self._take_turn(lambda: self._player_attack(target))

        if not self.dungeon.is_walkable(nx, ny):
            self._log("前面是石墙，无法通行", LOG_SYSTEM)
            self._emit("bump", x=nx, y=ny)
            return False

        def act() -> bool:
            self.player.move_to(nx, ny)
            self.player.steps += 1
            self._auto_pickup()
            return True

        return self._take_turn(act)

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
        """执行一次完整回合：玩家行动 → 怪物行动 → 视野刷新 → 状态判定。"""
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

    def _player_attack(self, monster: Monster) -> bool:
        """玩家攻击怪物。"""
        result = resolve_attack(self.player.total_atk(), monster.total_def(), self.rng)
        if not result.hit:
            self._log(f"你挥空了，{monster.name}闪身躲开", LOG_COMBAT)
            self._emit("miss", x=monster.x, y=monster.y, text="MISS")
            return True

        actual = monster.take_damage(result.damage)
        self.player.damage_dealt += actual
        tone = "crit" if result.crit else "player"
        self._emit("damage", x=monster.x, y=monster.y, text=f"-{actual}", tone=tone)
        prefix = "暴击！" if result.crit else ""
        self._log(f"{prefix}你击中{monster.name}，造成 {actual} 点伤害", LOG_COMBAT)

        if not monster.alive:
            self._kill_monster(monster)
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
        """所有存活怪物依次行动。"""
        for monster in list(self.monsters):
            if not monster.alive or self.player.hp <= 0:
                break
            action: MonsterAction = monster.decide(self.dungeon, self.player, self.rng)
            if action.kind == "attack":
                self._monster_attack(monster)
            elif action.kind == "move" and action.target is not None:
                nx, ny = action.target
                if (
                    self.dungeon.is_walkable(nx, ny)
                    and self.monster_at(nx, ny) is None
                    and (nx, ny) != self.player.pos
                ):
                    monster.move_to(nx, ny)

    def _monster_attack(self, monster: Monster) -> None:
        """怪物攻击玩家。"""
        result = resolve_attack(monster.total_atk(), self.player.total_def(), self.rng)
        if not result.hit:
            self._log(f"{monster.name}扑了个空", LOG_COMBAT)
            return
        actual = self.player.take_damage(result.damage)
        self.player.damage_taken += actual
        self._emit("damage", x=self.player.x, y=self.player.y, text=f"-{actual}", tone="hurt")
        self._log(f"{monster.name}咬中你，造成 {actual} 点伤害", LOG_DANGER)

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

            monsters = [Monster.from_dict(d) for d in data.get("monsters", [])]
            items: dict[tuple[int, int], Item] = {}
            for entry in data.get("items", []):
                items[(int(entry["x"]), int(entry["y"]))] = item_from_dict(entry)

            progress = data.get("progress", {})
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
