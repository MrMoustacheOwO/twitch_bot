"""
FastAPI-приложение для управления системой и мониторинга.

Эндпоинты:
- GET  /health          — статус системы
- GET  /stats           — статистика (боты, LLM, снимки)
- GET  /bots            — список ботов и их активность
- POST /bots/{name}/trigger — принудительно триггернуть бота
- GET  /messages        — последние сообщения ботов из БД
- POST /stream/snapshot — ручной снимок (для тестирования)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from pydantic import BaseModel

from db.database import MessageRepository

if TYPE_CHECKING:
    from bots.scheduler import BotScheduler
    from core.context_builder import ContextBuilder


app = FastAPI(
    title="Twitch Virtual Viewer",
    description="Система интеллектуальных виртуальных зрителей Twitch",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные ссылки на компоненты системы (устанавливаются при старте)
_scheduler: "BotScheduler | None" = None
_context_builder: "ContextBuilder | None" = None
_repo: MessageRepository = MessageRepository()


def set_scheduler(scheduler: "BotScheduler") -> None:
    global _scheduler
    _scheduler = scheduler


def set_context_builder(cb: "ContextBuilder") -> None:
    global _context_builder
    _context_builder = cb


# --- Pydantic-схемы ---

class HealthResponse(BaseModel):
    status: str
    bots_loaded: int


class ManualSnapshotRequest(BaseModel):
    screen_description: str = ""
    current_game: str = ""
    streamer_speech: list[str] = []


# --- Эндпоинты ---

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    bots = len(_scheduler._bots) if _scheduler else 0
    return HealthResponse(status="ok", bots_loaded=bots)


@app.get("/stats")
async def stats() -> dict:
    if not _scheduler:
        raise HTTPException(503, "Система ещё не инициализирована")
    return _scheduler.stats


@app.get("/bots")
async def list_bots() -> list[dict]:
    if not _scheduler:
        raise HTTPException(503, "Система ещё не инициализирована")
    return [bot.stats() for bot in _scheduler._bots]


@app.post("/bots/{bot_name}/reset-cooldown")
async def reset_bot_cooldown(bot_name: str) -> dict:
    """Сбрасывает cooldown конкретного бота."""
    if not _scheduler:
        raise HTTPException(503, "Система ещё не инициализирована")
    for bot in _scheduler._bots:
        if bot.name == bot_name:
            bot._last_sent_at = 0.0
            logger.info(f"Cooldown сброшен для бота {bot_name!r}")
            return {"ok": True, "bot": bot_name}
    raise HTTPException(404, f"Бот {bot_name!r} не найден")


@app.get("/messages")
async def recent_messages(limit: int = 20) -> list[dict]:
    """Последние сообщения ботов из базы данных."""
    records = await _repo.get_recent_bot_messages(limit=min(limit, 100))
    return [
        {
            "id": r.id,
            "bot_name": r.bot_name,
            "text": r.text,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]


@app.post("/stream/snapshot")
async def manual_snapshot(req: ManualSnapshotRequest) -> dict:
    """
    Принудительно создаёт снимок и отправляет всем ботам.
    Полезно для тестирования без реального потока.
    """
    from core.models import StreamSnapshot, ScreenEvent
    from core.event_bus import SNAPSHOT_READY

    if not _context_builder:
        raise HTTPException(503, "ContextBuilder не инициализирован")

    snapshot = StreamSnapshot(
        screen_description=req.screen_description,
        current_game=req.current_game or "тест",
        streamer_speech=req.streamer_speech,
        screen_event=ScreenEvent.UNKNOWN,
    )
    from core.event_bus import EventBus
    # Публикуем снимок напрямую через шину
    await _context_builder._bus.publish(SNAPSHOT_READY, snapshot)
    return {"ok": True, "snapshot_game": snapshot.current_game}
