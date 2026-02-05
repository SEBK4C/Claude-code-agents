"""
Database connection and session management for the Telegram Trade Journal Bot.

This module provides async database engine configuration and session management
using SQLAlchemy 2.0 async patterns.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import get_config
from database.models import Base


# Module-level engine and session factory (lazy-initialized)
_engine: Optional[AsyncEngine] = None
_async_session: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """
    Get or create the async database engine.

    The engine is created lazily on first access and reused thereafter.

    Returns:
        AsyncEngine: The SQLAlchemy async engine instance.
    """
    global _engine
    if _engine is None:
        config = get_config()
        _engine = create_async_engine(
            config.database.url,
            echo=config.database.echo,
            # Pool configuration for SQLite
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get or create the async session factory.

    The session factory is created lazily on first access and reused thereafter.

    Returns:
        async_sessionmaker[AsyncSession]: The SQLAlchemy async session factory.
    """
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _async_session


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Provides a transactional scope for database operations. The session
    is automatically committed on successful completion and rolled back
    on exceptions.

    Yields:
        AsyncSession: An async database session.

    Example:
        async with get_session() as session:
            user = User(telegram_id=123456)
            session.add(user)
            # Commits automatically on context exit

    Raises:
        Exception: Re-raises any exception after rollback.
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """
    Initialize the database by creating all tables.

    This function creates all tables defined in the models module
    if they don't already exist. It's safe to call multiple times.

    Example:
        await init_db()
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    """
    Drop all database tables.

    WARNING: This will permanently delete all data in the database.
    Use with caution and only for testing or development purposes.

    Example:
        await drop_db()  # Drops all tables
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db() -> None:
    """
    Close the database engine and cleanup resources.

    This should be called during application shutdown to properly
    release database connections.

    Example:
        await close_db()
    """
    global _engine, _async_session
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session = None


def reset_db_state() -> None:
    """
    Reset the database state for testing purposes.

    This clears the module-level engine and session factory,
    allowing reconfiguration with different settings.
    """
    global _engine, _async_session
    _engine = None
    _async_session = None
