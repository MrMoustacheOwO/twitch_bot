"""
Шина событий на базе asyncio.
Модули восприятия публикуют события → Context Builder подписывается.
Паттерн: publish-subscribe без внешних брокеров.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine

from loguru import logger


EventHandler = Callable[[Any], Coroutine[Any, Any, None]]


class EventBus:
    """
    Простая асинхронная шина событий.

    Использование:
        bus = EventBus()
        bus.subscribe("chat_message", handler)
        await bus.publish("chat_message", payload)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event].append(handler)
        logger.debug(f"EventBus: подписка на '{event}' — {handler.__qualname__}")

    def unsubscribe(self, event: str, handler: EventHandler) -> None:
        self._handlers[event] = [
            h for h in self._handlers[event] if h is not handler
        ]

    async def publish(self, event: str, payload: Any = None) -> None:
        handlers = self._handlers.get(event, [])
        if not handlers:
            return
        await asyncio.gather(
            *(h(payload) for h in handlers),
            return_exceptions=True,
        )


# Имена событий — константы, чтобы не опечататься
CHAT_MESSAGE = "chat_message"
STT_PHRASE = "stt_phrase"
VISION_FRAME = "vision_frame"
SNAPSHOT_READY = "snapshot_ready"
BOT_MESSAGE_SENT = "bot_message_sent"
