"""
Application settings, read from environment variables (with .env fallback for local dev).

Only DATABASE_URL is consumed by this phase's code. The remaining fields are declared
now so later phases (auth, LLM/RAG, tracing) don't need to reshape this file - they
default to an empty string / None where no value exists yet.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Persistence (Phase 1)
    DATABASE_URL: str = "postgresql+asyncpg://pitcrew:pitcrew@localhost:5432/pitcrew"

    # Auth (Phase 2)
    JWT_SECRET: str = ""
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 14

    # LLM backend (later phases)
    LLM_BACKEND: str = "replay"
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Embeddings / reranking (RAG phase)
    EMBED_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Observability (later phase)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = ""

    # Test/replay fixtures for LLM calls (later phase)
    CASSETTE_DIR: str = ""


settings = Settings()
