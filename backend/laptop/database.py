import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from typing import Generator

logger = logging.getLogger(__name__)

# Base registry — all models import this and register themselves
Base = declarative_base()


def _make_engine(database_url: str):
    """Create the SQLAlchemy engine with sensible pool settings."""
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )


def _get_settings():
    """Lazy import to avoid circular imports at module load time."""
    from laptop.config import settings
    return settings


# Engine and session factory — built once on first use
_engine = None
_SessionLocal = None


def _ensure_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = _get_settings()
        _engine = _make_engine(settings.DATABASE_URL)
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_engine,
        )


def get_engine():
    _ensure_engine()
    return _engine


# Expose SessionLocal as a module-level name for imports
class _SessionProxy:
    """Proxy so `from database import SessionLocal` works before engine init."""
    def __call__(self, *args, **kwargs):
        _ensure_engine()
        return _SessionLocal(*args, **kwargs)

    def __getattr__(self, name):
        _ensure_engine()
        return getattr(_SessionLocal, name)


SessionLocal = _SessionProxy()


def get_db() -> Generator:
    """
    FastAPI dependency — yields a database session and ensures it is
    closed after the request completes, even on errors.
    """
    _ensure_engine()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Create all tables defined on Base.
    Imports models so they register themselves before create_all runs.
    Idempotent — safe to call multiple times.
    """
    _ensure_engine()

    # Import models to register them with Base before create_all
    import laptop.models  # noqa: F401

    try:
        Base.metadata.create_all(bind=_engine)
        logger.info("Database tables created (or already exist).")
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc)
        raise
