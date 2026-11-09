"""
Модуль распознавания речи стримера.

Захватывает аудио с системного выхода (или RTMP потока),
сегментирует на фразы и публикует текст на шину событий.

Faster-Whisper работает в отдельном потоке (CPU/CUDA intensive),
результаты передаются в asyncio через run_in_executor.
"""
from __future__ import annotations

import asyncio
import io
import queue
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from loguru import logger

from core.event_bus import EventBus, STT_PHRASE
from config.settings import settings


# Параметры захвата аудио
SAMPLE_RATE = 16000       # Whisper работает с 16kHz
CHUNK_DURATION = 0.5      # Секунд в одном чанке
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION)
SILENCE_THRESHOLD = 0.01  # RMS ниже этого = тишина
MIN_PHRASE_SEC = 1.0      # Минимальная длина фразы для распознавания
MAX_PHRASE_SEC = 30.0     # Максимальная длина буфера до принудительной отправки


class STTModule:
    """
    Модуль распознавания речи.

    Архитектура:
    - Поток sounddevice записывает аудио → сырая очередь
    - Поток-агрегатор собирает чанки в фразы по паузам
    - Asyncio-воркер вызывает Whisper через executor и публикует результат
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._model: Optional[WhisperModel] = None
        self._raw_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._phrase_queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=50)
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _load_model(self) -> None:
        logger.info(
            f"Загрузка Faster-Whisper: size={settings.stt_model_size!r} "
            f"device={settings.stt_device!r}"
        )
        self._model = WhisperModel(
            settings.stt_model_size,
            device=settings.stt_device,
            compute_type="float16" if settings.stt_device == "cuda" else "int8",
        )
        logger.info("Faster-Whisper загружен")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        """Вызывается sounddevice в реальном времени."""
        if status:
            logger.warning(f"STT audio status: {status}")
        chunk = indata[:, 0].copy()  # моно
        try:
            self._raw_queue.put_nowait(chunk)
        except queue.Full:
            pass  # Потеря чанка лучше чем зависание

    def _aggregator_thread(self) -> None:
        """
        Собирает аудио-чанки в фразы.
        Фраза заканчивается когда наступает тишина (>= 0.8s).
        Запускается в отдельном daemon-потоке.
        """
        buffer: list[np.ndarray] = []
        silence_chunks = 0
        SILENCE_LIMIT = int(0.8 / CHUNK_DURATION)  # 0.8s тишины = конец фразы

        while self._running:
            try:
                chunk = self._raw_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))
            is_silent = rms < SILENCE_THRESHOLD

            if is_silent:
                silence_chunks += 1
                if buffer:
                    buffer.append(chunk)
            else:
                silence_chunks = 0
                buffer.append(chunk)

            # Конец фразы: достаточно тишины И есть накопленное аудио
            buffer_sec = len(buffer) * CHUNK_DURATION
            end_by_silence = silence_chunks >= SILENCE_LIMIT and buffer_sec >= MIN_PHRASE_SEC
            end_by_length = buffer_sec >= MAX_PHRASE_SEC

            if (end_by_silence or end_by_length) and buffer:
                phrase_audio = np.concatenate(buffer)
                buffer = []
                silence_chunks = 0
                # Передаём в asyncio-цикл
                if self._loop and not self._loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self._phrase_queue.put(phrase_audio),
                        self._loop,
                    )

    async def _transcribe_worker(self) -> None:
        """Asyncio-воркер: берёт аудио из очереди, вызывает Whisper, публикует текст."""
        loop = asyncio.get_running_loop()
        while self._running:
            audio = await self._phrase_queue.get()
            try:
                # Whisper — блокирующий вызов, запускаем в executor
                text = await loop.run_in_executor(None, self._transcribe, audio)
                if text:
                    logger.debug(f"STT: {text!r}")
                    await self._bus.publish(STT_PHRASE, text)
            except Exception as e:
                logger.error(f"Ошибка транскрипции: {e}")
            finally:
                self._phrase_queue.task_done()

    def _transcribe(self, audio: np.ndarray) -> str:
        """Синхронный вызов Whisper (выполняется в executor)."""
        if self._model is None:
            return ""
        segments, _info = self._model.transcribe(
            audio,
            language=settings.stt_language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

    async def run(self) -> None:
        """Основной метод запуска. Блокирует до остановки."""
        self._loop = asyncio.get_running_loop()
        self._running = True

        # Загружаем модель в executor чтобы не блокировать event loop
        await asyncio.get_running_loop().run_in_executor(None, self._load_model)

        # Запускаем поток агрегации
        agg_thread = threading.Thread(
            target=self._aggregator_thread, daemon=True, name="stt-aggregator"
        )
        agg_thread.start()

        # Открываем микрофон / системный аудио
        logger.info("STT: открываем аудиопоток...")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_SIZE,
            callback=self._audio_callback,
        ):
            logger.info("STT модуль активен, слушаю аудио")
            await self._transcribe_worker()

    def stop(self) -> None:
        self._running = False
