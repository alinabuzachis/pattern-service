from urllib.parse import urlparse

from pydantic import Field
from pydantic import field_validator
from pydantic_settings import BaseSettings


class AAPSettings(BaseSettings):
    url: str = Field("https://localhost:5000", env=["AAP_URL", "CONTROLLER_URL", "TOWER_URL"])
    username: str = Field("defaultuser", env=["AAP_USERNAME", "CONTROLLER_USERNAME", "TOWER_USERNAME"])
    password: str = Field("defaultpass", env=["AAP_PASSWORD", "CONTROLLER_PASSWORD", "TOWER_PASSWORD"])
    verify_ssl: bool = Field(False, env=["AAP_VALIDATE_CERTS", "CONTROLLER_VERIFY_SSL", "TOWER_VERIFY_SSL"])

    @field_validator("url", mode="before")
    @classmethod
    def ensure_scheme_and_validate(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"
        parsed = urlparse(v)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid controller host: {v!r}")
        return v.rstrip("/")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


AAP_SETTINGS = AAPSettings()
