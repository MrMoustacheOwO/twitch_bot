"""
Модуль анализа видеопотока трансляции.

Периодически захватывает кадр из RTMP-потока через FFmpeg/OpenCV,
отправляет в Qwen2.5-VL через Ollama и публикует описание на шину.

Один экземпляр на всю систему — все боты получают одно описание.
"""
from __future__ import annotations

import asyncio
import base64
import io
import subprocess
import time
from typing import Optional

import cv2
import httpx
import numpy as np
from loguru import logger

from core.event_bus import EventBus, VISION_FRAME
from core.models import ScreenEvent
from config.settings import settings


# Промпт для VL-модели: получаем структурированный ответ
VISION_SYSTEM_PROMPT = """Ты анализируешь скриншоты из видеоигр.
Ответь в формате:
ИГРА: <название или 'неизвестно'>
СОБЫТИЕ: <одно из: fight, victory, defeat, menu, dialogue, exploration, cutscene, unknown>
ОПИСАНИЕ: <одно предложение что происходит на экране>

Отвечай только в этом формате, без лишних слов."""


def _parse_vision_response(text: str) -> dict:
    """Парсит структурированный ответ VL-модели."""
    result = {
        "description": "",
        "event": ScreenEvent.UNKNOWN,
        "game": None,
    }
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("ИГРА:"):
            game = line[5:].strip()
            if game.lower() not in ("неизвестно", "unknown", ""):
                result["game"] = game
        elif line.startswith("СОБЫТИЕ:"):
            event_str = line[8:].strip().lower()
            try:
                result["event"] = ScreenEvent(event_str)
            except ValueError:
                result["event"] = ScreenEvent.UNKNOWN
        elif line.startswith("ОПИСАНИЕ:"):
            result["description"] = line[9:].strip()
    return result


class VisionModule:
    """
    Захватывает кадры и анализирует их через Qwen2.5-VL.

    Каждые `frame_interval_sec` секунд:
    1. Захватывает кадр из потока
    2. Отправляет в Ollama (vision)
    3. Публикует результат на EventBus
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._interval = settings.vision_frame_interval_sec
        self._stream_url = settings.stream_url
        self._ollama_url = settings.ollama_base_url
        self._model = settings.ollama_vision_model
        self._running = False

        # Кеш последнего кадра (между захватами)
        self._last_frame: Optional[np.ndarray] = None
        self._cap: Optional[cv2.VideoCapture] = None

    def _open_capture(self) -> cv2.VideoCapture:
        """Открывает видеопоток через OpenCV/FFmpeg."""
        if self._stream_url:
            logger.info(f"Vision: открываю поток {self._stream_url!r}")
            cap = cv2.VideoCapture(self._stream_url, cv2.CAP_FFMPEG)
        else:
            # Fallback: захват экрана через виртуальное устройство
            logger.info("Vision: URL потока не задан, захват экрана (устройство 0)")
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("Не удалось открыть видеопоток")
        return cap

    def _capture_frame(self) -> Optional[np.ndarray]:
        """Захватывает один кадр из потока."""
        if self._cap is None or not self._cap.isOpened():
            try:
                self._cap = self._open_capture()
            except RuntimeError as e:
                logger.error(f"Vision: {e}")
                return None

        ret, frame = self._cap.read()
        if not ret:
            logger.warning("Vision: не удалось прочитать кадр, переподключаюсь...")
            self._cap.release()
            self._cap = None
            return None

        # Масштабируем до 1280x720 для оптимальной скорости VL
        frame = cv2.resize(frame, (1280, 720))
        return frame

    def _frame_to_base64(self, frame: np.ndarray) -> str:
        """Конвертирует кадр OpenCV в base64 JPEG."""
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buf.tobytes()).decode("utf-8")

    async def _analyze_frame(self, frame: np.ndarray) -> dict:
        """Отправляет кадр в Ollama и возвращает разобранный результат."""
        image_b64 = await asyncio.get_running_loop().run_in_executor(
            None, self._frame_to_base64, frame
        )

        payload = {
            "model": self._model,
            "prompt": "Проанализируй этот скриншот игры.",
            "system": VISION_SYSTEM_PROMPT,
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 150},
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._ollama_url}/api/generate", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "")

        result = _parse_vision_response(raw_text)
        logger.debug(
            f"Vision: event={result['event'].value!r} "
            f"desc={result['description'][:50]!r}"
        )
        return result

    async def run(self) -> None:
        """Основной цикл захвата и анализа кадров."""
        self._running = True
        logger.info(f"VisionModule запущен, интервал={self._interval}s")

        while self._running:
            start = time.monotonic()

            # Захват кадра (блокирующий — в executor)
            frame = await asyncio.get_running_loop().run_in_executor(
                None, self._capture_frame
            )

            if frame is not None:
                try:
                    result = await self._analyze_frame(frame)
                    await self._bus.publish(VISION_FRAME, result)
                except httpx.HTTPError as e:
                    logger.error(f"Vision HTTP ошибка: {e}")
                except Exception as e:
                    logger.error(f"Vision ошибка анализа: {e}")
            else:
                # Нет кадра — публикуем пустой результат чтобы не блокировать ботов
                await self._bus.publish(VISION_FRAME, {
                    "description": "видео недоступно",
                    "event": ScreenEvent.UNKNOWN,
                })

            # Ждём до следующего цикла
            elapsed = time.monotonic() - start
            wait = max(0, self._interval - elapsed)
            await asyncio.sleep(wait)

        if self._cap:
            self._cap.release()

    def stop(self) -> None:
        self._running = False
