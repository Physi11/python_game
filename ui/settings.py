"""用户设置：数据模型、schema 与持久化。

为什么要有 schema
------------------
设置面板的每一行都由 :data:`SETTING_SPECS` 生成，界面代码里没有任何
"全屏复选框""难度下拉框"这样的硬编码。**新增一个设置项 = 往这个元组里
追加一条 ``SettingSpec``**，面板会自动多出一行、自动读写、自动持久化。
这就是需求里说的"为后续其他设置项预留扩展通道"。

文件位置固定在 ``data/settings.json``：
- 与存档分开，删存档不会丢设置；
- 读不出来（文件缺失、JSON 坏了、字段类型不对）时**一律回退默认值**，
  绝不让一个坏配置文件把游戏挡在启动界面之外。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "data" / "settings.json"


@dataclass(frozen=True)
class SettingSpec:
    """一条设置项的定义。

    ``kind`` 决定界面用什么控件渲染：
    - ``bool``   → 复选框
    - ``choice`` → 下拉框，取值来自 ``choices``
    """

    key: str
    label: str
    kind: str
    default: Any
    help: str = ""
    choices: tuple[tuple[str, str], ...] = ()   # (存储值, 显示名)

    def coerce(self, raw: Any) -> Any:
        """把外部读进来的值转成合法值；非法时返回默认值。"""
        if self.kind == "bool":
            return bool(raw) if isinstance(raw, bool) else self.default
        if self.kind == "choice":
            allowed = {value for value, _ in self.choices}
            return raw if raw in allowed else self.default
        return raw


# ------------------------------------------------------------------ 设置项
# 想加新设置？在这里追加一行就行，界面与持久化会自动跟上。
SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        key="fullscreen",
        label="全屏模式",
        kind="bool",
        default=False,
        help="按 F11 也可以随时切换",
    ),
    SettingSpec(
        key="adaptive_difficulty",
        label="自适应难度",
        kind="bool",
        default=True,
        help="状态好时多来一点敌人，状态差时少来一点；只调整对手，不会削弱你",
    ),
    SettingSpec(
        key="difficulty",
        label="难度预设",
        kind="choice",
        default="normal",
        help="影响敌人数量与精英出现频率",
        choices=(("easy", "轻松"), ("normal", "标准"), ("hard", "硬核")),
    ),
)


@dataclass
class Settings:
    """运行期设置。字段与 :data:`SETTING_SPECS` 的 key 一一对应。"""

    fullscreen: bool = False
    adaptive_difficulty: bool = True
    difficulty: str = "normal"
    # 预留位：以后加设置项时，把新字段写在这里并在 SETTING_SPECS 里登记

    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------ 读写
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """按 schema 逐项取值并校验，任何非法值都退回默认。"""
        values: dict[str, Any] = {}
        for spec in SETTING_SPECS:
            values[spec.key] = spec.coerce(data.get(spec.key, spec.default))
        settings = cls(**values)
        # 未知字段原样保留，方便不同版本之间来回切换而不丢设置
        known = {spec.key for spec in SETTING_SPECS}
        settings._extra = {k: v for k, v in data.items() if k not in known}
        return settings

    def to_dict(self) -> dict[str, Any]:
        data = {spec.key: getattr(self, spec.key, spec.default) for spec in SETTING_SPECS}
        data.update(self._extra)
        return data

    def apply(self, **changes: Any) -> None:
        """批量更新，只接受 schema 里登记过的键。"""
        known = {spec.key for spec in SETTING_SPECS}
        for key, value in changes.items():
            if key in known:
                setattr(self, key, value)


def load_settings(path: Path | None = None) -> Settings:
    """读取设置文件；不存在或损坏时返回默认设置。"""
    target = path or SETTINGS_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    try:
        return Settings.from_dict(data)
    except TypeError:      # 字段名对不上（例如手改出一个 schema 里没有的键）
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> bool:
    """写回设置文件。返回是否写入成功（失败不抛异常，不影响游戏运行）。"""
    target = path or SETTINGS_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def reset_settings(path: Path | None = None) -> Settings:
    """恢复默认并立即落盘，供设置面板的"恢复默认"按钮使用。"""
    settings = Settings()
    save_settings(settings, path)
    return settings
