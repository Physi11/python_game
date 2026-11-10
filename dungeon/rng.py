"""随机数封装模块。

设计要点
--------
1. 全项目**只使用一个 Rng 实例**，禁止直接调用 ``random.randint`` 等模块级函数。
   模块级函数共享全局状态，任何第三方库调用都会污染序列，导致"读档后行为漂移"。
2. 存档同时保存 ``seed``（人类可读、可复现整局）和 ``state``
   （``getstate()`` 的精确快照）。因为 Mersenne Twister 已经抽取过几百次，
   仅凭 seed 无法回到"当前这一刻"，必须靠 state 才能 100% 复现。
3. ``state`` 序列化为纯 JSON 结构，不使用 pickle（pickle 可执行任意代码、
   且与类的模块路径绑定，重命名类即失效）。
"""

from __future__ import annotations

import random
from typing import Any


class Rng:
    """对 ``random.Random`` 的薄封装，额外提供状态导出/恢复能力。"""

    def __init__(self, seed: int | None = None) -> None:
        if seed is None:
            seed = random.SystemRandom().randint(1, 999_999_999)
        self.seed: int = int(seed)
        self._random = random.Random(self.seed)

    # ---------------------------------------------------------- 常用转发
    def random(self) -> float:
        """返回 [0.0, 1.0) 之间的随机浮点数。"""
        return self._random.random()

    def randint(self, a: int, b: int) -> int:
        """返回 [a, b] 闭区间内的随机整数。"""
        return self._random.randint(a, b)

    def choice(self, seq: list[Any] | tuple[Any, ...]) -> Any:
        """从序列中随机取一个元素。"""
        return self._random.choice(seq)

    def choices(self, population: list[Any], weights: list[float], k: int = 1) -> list[Any]:
        """按权重有放回抽样，用于怪物类型加权抽取。"""
        return self._random.choices(population, weights=weights, k=k)

    def shuffle(self, seq: list[Any]) -> None:
        """原地打乱序列。"""
        self._random.shuffle(seq)

    def sample(self, population: list[Any], k: int) -> list[Any]:
        """无放回抽样 k 个元素。"""
        return self._random.sample(population, k)

    def chance(self, probability: float) -> bool:
        """以给定概率返回 True，用于暴击/落空判定。"""
        return self._random.random() < probability

    # ---------------------------------------------------------- 状态导出/恢复
    def get_state(self) -> dict[str, Any]:
        """把内部状态导出为可直接写 JSON 的字典。

        ``random.Random.getstate()`` 返回三元组 ``(version, internal, gauss)``，
        其中 ``internal`` 是 625 个整数的元组。元组无法直接 JSON 化，故转成列表。
        """
        version, internal, gauss = self._random.getstate()
        return {
            "version": int(version),
            "keys": [int(k) for k in internal],
            "gauss": None if gauss is None else float(gauss),
        }

    def set_state(self, data: dict[str, Any]) -> None:
        """从 :meth:`get_state` 导出的字典恢复内部状态。

        参数缺失或格式非法时会抛出 ``ValueError``，由存档层统一转换成
        用户可读的 ``SaveError``。
        """
        try:
            version = int(data["version"])
            keys = tuple(int(k) for k in data["keys"])
            gauss = data.get("gauss")
            if len(keys) != 625:
                raise ValueError("随机数状态长度异常")
            self._random.setstate((version, keys, gauss))
        except (KeyError, TypeError) as exc:  # 字段缺失 / 类型不对
            raise ValueError(f"随机数状态不合法：{exc}") from exc

    # ---------------------------------------------------------- 其它
    def reseed(self, seed: int) -> None:
        """重置种子，开始新一局时使用。"""
        self.seed = int(seed)
        self._random.seed(self.seed)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"<Rng seed={self.seed}>"
