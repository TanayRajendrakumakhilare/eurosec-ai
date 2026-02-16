from pydantic import BaseModel
import os

class Settings(BaseModel):
    # IPC
    host: str = os.getenv("EUROSEC_HOST", "127.0.0.1")
    port: int = int(os.getenv("EUROSEC_PORT", "48155"))

    # Cloud control (must be explicit user consent from GUI)
    cloud_enabled_default: bool = os.getenv("EUROSEC_CLOUD_DEFAULT", "false").lower() == "true"

    # OpenAI
    openai_api_key: str | None = os.getenv("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")
    openai_model: str = os.getenv("EUROSEC_OPENAI_MODEL", "gpt-3.5")  # allowed: gpt-3.5 or newer

    # GDPR logging
    log_level: str = os.getenv("EUROSEC_LOG_LEVEL", "INFO")

settings = Settings()
