"""
Центральные модели данных системы.
StreamSnapshot — единственный объект, который передаётся всем ботам.
Создаётся один раз, транслируется всем — никаких дублирующих вычислений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ScreenEvent(str, Enum):
    FIGHT = "fight"
    VICTORY = "victory"
    DEFEAT = "defeat"
    MENU = "menu"
    DIALOGUE = "dialogue"
    EXPLORATION = "exploration"
    CUTSCENE = "cutscene"
    UNKNOWN = "unknown"


class ChatMood(str, Enum):
    HYPE = "hype"
    CALM = "calm"
    ANGRY = "angry"
    FUNNY = "funny"
    SAD = "sad"
    NEUTRAL = "neutral"


@dataclass
class ChatMessage:
    username: str
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __str__(self) -> str:
        return f"{self.username}: {self.text}"


@dataclass
class StreamSnapshot:
    """
    Снимок состояния трансляции в конкретный момент времени.

    Создаётся ContextBuilder один раз и передаётся всем ботам без копирования.
    STT, Vision и Context — вычисляются ОДИН раз на всю систему.
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Результат Vision модуля (Qwen2.5-VL)
    screen_description: str = ""
    screen_event: ScreenEvent = ScreenEvent.UNKNOWN
    current_game: str = "неизвестная игра"

    # Результат STT модуля (Faster-Whisper)
    streamer_speech: list[str] = field(default_factory=list)

    # Состояние чата (TwitchIO)
    recent_chat: list[ChatMessage] = field(default_factory=list)
    chat_topic: str = ""
    chat_mood: ChatMood = ChatMood.NEUTRAL

    # Накопленная история событий
    event_history: list[str] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Форматирует снимок в читаемый текст для промпта LLM."""
        chat_lines = "\n".join(
            f"  {m}" for m in self.recent_chat[-10:]
        )
        speech_lines = "\n".join(f"  - {s}" for s in self.streamer_speech[-5:])
        history_lines = "\n".join(f"  - {e}" for e in self.event_history[-5:])

        return (
            f"=== Контекст трансляции ===\n"
            f"Игра: {self.current_game}\n"
            f"На экране: {self.screen_description}\n"
            f"Событие: {self.screen_event.value}\n\n"
            f"Стример говорил:\n{speech_lines or '  (тишина)'}\n\n"
            f"Последние сообщения чата:\n{chat_lines or '  (чат пуст)'}\n\n"
            f"Тема чата: {self.chat_topic}\n"
            f"Настроение чата: {self.chat_mood.value}\n\n"
            f"История событий:\n{history_lines or '  (нет данных)'}\n"
        )
