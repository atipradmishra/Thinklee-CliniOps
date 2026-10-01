import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwtsecret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///thinkly.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # The ingestion worker writes from a background thread while requests are
    # being served. On SQLite a concurrent writer raises "database is locked"
    # immediately unless it is told to wait, so give it a busy timeout.
    # Harmless on other engines: only applied when the URI is SQLite.
    if SQLALCHEMY_DATABASE_URI.startswith("sqlite"):
        SQLALCHEMY_ENGINE_OPTIONS = {
            "connect_args": {"timeout": 30, "check_same_thread": False},
        }
    else:
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}