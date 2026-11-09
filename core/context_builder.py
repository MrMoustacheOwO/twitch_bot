"""
Context Builder — собирает StreamSnapshot из всех источников.

Подписывается на события шины, накапливает данные в кольцевых буферах,
периодически формирует StreamSnapshot и публикует его всем ботам.

Это единственное место, где строится контекст. Все 100 ботов
получают ОДИН объект — никакого дублирования вычислений.
"""
from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime

from loguru import logger

from core.event_bus import (
    EventBus,
    CHAT_MESSAGE,
    STT_PHRASE,
    VISION_FRAME,
    SNAPSHOT_READY,
)
from core.models import (
    ChatMessage,
    ChatMood,
    ScreenEvent,
    StreamSnapshot,
)


# Ключевые слова для определения темы и настроения чата
_HYPE_WORDS = {"го", "го го", "pog", "wow", "лол", "кек", "gg", "ez", "огонь"}
_ANGRY_WORDS = {"oof", "нет", "упал", "умер", "фейл", "fail", "блин", "ну зачем"}
_FUNNY_WORDS = {"lol", "lmao", "kek", "хаха", "смешно", "кринж"}


def _detect_mood(messages: list[ChatMessage]) -> ChatMood:
    if not messages:
        return ChatMood.NEUTRAL
    text = " ".join(m.text.lower() for m in messages[-20:])
    if any(w in text for w in _HYPE_WORDS):
        return ChatMood.HYPE
    if any(w in text for w in _ANGRY_WORDS):
        return ChatMood.ANGRY
    if any(w in text for w in _FUNNY_WORDS):
        return ChatMood.FUNNY
    return ChatMood.NEUTRAL


def _detect_topic(messages: list[ChatMessage]) -> str:
    if not messages:
        return ""
    # Берём последние 15 сообщений, ищем самое частое слово длиннее 4 символов
    words: dict[str, int] = {}
    for m in messages[-15:]:
        for word in m.text.lower().split():
            if len(word) > 4:
                words[word] = words.get(word, 0) + 1
    if not words:
        return ""
    top = max(words, key=words.__getitem__)
    return top if words[top] >= 2 else ""


class ContextBuilder:
    """
    Накапливает данные от всех модулей восприятия.
    Каждые `interval_sec` секунд публикует StreamSnapshot на шину.
    """

    def __init__(
        self,
        bus: EventBus,
        interval_sec: int = 5,
        chat_history_size: int = 100,
        speech_history_size: int = 20,
        event_history_size: int = 30,
    ) -> None:
        self._bus = bus
        self._interval = interval_sec

        # Кольцевые буферы — потокобезопасны в asyncio (одно событийное кольцо)
        self._chat: deque[ChatMessage] = deque(maxlen=chat_history_size)
        self._speech: deque[str] = deque(maxlen=speech_history_size)
        self._event_history: deque[str] = deque(maxlen=event_history_size)

        # Последнее состояние экрана
        self._screen_description: str = ""
        self._screen_event: ScreenEvent = ScreenEvent.UNKNOWN
        self._current_game: str = "неизвестная игра"

        self._running = False

    def setup(self) -> None:
        """Регистрирует обработчики событий на шине."""
        self._bus.subscribe(CHAT_MESSAGE, self._on_chat_message)
        self._bus.subscribe(STT_PHRASE, self._on_stt_phrase)
        self._bus.subscribe(VISION_FRAME, self._on_vision_frame)

    async def _on_chat_message(self, msg: ChatMessage) -> None:
        self._chat.append(msg)

    async def _on_stt_phrase(self, phrase: str) -> None:
        self._speech.append(phrase)
        self._event_history.append(f"Стример: «{phrase[:80]}»")

    async def _on_vision_frame(self, data: dict) -> None:
        """
        data = {
            "description": str,
            "event": ScreenEvent,
            "game": str (optional)
        }
        """
        self._screen_description = data.get("description", "")
        event = data.get("event", ScreenEvent.UNKNOWN)
        self._screen_event = event
        if "game" in data:
            self._current_game = data["game"]

        # Добавляем значимые события в историю
        if event not in (ScreenEvent.UNKNOWN, ScreenEvent.EXPLORATION):
            self._event_history.append(
                f"На экране: {event.value} — {self._screen_description[:60]}"
            )

    def _build_snapshot(self) -> StreamSnapshot:
        chat_list = list(self._chat)
        return StreamSnapshot(
            timestamp=datetime.utcnow(),
            screen_description=self._screen_description,
            screen_event=self._screen_event,
            current_game=self._current_game,
            streamer_speech=list(self._speech),
            recent_chat=chat_list,
            chat_topic=_detect_topic(chat_list),
            chat_mood=_detect_mood(chat_list),
            event_history=list(self._event_history),
        )

    async def run(self) -> None:
        """Основной цикл: каждые N секунд публикует снимок."""
        self._running = True
        logger.info(f"ContextBuilder запущен, интервал={self._interval}s")
        while self._running:
            await asyncio.sleep(self._interval)
            snapshot = self._build_snapshot()
            logger.debug(
                f"Snapshot: game={snapshot.current_game!r} "
                f"event={snapshot.screen_event.value} "
                f"chat_msgs={len(snapshot.recent_chat)}"
            )
            await self._bus.publish(SNAPSHOT_READY, snapshot)

    def stop(self) -> None:
        self._running = False
