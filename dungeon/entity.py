"""实体基类模块。

``Entity`` 是玩家与怪物的公共父类，只负责"有坐标、有血量、能受伤"这些
最基础的能力；等级、背包、AI 等差异化内容分别放到 ``Player`` / ``Monster``。

把公共逻辑上提抽象类，是本项目"模块化设计"得分的基础：
同一份 ``take_damage`` 只写一次，玩家和怪物共用，没有重复代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Entity(ABC):
    """一切占据地图格子的实体。"""

    def __init__(
        self,
        name: str,
        glyph: str,
        x: int,
        y: int,
        hp: int,
        atk: int,
        defense: int,
    ) -> None:
        self.name: str = name
        self.glyph: str = glyph          # 界面上显示的单字符
        self.x: int = x
        self.y: int = y
        self.max_hp: int = max(1, int(hp))
        self.hp: int = self.max_hp
        self.atk: int = max(0, int(atk))
        self.defense: int = max(0, int(defense))
        self.alive: bool = True

    # ------------------------------------------------------------ 位置
    @property
    def pos(self) -> tuple[int, int]:
        return self.x, self.y

    def move_to(self, x: int, y: int) -> None:
        self.x, self.y = int(x), int(y)

    def distance_to(self, other: "Entity") -> int:
        """曼哈顿距离。本项目不限制斜向移动，用曼哈顿距离判断"相邻"最准确。"""
        return abs(self.x - other.x) + abs(self.y - other.y)

    def is_adjacent(self, other: "Entity") -> bool:
        return self.distance_to(other) == 1

    # ------------------------------------------------------------ 数值
    def total_atk(self) -> int:
        """实际攻击力。子类可叠加装备加成，基类直接返回基础值。"""
        return self.atk

    def total_def(self) -> int:
        """实际防御力。子类可叠加装备加成，基类直接返回基础值。"""
        return self.defense

    @property
    def hp_ratio(self) -> float:
        """血量百分比，界面绘制血条时使用。"""
        if self.max_hp <= 0:
            return 0.0
        return max(0.0, min(1.0, self.hp / self.max_hp))

    def take_damage(self, amount: int) -> int:
        """受到伤害，返回实际扣除的血量。

        - 传入负数视为非法参数，抛 ``ValueError``（由上层统一捕获转成提示）；
        - 扣血下限为 0，避免出现负血量导致血条反向绘制。
        """
        if amount < 0:
            raise ValueError("伤害值不能为负数")
        actual = min(amount, self.hp)
        self.hp -= actual
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
        return actual

    def heal(self, amount: int) -> int:
        """回复生命，返回实际回复量，溢出部分直接封顶到最大生命。"""
        if amount < 0:
            raise ValueError("治疗量不能为负数")
        if not self.alive:
            return 0
        before = self.hp
        self.hp = min(self.max_hp, self.hp + amount)
        return self.hp - before

    def revive_full(self) -> None:
        """满血复活，仅用于调试与自动模拟。"""
        self.hp = self.max_hp
        self.alive = True

    # ------------------------------------------------------------ 序列化
    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """导出为可 JSON 化的字典。"""

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entity":
        """从字典还原对象。"""

    def _base_dict(self) -> dict[str, Any]:
        """子类序列化时复用的公共字段。"""
        return {
            "cls": type(self).__name__,
            "name": self.name,
            "glyph": self.glyph,
            "x": self.x,
            "y": self.y,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "atk": self.atk,
            "defense": self.defense,
        }

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<{type(self).__name__} {self.name} hp={self.hp}/{self.max_hp} at=({self.x},{self.y})>"
