from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    port: int = Field(default=8765, ge=1024, le=65535)
    headless: bool = False
    task_timeout_ms: int = Field(default=600_000, ge=1000)
    navigation_timeout_ms: int = Field(default=45_000, ge=1000)
    title_match_threshold: float = Field(default=0.94, ge=0.85, le=1)
    browser_profile_dir: Path = Path(".browser-profile")
    download_dir: Path = Path("downloads")
    jaccount_username: SecretStr | None = Field(default=None, validation_alias="JACCOUNT_USERNAME")
    jaccount_password: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("JACCOUNT_PASSWORD", "Jaccount_PWD"))
    captcha_model_path: Path = Path(".state/nn_model.onnx")


@lru_cache
def get_settings() -> Settings:
    return Settings()
