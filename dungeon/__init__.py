"""地下城探险 —— 纯逻辑层。

本包**不得**导入任何界面库（tkinter 等），以保证：

- ``tests/`` 下的单元测试可以在没有显示器的环境下运行；
- ``tools/balance_sim.py`` 可以批量自动对局做数值平衡验证；
- 将来把界面从 tkinter 换成网页或命令行时，业务代码一行都不用改。

``tests/test_architecture.py`` 中有一条"架构守卫"用例会自动扫描本目录源码，
一旦出现 ``import tkinter`` 即判定失败。
"""

from __future__ import annotations

from . import config
from .combat import AttackResult, base_damage, resolve_attack, strike
from .dungeon import Dungeon, Room, Tile
from .entity import Entity
from .game_state import GameState, GameStatus
from .item import Armor, Item, Potion, Scroll, Weapon, make_item, roll_item
from .monster import MONSTER_TABLE, Monster, MonsterProto
from .player import Player
from .rng import Rng
from .save_manager import SaveError, SaveManager
from .stats import StatsAnalyzer

__all__ = [
    "config",
    "AttackResult",
    "base_damage",
    "resolve_attack",
    "strike",
    "Dungeon",
    "Room",
    "Tile",
    "Entity",
    "GameState",
    "GameStatus",
    "Item",
    "Potion",
    "Weapon",
    "Armor",
    "Scroll",
    "make_item",
    "roll_item",
    "MONSTER_TABLE",
    "Monster",
    "MonsterProto",
    "Player",
    "Rng",
    "SaveError",
    "SaveManager",
    "StatsAnalyzer",
]

__version__ = "1.0.0"
