from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Twitch
    twitch_channel: str = Field(..., description="Канал для подключения")
    twitch_accounts_config_path: str = "config/twitch_accounts.json"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen3:14b"
    ollama_vision_model: str = "qwen2.5vl:7b"
    ollama_max_concurrent: int = 3

    # STT
    stt_model_size: str = "large-v3"
    stt_language: str = "ru"
    stt_device: str = "cuda"

    # Vision
    vision_frame_interval_sec: int = 10
    stream_url: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/twitch_bots"

    # Scheduler
    snapshot_interval_sec: int = 5
    bot_config_path: str = "config/bots.json"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
