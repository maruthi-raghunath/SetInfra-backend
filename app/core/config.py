from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    LLM_MODEL: str = "gemini-3.1-pro"
    JWT_SECRET: str = "setinfra-dev-secret"
    DB_PATH: str = "./data/db/setinfra.db"
    UPLOAD_DIR: str = "./data/uploads"
    VECTOR_DIR: str = "./data/vector"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    USE_DUCKDB: bool = True
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173,https://set-infra-frontend.vercel.app"
    USE_LOCAL_EMBEDDING: bool = False

    class Config:
        env_file = ".env"

settings = Settings()


def gemini_api_key_preview() -> str:
    """Short masked form of GEMINI_API_KEY for logs/UI.

    The key is sent to Google only for HTTP authentication; it is not part of the
    model prompt (`contents`).
    """
    key = (settings.GEMINI_API_KEY or "").strip()
    if not key:
        return "(not configured)"
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:4]}…{key[-4:]}"
