"""Загрузка конфигурации из YAML-файла."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class TwitchConfig(BaseModel):
    channel: str
    bot_token: str
    client_id: str
    stream_url: str


class DatabaseConfig(BaseModel):
    url: str


class OllamaConfig(BaseModel):
    base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:14b"
    vision_model: str = "qwen2.5-vl:7b"
    max_concurrent: int = 3
    timeout_sec: int = 15


class STTConfig(BaseModel):
    model_size: str = "large-v3"
    language: str = "ru"
    device: str = "cuda"
    compute_type: str = "float16"
    chunk_duration_sec: int = 5
    min_phrase_len: int = 3


class VisionConfig(BaseModel):
    capture_interval_sec: int = 10
    frame_width: int = 1280
    frame_height: int = 720


class ContextConfig(BaseModel):
    chat_history_size: int = 100
    streamer_speech_size: int = 10
    snapshot_interval_sec: int = 5


class BotsConfig(BaseModel):
    profiles_path: str = "config/bots.json"
    global_rate_limit_per_min: int = 20


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "logs/bot.log"


class Settings(BaseModel):
    twitch: TwitchConfig
    database: DatabaseConfig
    ollama: OllamaConfig = OllamaConfig()
    stt: STTConfig = STTConfig()
    vision: VisionConfig = VisionConfig()
    context: ContextConfig = ContextConfig()
    bots: BotsConfig = BotsConfig()
    api: APIConfig = APIConfig()
    logging: LoggingConfig = LoggingConfig()


@lru_cache(maxsize=1)
def get_settings(config_path: str = "config/settings.yaml") -> Settings:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Файл настроек не найден: {path}\n"
            f"Скопируйте config/settings.example.yaml в config/settings.yaml и заполните."
        )
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return Settings(**data)
