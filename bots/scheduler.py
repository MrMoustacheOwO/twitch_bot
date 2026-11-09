"""
Оркестратор виртуальных зрителей.
Каждый BotProfile привязан к конкретному Twitch account.
"""
from __future__ import annotations

import time
from collections import deque

from loguru import logger

from bots.bot import Bot
from bots.llm_pool import LLMWorkerPool
from core.event_bus import EventBus, SNAPSHOT_READY, BOT_MESSAGE_SENT
from core.models import StreamSnapshot
from db.repository import MessageRepository


class BotScheduler:
    def __init__(
        self,
        bots: list[Bot],
        llm_pool: LLMWorkerPool,
        bus: EventBus,
        repo: MessageRepository,
        global_rate_limit: int = 20,
        global_rate_window_sec: int = 60,
    ) -> None:
        self._bots = bots
        self._llm_pool = llm_pool
        self._bus = bus
        self._repo = repo
        self._rate_limit = global_rate_limit
        self._rate_window = global_rate_window_sec
        self._send_timestamps: deque[float] = deque()
        self._snapshot_count = 0
        self._triggered_count = 0

        logger.info(
            f"BotScheduler: {len(bots)} ботов, "
            f"rate_limit={global_rate_limit}/{global_rate_window_sec}s"
        )

    def setup(self) -> None:
        self._bus.subscribe(SNAPSHOT_READY, self._on_snapshot)
        self._llm_pool.set_callback(self._on_message_generated)

    async def _on_snapshot(self, snapshot: StreamSnapshot) -> None:
        self._snapshot_count += 1

        candidates = [
            bot for bot in self._bots if bot.should_trigger(snapshot)
        ]
        if not candidates:
            return

        now = time.monotonic()
        while (
            self._send_timestamps
            and now - self._send_timestamps[0] > self._rate_window
        ):
            self._send_timestamps.popleft()

        available_slots = self._rate_limit - len(self._send_timestamps)
        if available_slots <= 0:
            return

        # Берём случайное подмножество, чтобы первые боты из JSON
        # не получали постоянного преимущества.
        candidates = candidates[:]
        import random
        random.shuffle(candidates)
        selected = candidates[:available_slots]

        for bot in selected:
            prompt = bot.build_prompt(snapshot)
            self._send_timestamps.append(time.monotonic())
            self._triggered_count += 1
            logger.debug(
                f"Триггер: {bot.name!r} -> account={bot.account!r}"
            )
            await self._llm_pool.submit(
                bot.name, bot.account, prompt
            )
            bot.on_message_sent()

    async def _on_message_generated(
        self, account: str, bot_name: str, text: str
    ) -> None:
        await self._bus.publish(
            BOT_MESSAGE_SENT,
            {
                "account": account,
                "bot_name": bot_name,
                "text": text,
            },
        )
        await self._repo.save_bot_message(
            bot_name=bot_name,
            text=text,
        )

    @property
    def stats(self) -> dict:
        return {
            "bots_total": len(self._bots),
            "accounts_used": len({bot.account for bot in self._bots}),
            "snapshots_processed": self._snapshot_count,
            "total_triggered": self._triggered_count,
            "llm_pool": self._llm_pool.stats,
            "bot_stats": [bot.stats() for bot in self._bots],
        }
