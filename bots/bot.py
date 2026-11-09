"""
Лёгкий агент виртуального зрителя.
Профиль содержит имя персонажа и Twitch-аккаунт, от имени которого он пишет.
"""
from __future__ import annotations

import random
import time

from core.models import StreamSnapshot
from bots.bot_profile import BotProfile


_SYSTEM_PROMPT = """\
Ты — зритель Twitch-трансляции. Ты пишешь сообщения в чат как живой человек.

Правила:
- Сообщение не длиннее 200 символов
- Пиши на русском языке, разговорным стилем
- НЕ используй слова: "стример", "виртуальный", "бот", "ИИ", "искусственный"
- Реагируй на то, что происходит прямо сейчас
- Не повторяй сообщения других зрителей
- Не пиши от имени других аккаунтов
- Пиши ТОЛЬКО само сообщение, без кавычек и пояснений"""


class Bot:
    __slots__ = ("profile", "_last_sent_at", "_message_count")

    def __init__(self, profile: BotProfile) -> None:
        self.profile = profile
        self._last_sent_at = 0.0
        self._message_count = 0

    @property
    def name(self) -> str:
        return self.profile.name

    @property
    def account(self) -> str:
        return self.profile.account

    def should_trigger(self, snapshot: StreamSnapshot) -> bool:
        elapsed = time.monotonic() - self._last_sent_at
        if elapsed < self.profile.cooldown_sec:
            return False

        chat_boost = min(0.15, len(snapshot.recent_chat) / 200)
        effective_prob = min(
            1.0, self.profile.respond_probability + chat_boost
        )
        return random.random() < effective_prob

    def build_prompt(self, snapshot: StreamSnapshot) -> str:
        context = snapshot.to_context_string()
        reply_hint = ""
        if snapshot.recent_chat:
            last = snapshot.recent_chat[-1]
            reply_hint = (
                f'\nПоследнее сообщение в чате: '
                f'{last.username}: "{last.text}"'
            )

        return (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Твой персонаж:\n"
            f"Имя персонажа: {self.profile.name}\n"
            f"Стиль: {self.profile.style}\n\n"
            f"{context}"
            f"{reply_hint}\n\n"
            f"Напиши одно сообщение в чат от лица этого персонажа:"
        )

    def on_message_sent(self) -> None:
        self._last_sent_at = time.monotonic()
        self._message_count += 1

    def stats(self) -> dict:
        return {
            "name": self.name,
            "account": self.account,
            "messages_sent": self._message_count,
            "last_sent_ago_sec": int(time.monotonic() - self._last_sent_at),
            "cooldown_sec": self.profile.cooldown_sec,
        }

    def __repr__(self) -> str:
        return f"Bot(name={self.name!r}, account={self.account!r}, msgs={self._message_count})"
