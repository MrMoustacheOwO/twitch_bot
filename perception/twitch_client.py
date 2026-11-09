"""Twitch IRC клиент для одного аккаунта."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import twitchio
from twitchio.ext import commands
from loguru import logger

from core.event_bus import EventBus, CHAT_MESSAGE
from core.models import ChatMessage
from config.settings import settings


@dataclass(frozen=True)
class TwitchAccountConfig:
    name: str
    nick: str
    access_token: str
    client_id: str


class TwitchClient(commands.Bot):
    """Один TwitchIO-клиент: читает чат и отправляет сообщения тем же аккаунтом."""

    def __init__(self, account: TwitchAccountConfig, channel: str, bus: EventBus,
                 send_interval_sec: float = 1.5) -> None:
        super().__init__(
            token=account.access_token,
            client_id=account.client_id,
            nick=account.nick,
            prefix="!",
            initial_channels=[channel.lstrip("#")],
        )
        self.account = account
        self._bus = bus
        self._channel_name = channel.lstrip("#")
        self._channel: twitchio.Channel | None = None
        self._send_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._send_interval_sec = send_interval_sec
        self._worker_started = False

    async def event_ready(self) -> None:
        logger.info(
            f"Twitch подключён: аккаунт={self.account.nick!r}, "
            f"канал=#{self._channel_name}"
        )
        self._channel = self.get_channel(self._channel_name)
        if not self._worker_started:
            self._worker_started = True
            asyncio.create_task(self._send_worker(), name="twitch-send")

    async def event_message(self, message: twitchio.Message) -> None:
        if message.echo:
            return
        author = message.author.name if message.author else "unknown"
        await self._bus.publish(
            CHAT_MESSAGE,
            ChatMessage(username=author, text=message.content),
        )

    async def event_error(self, error: Exception, data: str | None = None) -> None:
        logger.error(f"Twitch ошибка: {error}")

    async def enqueue_message(self, bot_name: str, text: str) -> None:
        await self._send_queue.put((bot_name, text))

    async def _send_worker(self) -> None:
        while True:
            bot_name, text = await self._send_queue.get()
            try:
                if self._channel is None:
                    self._channel = self.get_channel(self._channel_name)
                if self._channel:
                    text = text[:500]
                    await self._channel.send(text)
                    logger.info(
                        f"Twitch[{self.account.nick}] сообщение от {bot_name!r}: {text[:80]!r}"
                    )
                else:
                    logger.warning("Twitch: канал не найден")
            except Exception as exc:
                logger.error(f"Twitch ошибка отправки: {exc}")
            finally:
                await asyncio.sleep(self._send_interval_sec)
                self._send_queue.task_done()

    async def send_message(self, bot_name: str, text: str) -> None:
        await self.enqueue_message(bot_name, text)

    async def start_async(self) -> None:
        await self.connect()


def load_account(path: str) -> TwitchAccountConfig:
    file = Path(path)
    if not file.exists():
        raise FileNotFoundError(f"Файл аккаунта не найден: {file}")
    with file.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list) or len(raw) != 1:
        raise ValueError("Для одноккаунтной версии twitch_accounts.json должен содержать ровно один аккаунт")
    account = TwitchAccountConfig(**raw[0])
    if not all((account.name, account.nick, account.access_token, account.client_id)):
        raise ValueError("Неполная конфигурация Twitch-аккаунта")
    return account


class TwitchSingleClient:
    """Обёртка, сохраняющая удобный интерфейс для остальной системы."""
    def __init__(self, bus: EventBus, accounts_config_path: str, channel: str) -> None:
        self._client = TwitchClient(load_account(accounts_config_path), channel, bus)

    async def send_message(self, account: str, bot_name: str, text: str) -> None:
        # account проверяется, чтобы конфигурационные ошибки не были скрыты.
        if account != self._client.account.name:
            raise ValueError(f"Ожидался аккаунт {self._client.account.name!r}, получен {account!r}")
        await self._client.send_message(bot_name, text)

    async def start_async(self) -> None:
        await self._client.start_async()
