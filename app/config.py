from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str

    # JWT / Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Lockout policy
    MAX_LOGIN_ATTEMPTS: int = 3
    LOCKOUT_MINUTES: int = 1

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()
