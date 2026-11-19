from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

  llm_model: str
  capstone_domain: str = "wealthpilot"
  project_root: Path = PROJECT_ROOT
  llm_temperature: float = 0.0
  llm_timeout_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
  return Settings()