"""
Pytest configuration and fixtures for the Telegram Trade Journal Bot tests.

This module provides shared fixtures for testing, including:
- In-memory SQLite database setup
- Test configuration
- Common test data factories
"""

import os
from datetime import datetime, time
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import Config, DatabaseConfig, LoggingConfig, LongCatConfig, TelegramConfig, reset_config
from database.db import reset_db_state
from services.currency_service import reset_currency_service
from database.models import (
    Account,
    Base,
    Reminder,
    Strategy,
    Tag,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
    Transaction,
    TransactionType,
    User,
)


# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy for tests."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def test_config() -> Config:
    """
    Provide a test configuration with all required settings.

    Returns:
        Config: A configuration object suitable for testing.
    """
    return Config(
        database=DatabaseConfig(url=TEST_DATABASE_URL, echo=False),
        telegram=TelegramConfig(token="test_token_123"),
        longcat=LongCatConfig(api_key="test_api_key_456"),
        logging=LoggingConfig(level="DEBUG", format="console"),
    )


@pytest_asyncio.fixture
async def async_engine():
    """
    Create an async engine for testing with in-memory SQLite.

    Yields:
        AsyncEngine: A configured async engine for testing.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide an async session for testing.

    Creates a new session for each test and handles cleanup.

    Args:
        async_engine: The async engine fixture.

    Yields:
        AsyncSession: An async database session.
    """
    async_session = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def sample_user(session: AsyncSession) -> User:
    """
    Create a sample user for testing.

    Args:
        session: The async database session.

    Returns:
        User: A persisted User instance.
    """
    user = User(
        telegram_id=123456789,
        username="testuser",
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def sample_account(session: AsyncSession, sample_user: User) -> Account:
    """
    Create a sample account for testing.

    Args:
        session: The async database session.
        sample_user: The user fixture.

    Returns:
        Account: A persisted Account instance.
    """
    account = Account(
        user_id=sample_user.id,
        name="Test Account",
        broker="Test Broker",
        starting_balance=Decimal("10000.00"),
        current_balance=Decimal("10000.00"),
        currency="USD",
        is_active=True,
    )
    session.add(account)
    await session.flush()
    return account


@pytest_asyncio.fixture
async def sample_strategy(session: AsyncSession, sample_user: User) -> Strategy:
    """
    Create a sample strategy for testing.

    Args:
        session: The async database session.
        sample_user: The user fixture.

    Returns:
        Strategy: A persisted Strategy instance.
    """
    strategy = Strategy(
        user_id=sample_user.id,
        name="Test Strategy",
        description="A test trading strategy",
        rules={"entry": "breakout", "exit": "trailing_stop"},
    )
    session.add(strategy)
    await session.flush()
    return strategy


@pytest_asyncio.fixture
async def sample_tag(session: AsyncSession) -> Tag:
    """
    Create a sample tag for testing.

    Args:
        session: The async database session.

    Returns:
        Tag: A persisted Tag instance.
    """
    tag = Tag(name="Test Tag", is_default=False)
    session.add(tag)
    await session.flush()
    return tag


@pytest_asyncio.fixture
async def sample_trade(
    session: AsyncSession, sample_account: Account, sample_strategy: Strategy
) -> Trade:
    """
    Create a sample trade for testing.

    Args:
        session: The async database session.
        sample_account: The account fixture.
        sample_strategy: The strategy fixture.

    Returns:
        Trade: A persisted Trade instance.
    """
    trade = Trade(
        account_id=sample_account.id,
        instrument="EURUSD",
        direction=TradeDirection.LONG,
        entry_price=Decimal("1.10000"),
        lot_size=Decimal("0.10"),
        status=TradeStatus.OPEN,
        strategy_id=sample_strategy.id,
        notes="Test trade entry",
    )
    session.add(trade)
    await session.flush()
    return trade


@pytest_asyncio.fixture
async def sample_reminder(session: AsyncSession, sample_user: User) -> Reminder:
    """
    Create a sample reminder for testing.

    Args:
        session: The async database session.
        sample_user: The user fixture.

    Returns:
        Reminder: A persisted Reminder instance.
    """
    reminder = Reminder(
        user_id=sample_user.id,
        time_utc=time(8, 0),
        enabled=True,
    )
    session.add(reminder)
    await session.flush()
    return reminder


@pytest.fixture(autouse=True)
def reset_global_state():
    """
    Reset global state before each test.

    This ensures tests don't interfere with each other through
    module-level singletons.
    """
    reset_config()
    reset_db_state()
    reset_currency_service()
    yield
    reset_config()
    reset_db_state()
    reset_currency_service()
