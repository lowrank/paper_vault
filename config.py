"""Centralized configuration constants."""
from pathlib import Path

# API
BASE_API_URL = "https://api.alphaxiv.org"
ALPHAXIV_WEB_URL = "https://www.alphaxiv.org"
USER_AGENT = "alphaxiv-cli/1.0"

# Cache
DEFAULT_CACHE_DIR = ".cache/alphaxiv"
DEFAULT_CACHE_TTL_HOURS = 24

# HTTP
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 5
IMAGE_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
