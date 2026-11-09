"""
Async SQLAlchemy engine + репозиторий для работы с БД.
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings
from db.models import Base, BotMessageRecord, ChatMessageRecord, SpeechRecord, VisionRecord


# Создаём движок один раз
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Создаёт таблицы если не существуют. Вызывается при старте."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("База данных инициализирована")


class MessageRepository:
    """
    Репозиторий для сохранения всех типов данных.
    Используется несколькими модулями параллельно.
    """

    async def save_chat_message(self, username: str, text: str) -> None:
        async with AsyncSessionFactory() as session:
            session.add(ChatMessageRecord(username=username, text=text))
            await session.commit()

    async def save_speech(self, text: str) -> None:
        async with AsyncSessionFactory() as session:
            session.add(SpeechRecord(text=text))
            await session.commit()

    async def save_vision(self, game: str | None, event: str, description: str) -> None:
        async with AsyncSessionFactory() as session:
            session.add(VisionRecord(game=game, event=event, description=description))
            await session.commit()

    async def save_bot_message(
        self, bot_name: str, text: str, generation_sec: float | None = None
    ) -> None:
        async with AsyncSessionFactory() as session:
            session.add(
                BotMessageRecord(
                    bot_name=bot_name,
                    text=text,
                    generation_sec=generation_sec,
                )
            )
            await session.commit()

    async def get_recent_bot_messages(
        self, limit: int = 50
    ) -> list[BotMessageRecord]:
        from sqlalchemy import select, desc
        async with AsyncSessionFactory() as session:
            result = await session.execute(
                select(BotMessageRecord)
                .order_by(desc(BotMessageRecord.created_at))
                .limit(limit)
            )
            return list(result.scalars().all())
