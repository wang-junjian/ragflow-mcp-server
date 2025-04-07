from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ragflow_api_key: str = ""
    ragflow_base_url: str = "http://localhost:9380"

    class Config:
        env_prefix = "RAGFLOW_"

settings = Settings()