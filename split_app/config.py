import os
import secrets
from datetime import timedelta


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.environ.get("SPLIT_SECRET_KEY") or secrets.token_hex(32)
    PERMANENT_SESSION_LIFETIME = timedelta(days=_env_int("SPLIT_SESSION_LIFETIME_DAYS", 7))
    MAX_CONTENT_LENGTH = _env_int("SPLIT_MAX_CONTENT_LENGTH", 50 * 1024 * 1024)
    REMEMBER_COOKIE_NAME = os.environ.get("SPLIT_REMEMBER_COOKIE_NAME", "split_remember")
    REMEMBER_ME_DAYS = _env_int("SPLIT_REMEMBER_DAYS", 7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SPLIT_SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = _env_bool("SPLIT_SESSION_COOKIE_SECURE", False)
    HOST = os.environ.get("SPLIT_HOST", "0.0.0.0")
    PORT = _env_int("SPLIT_PORT", 777)
    DEBUG = _env_bool("SPLIT_DEBUG", False)
