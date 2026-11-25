from dotenv import load_dotenv
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
  model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

  llm_model: str
  embedding_model: str  # required: set EMBEDDING_MODEL in .env
  capstone_domain: str = "wealthpilot"
  project_root: Path = PROJECT_ROOT
  llm_temperature: float = 0.0
  llm_timeout_seconds: int = 60
  max_repair_attempts: int = 3	
  llm_max_retries: int = 5
  max_agent_steps: int = 8  # hard cap on model calls per agent run
  max_approval_attempts: int = 3  # rejected human decisions before a case is escalated as unresolved
  max_committee_rounds: int = 3  # analyst/reviewer revision rounds before the committee gives up
  tracing_enabled: bool = True
  retry_max_attempts: int = 3  # tries per dependency call (first try included)
  retry_base_delay_seconds: float = 0.5
  retry_max_delay_seconds: float = 4.0
  breaker_failure_threshold: int = 3  # failed calls (after retries) before a circuit opens
  breaker_reset_seconds: float = 30.0  # cool-down before one trial call is allowed
  bureau_cache_max_age_hours: float = 72.0  # a cached bureau report older than this is not used
  working_memory_budget_tokens: int = 3000  # conversation context allowed before old turns are trimmed
  working_memory_min_turns: int = 4  # never trim below this many most-recent messages
  qdrant_collection: str = "policy_docs"
  chunk_max_chars: int = 1800  # sections longer than this are split on paragraph breaks
  embedding_batch_size: int = 16
  embedding_requests_per_minute: int = 80  # free tier allows 100 texts a minute; stay under it
  embedding_retry_wait_seconds: float = 45.0  # wait after a rate-limit error before retrying
  embedding_rate_limit_retries: int = 3
  retrieval_top_k: int = 5  # chunks passed on to the answerer / scored
  retrieval_candidates: int = 20  # chunks fetched from each retriever before fusion
  rrf_k: int = 60  # reciprocal-rank-fusion constant
  rerank_candidates: int = 10  # fused candidates sent to the reranker
  rerank_min_score: float = 4.0  # below this top score the answerer abstains (0-10 scale)
  eval_delay_seconds: float = 5.0  # pause between records when scoring (free-tier rate limits)

@lru_cache
def get_settings() -> Settings:
  load_dotenv(PROJECT_ROOT / ".env")
  return Settings()