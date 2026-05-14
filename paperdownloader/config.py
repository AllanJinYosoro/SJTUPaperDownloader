from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8765
    headless: bool = True
    slow_mo_ms: int = 0
    task_timeout_ms: int = 180_000
    navigation_timeout_ms: int = 45_000
    title_match_threshold: float = 0.72

    browser_profile_dir: Path = Path(".browser-profile")
    download_dir: Path = Field(default_factory=lambda: Path.home() / "Downloads")

    jaccount_username: str | None = Field(default=None, alias="Jaccount_Username")
    jaccount_password: str | None = Field(default=None, alias="Jaccount_PWD")

    captcha_model_path: Path = Path("models/jaccount_resnet.onnx")
    captcha_charset: str = "abcdefghijklmnopqrstuvwxyz"
    captcha_width: int = 100
    captcha_height: int = 40
    captcha_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
