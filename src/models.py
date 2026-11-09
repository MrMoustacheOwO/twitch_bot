"""Общие модели данных, которыми обмениваются все модули."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ScreenEvent(str, Enum):
    UNKNOWN = "unknown"
    BATTLE = "battle"
    VICTORY = "victory"
    DEFEAT = "defeat"
    MENU = "menu"
    DIALOGUE = "dialogue"
    EXPLORATION = "exploration"
    CUTSCENE = "cutscene"
    LOADING = "loading"
    INVENTORY = "inventory"


@dataclass
class ChatMessage:
    username: str
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_bot: bool = False  # помечаем собственные сообщения


@dataclass
class StreamerPhrase:
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class FrameAnalysis:
    description: str
    event: ScreenEvent
    timestamp: datetime = field(default_factory=datetime.utcnow)
    confidence: float = 1.0


@dataclass
class StreamSnapshot:
    """
    Единое состояние трансляции — результат работы Context Engine.
    Вычисляется один раз и передаётся всем ботам.
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Из TwitchIRC
    recent_chat: list[ChatMessage] = field(default_factory=list)
    chat_topic: str = ""
    chat_mood: str = "нейтральный"  # позитивный / негативный / взволнованный

    # Из STT
    streamer_speech: list[StreamerPhrase] = field(default_factory=list)
    streamer_last_said: str = ""

    # Из Vision
    screen_description: str = ""
    screen_event: ScreenEvent = ScreenEvent.UNKNOWN
    current_game: str = ""

    # Агрегированное
    discussion_topic: str = ""
    last_significant_event: str = ""

    def to_context_text(self) -> str:
        """Человекочитаемое представление снимка для промпта."""
        chat_lines = "\n".join(
            f"  {m.username}: {m.text}"
            for m in self.recent_chat[-10:]
        )
        speech_lines = " / ".join(
            p.text for p in self.streamer_speech[-3:]
        ) or "—"

        return (
            f"Игра: {self.current_game or 'неизвестно'}\n"
            f"На экране: {self.screen_description or '—'}\n"
            f"Событие: {self.screen_event.value}\n"
            f"Стример говорит: {speech_lines}\n"
            f"Тема чата: {self.discussion_topic or '—'}\n"
            f"Настроение чата: {self.chat_mood}\n"
            f"Последнее важное событие: {self.last_significant_event or '—'}\n"
            f"Последние сообщения:\n{chat_lines}"
        )


@dataclass
class BotMessage:
    """Сообщение, готовое к публикации."""
    bot_name: str
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    snapshot_id: Optional[str] = None
