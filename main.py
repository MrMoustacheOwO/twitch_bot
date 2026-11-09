"""
main.py — точка входа системы.

Поднимает все модули и запускает их конкурентно через asyncio.gather:
- TwitchClient  (получение/отправка сообщений)
- STTModule     (распознавание речи)
- VisionModule  (анализ видео)
- ContextBuilder (сборка снимков)
- BotScheduler  (диспетчер ботов)
- FastAPI       (HTTP API для управления)

Все тяжёлые вычисления (STT, Vision) — в единственном экземпляре.
До 100 ботов получают общий StreamSnapshot без дублирования.
"""
from __future__ import annotations

import asyncio
import signal
import sys

import uvicorn
from loguru import logger

from config.settings import settings
from core.event_bus import EventBus, BOT_MESSAGE_SENT
from core.context_builder import ContextBuilder
from core.models import ChatMessage
from db.database import init_db, MessageRepository
from perception.twitch_client import TwitchSingleClient
from perception.stt_module import STTModule
from perception.vision_module import VisionModule
from bots.bot_profile import BotFactory
from bots.llm_pool import LLMWorkerPool
from bots.scheduler import BotScheduler
from api.app import app as fastapi_app, set_scheduler, set_context_builder


def configure_logging() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        level="INFO",
    )
    logger.add(
        "logs/system.log",
        rotation="50 MB",
        retention="7 days",
        level="DEBUG",
        encoding="utf-8",
    )


async def main() -> None:
    configure_logging()
    logger.info("=== Twitch Virtual Viewer запускается ===")

    # --- Инициализация БД ---
    await init_db()
    repo = MessageRepository()

    # --- Шина событий (единственная на всю систему) ---
    bus = EventBus()

    # --- Модули восприятия ---
    twitch = TwitchSingleClient(
        bus=bus,
        accounts_config_path=settings.twitch_accounts_config_path,
        channel=settings.twitch_channel,
    )
    stt = STTModule(bus)
    vision = VisionModule(bus)

    # --- Context Builder ---
    context_builder = ContextBuilder(
        bus=bus,
        interval_sec=settings.snapshot_interval_sec,
    )
    context_builder.setup()

    # --- Боты (лёгкие агенты) ---
    bots = BotFactory.create_from_config(settings.bot_config_path)
    logger.info(f"Загружено {len(bots)} ботов")

    # --- LLM Pool ---
    llm_pool = LLMWorkerPool(max_concurrent=settings.ollama_max_concurrent)

    # --- Scheduler ---
    scheduler = BotScheduler(
        bots=bots,
        llm_pool=llm_pool,
        bus=bus,
        repo=repo,
        global_rate_limit=10,
        global_rate_window_sec=60,
    )
    scheduler.setup()

    # --- Подписка: отправлять сгенерированные сообщения в Twitch ---
    async def on_bot_message(payload: dict) -> None:
        await twitch.send_message(
            account=payload["account"],
            bot_name=payload["bot_name"],
            text=payload["text"],
        )
        await repo.save_bot_message(
            bot_name=payload["bot_name"],
            text=payload["text"],
        )

    bus.subscribe(BOT_MESSAGE_SENT, on_bot_message)

    # --- Подписка: сохранять сообщения чата в БД ---
    async def on_chat_for_db(msg: ChatMessage) -> None:
        await repo.save_chat_message(username=msg.username, text=msg.text)

    bus.subscribe("chat_message", on_chat_for_db)

    # --- FastAPI ---
    set_scheduler(scheduler)
    set_context_builder(context_builder)

    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    # --- Корректное завершение ---
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Получен сигнал завершения, останавливаюсь...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Запускаю все модули...")
    logger.info(f"API доступен: http://{settings.api_host}:{settings.api_port}/docs")

    # Запускаем все модули конкурентно
    tasks = [
        asyncio.create_task(twitch.start_async(), name="twitch"),
        asyncio.create_task(stt.run(), name="stt"),
        asyncio.create_task(vision.run(), name="vision"),
        asyncio.create_task(context_builder.run(), name="context"),
        asyncio.create_task(uvicorn_server.serve(), name="api"),
        asyncio.create_task(stop_event.wait(), name="stop-sentinel"),
    ]

    # Ждём пока один из модулей не завершится (или не придёт сигнал)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    for task in done:
        if task.get_name() != "stop-sentinel":
            exc = task.exception()
            if exc:
                logger.error(f"Задача {task.get_name()!r} завершилась с ошибкой: {exc}")

    # Останавливаем оставшиеся задачи
    logger.info("Завершаю работу...")
    context_builder.stop()
    stt.stop()
    vision.stop()
    uvicorn_server.should_exit = True

    await llm_pool.wait_all()

    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)

    logger.info("Система остановлена")


if __name__ == "__main__":
    import os
    os.makedirs("logs", exist_ok=True)
    asyncio.run(main())
