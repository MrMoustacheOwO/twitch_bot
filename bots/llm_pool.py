"""
Пул генерации сообщений через Ollama.
Теперь callback передаёт также account, чтобы сообщение ушло
через правильный Twitch-аккаунт.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Coroutine, Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config.settings import settings


SendCallback = Callable[[str, str, str], Coroutine[Any, Any, None]]


class LLMWorkerPool:
    def __init__(
        self,
        max_concurrent: int | None = None,
        on_message: SendCallback | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent or settings.ollama_max_concurrent
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._on_message = on_message
        self._active_tasks: set[asyncio.Task] = set()

        self._total_generated = 0
        self._total_errors = 0
        self._total_time_sec = 0.0

        logger.info(
            f"LLMWorkerPool: max_concurrent={self._max_concurrent}, "
            f"model={settings.ollama_llm_model!r}"
        )

    def set_callback(self, cb: SendCallback) -> None:
        self._on_message = cb

    async def submit(self, bot_name: str, account: str, prompt: str) -> None:
        task = asyncio.create_task(
            self._generate_and_send(bot_name, account, prompt),
            name=f"llm-{account}-{bot_name}",
        )
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    async def _generate_and_send(
        self, bot_name: str, account: str, prompt: str
    ) -> None:
        async with self._sem:
            start = time.monotonic()
            try:
                text = await self._call_ollama(prompt)
                elapsed = time.monotonic() - start
                self._total_generated += 1
                self._total_time_sec += elapsed

                logger.info(
                    f"[{account}/{bot_name}] сгенерировано за "
                    f"{elapsed:.1f}s: {text[:60]!r}..."
                )

                if self._on_message and text:
                    await self._on_message(account, bot_name, text)
            except Exception as e:
                self._total_errors += 1
                logger.error(
                    f"[{account}/{bot_name}] ошибка генерации: {e}"
                )

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_ollama(self, prompt: str) -> str:
        payload = {
            "model": settings.ollama_llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.85,
                "top_p": 0.9,
                "num_predict": 100,
                "stop": ["\n\n", "---"],
            },
        }

        async with httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(
                connect=5.0, read=30.0, write=5.0, pool=5.0
            ),
        ) as client:
            resp = await client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return data.get("response", "").strip().strip('"\'')[:300]

    @property
    def stats(self) -> dict:
        avg = (
            self._total_time_sec / self._total_generated
            if self._total_generated
            else 0.0
        )
        return {
            "total_generated": self._total_generated,
            "total_errors": self._total_errors,
            "avg_generation_sec": round(avg, 2),
            "active_tasks": len(self._active_tasks),
            "max_concurrent": self._max_concurrent,
        }

    async def wait_all(self) -> None:
        if self._active_tasks:
            await asyncio.gather(
                *list(self._active_tasks), return_exceptions=True
            )
