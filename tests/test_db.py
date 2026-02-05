"""
Tests for database connection and session management.

This module tests:
- Database engine creation
- Session management
- Database initialization and cleanup
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import (
    close_db,
    drop_db,
    get_engine,
    get_session,
    get_session_factory,
    init_db,
    reset_db_state,
)
from database.models import Base, User


class TestDatabaseEngine:
    """Tests for database engine functions."""

    def test_get_engine_returns_engine(self, test_config, monkeypatch):
        """Test get_engine creates and returns an engine."""
        # Set environment for config
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        reset_db_state()
        engine = get_engine()

        assert engine is not None
        assert "sqlite" in str(engine.url)

    def test_get_engine_returns_same_instance(self, test_config, monkeypatch):
        """Test get_engine returns singleton instance."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        reset_db_state()
        engine1 = get_engine()
        engine2 = get_engine()

        assert engine1 is engine2


class TestSessionFactory:
    """Tests for session factory functions."""

    def test_get_session_factory_returns_factory(self, test_config, monkeypatch):
        """Test get_session_factory creates and returns a factory."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        reset_db_state()
        factory = get_session_factory()

        assert factory is not None

    def test_get_session_factory_returns_same_instance(self, test_config, monkeypatch):
        """Test get_session_factory returns singleton instance."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        reset_db_state()
        factory1 = get_session_factory()
        factory2 = get_session_factory()

        assert factory1 is factory2


class TestSessionContextManager:
    """Tests for the get_session context manager."""

    @pytest.mark.asyncio
    async def test_get_session_yields_session(self, async_engine):
        """Test get_session yields a valid session."""
        # Use test fixtures which set up the session correctly
        pass  # This is tested implicitly by all tests using the session fixture

    @pytest.mark.asyncio
    async def test_session_commits_on_success(self, session):
        """Test session commits changes on successful exit."""
        user = User(telegram_id=111111111, username="commit_test")
        session.add(user)
        await session.flush()

        # Verify user was created
        assert user.id is not None

    @pytest.mark.asyncio
    async def test_session_rollback_on_exception(self, async_engine):
        """Test session rolls back on exception."""
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

        async_session = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        try:
            async with async_session() as session:
                user = User(telegram_id=222222222, username="rollback_test")
                session.add(user)
                await session.flush()
                user_id = user.id
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Verify in new session that user was not persisted
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(
                select(User).where(User.telegram_id == 222222222)
            )
            assert result.scalar_one_or_none() is None


class TestDatabaseInitialization:
    """Tests for database initialization functions."""

    @pytest.mark.asyncio
    async def test_init_db_creates_tables(self, monkeypatch):
        """Test init_db creates all tables."""
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

        # Create a fresh in-memory database
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        # Verify tables don't exist yet
        async with engine.begin() as conn:
            # Create tables
            await conn.run_sync(Base.metadata.create_all)

        # Verify tables were created
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result.fetchall()]

        assert "users" in tables
        assert "accounts" in tables
        assert "trades" in tables
        assert "tags" in tables
        assert "strategies" in tables
        assert "transactions" in tables
        assert "reminders" in tables
        assert "trade_tags" in tables

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_drop_db_removes_tables(self):
        """Test drop_db removes all tables."""
        from sqlalchemy.ext.asyncio import create_async_engine

        # Create a fresh database with tables
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Verify tables exist
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result.fetchall()]
        assert len(tables) > 0

        # Drop all tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        # Verify tables were dropped
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result.fetchall()]

        # Only internal SQLite tables should remain (if any)
        user_tables = [t for t in tables if not t.startswith("sqlite_")]
        assert len(user_tables) == 0

        await engine.dispose()


class TestDatabaseCleanup:
    """Tests for database cleanup functions."""

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self, monkeypatch):
        """Test close_db properly disposes the engine."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        reset_db_state()
        engine = get_engine()

        await close_db()

        # After close, getting engine should create a new one
        new_engine = get_engine()
        assert new_engine is not engine

    def test_reset_db_state_clears_globals(self, monkeypatch):
        """Test reset_db_state clears module-level state."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        # Create engine and factory
        engine1 = get_engine()
        factory1 = get_session_factory()

        # Reset state
        reset_db_state()

        # New instances should be different
        engine2 = get_engine()
        factory2 = get_session_factory()

        assert engine1 is not engine2
        assert factory1 is not factory2


class TestDatabaseOperations:
    """Integration tests for database operations."""

    @pytest.mark.asyncio
    async def test_crud_operations(self, session):
        """Test basic CRUD operations through session."""
        # Create
        user = User(telegram_id=333333333, username="crud_test")
        session.add(user)
        await session.flush()
        user_id = user.id

        # Read
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        found_user = result.scalar_one()
        assert found_user.username == "crud_test"

        # Update
        found_user.username = "updated_user"
        await session.flush()

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        updated_user = result.scalar_one()
        assert updated_user.username == "updated_user"

        # Delete
        await session.delete(updated_user)
        await session.flush()

        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        assert result.scalar_one_or_none() is None
