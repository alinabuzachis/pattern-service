import os
from urllib.parse import urlparse

from dynaconf import Dynaconf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load from dev and PATTERN_SERVICE_* env variables
_settings = Dynaconf(
    settings_files=[
        os.path.join(BASE_DIR, "defaults_development.py"),
        os.path.join(BASE_DIR, "testing_defaults.py"),
    ],
    envvar_prefix="PATTERN_SERVICE",
    envvar_cast=True,
    load_dotenv=True,
)


def _validate_url(url: str) -> str:
    """Ensure the URL has a valid scheme and format."""
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")
    return url.rstrip("/")


# Exposed config values
AAP_URL = _validate_url(_settings.AAP_URL)
AAP_VALIDATE_CERTS = _settings.AAP_VALIDATE_CERTS
AAP_USERNAME = _settings.AAP_USERNAME
AAP_PASSWORD = _settings.AAP_PASSWORD
