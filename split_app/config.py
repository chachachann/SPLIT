from datetime import timedelta


class Config:
    SECRET_KEY = "supersecretkey"
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    REMEMBER_COOKIE_NAME = "split_remember"
    HOST = "0.0.0.0"
    PORT = 777
    DEBUG = True
