"""
Профили виртуальных зрителей и фабрика ботов.
Каждый профиль привязан к отдельному Twitch-аккаунту через поле account.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from bots.bot import Bot


@dataclass(frozen=True)
class BotProfile:
    name: str
    account: str
    style: str
    cooldown_sec: int = 60
    respond_probability: float = 0.3
    active: bool = True

    def __post_init__(self) -> None:
        if not self.account.strip():
            raise ValueError("account не может быть пустым")
        if not 0.0 < self.respond_probability <= 1.0:
            raise ValueError("respond_probability должна быть в (0, 1]")
        if self.cooldown_sec < 10:
            raise ValueError("cooldown_sec должен быть >= 10")


class BotFactory:
    @staticmethod
    def load_profiles(config_path: str | Path) -> list[BotProfile]:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Конфиг ботов не найден: {path}")

        with path.open(encoding="utf-8") as f:
            raw = json.load(f)

        profiles: list[BotProfile] = []
        for item in raw:
            try:
                profile = BotProfile(**item)
                if profile.active:
                    profiles.append(profile)
                    logger.debug(
                        f"Загружен профиль {profile.name!r} -> аккаунт {profile.account!r}"
                    )
            except (TypeError, ValueError) as e:
                logger.warning(
                    f"Ошибка в профиле бота {item.get('name')!r}: {e}"
                )

        logger.info(f"Загружено {len(profiles)} активных профилей")
        return profiles

    @staticmethod
    def create_bots(profiles: list[BotProfile]) -> list["Bot"]:
        from bots.bot import Bot
        return [Bot(profile) for profile in profiles]

    @classmethod
    def create_from_config(cls, config_path: str | Path) -> list["Bot"]:
        return cls.create_bots(cls.load_profiles(config_path))
