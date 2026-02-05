"""
Database migrations and seeding for the Telegram Trade Journal Bot.

This module provides functions for seeding default data into the database,
including default tags and reminder schedules.
"""

from datetime import time
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import get_engine, get_session
from database.models import Reminder, Tag, User


# Default tags for trade categorization
DEFAULT_TAGS = [
    "Breakout",
    "Reversal",
    "News",
    "Scalp",
    "Swing",
    "Trend",
    "Counter-trend",
    "Range",
]

# Default reminder times in UTC (HH:MM)
DEFAULT_REMINDER_TIMES = [
    time(8, 0),   # 08:00 UTC
    time(10, 0),  # 10:00 UTC
    time(15, 0),  # 15:00 UTC
]


async def seed_default_tags(session: AsyncSession) -> list[Tag]:
    """
    Seed default tags into the database.

    Creates default tags if they don't already exist. Tags are marked
    as defaults (is_default=True) to distinguish them from user-created tags.

    Args:
        session: The async database session to use.

    Returns:
        list[Tag]: A list of all default tags (existing or newly created).

    Example:
        async with get_session() as session:
            tags = await seed_default_tags(session)
    """
    created_tags = []

    for tag_name in DEFAULT_TAGS:
        # Check if tag already exists
        result = await session.execute(select(Tag).where(Tag.name == tag_name))
        existing_tag = result.scalar_one_or_none()

        if existing_tag is None:
            # Create new tag
            tag = Tag(name=tag_name, is_default=True)
            session.add(tag)
            created_tags.append(tag)
        else:
            created_tags.append(existing_tag)

    await session.flush()
    return created_tags


async def seed_default_reminders(
    session: AsyncSession, user: User
) -> list[Reminder]:
    """
    Seed default reminders for a specific user.

    Creates default reminders at 08:00, 10:00, and 15:00 UTC if they
    don't already exist for the user.

    Args:
        session: The async database session to use.
        user: The user to create reminders for.

    Returns:
        list[Reminder]: A list of all default reminders (existing or newly created).

    Example:
        async with get_session() as session:
            reminders = await seed_default_reminders(session, user)
    """
    created_reminders = []

    for reminder_time in DEFAULT_REMINDER_TIMES:
        # Check if reminder already exists for this user and time
        result = await session.execute(
            select(Reminder).where(
                Reminder.user_id == user.id,
                Reminder.time_utc == reminder_time,
            )
        )
        existing_reminder = result.scalar_one_or_none()

        if existing_reminder is None:
            # Create new reminder
            reminder = Reminder(
                user_id=user.id,
                time_utc=reminder_time,
                enabled=True,
            )
            session.add(reminder)
            created_reminders.append(reminder)
        else:
            created_reminders.append(existing_reminder)

    await session.flush()
    return created_reminders


async def seed_default_data(session: Optional[AsyncSession] = None) -> dict:
    """
    Seed all default data into the database.

    This is the main entry point for database seeding. It creates
    default tags. Note: Default reminders are created per-user when
    a new user is registered.

    Args:
        session: Optional async database session. If not provided,
                 a new session will be created.

    Returns:
        dict: A dictionary containing seeding results with keys:
            - 'tags': List of seeded Tag objects

    Example:
        # Using existing session
        async with get_session() as session:
            result = await seed_default_data(session)

        # Or create a new session
        result = await seed_default_data()
    """
    if session is None:
        async with get_session() as new_session:
            tags = await seed_default_tags(new_session)
            return {"tags": tags}
    else:
        tags = await seed_default_tags(session)
        return {"tags": tags}


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    create_default_reminders: bool = True,
) -> tuple[User, bool]:
    """
    Get an existing user or create a new one.

    This is a utility function for user registration that handles
    finding existing users by Telegram ID or creating new ones
    with default reminders.

    Args:
        session: The async database session to use.
        telegram_id: The Telegram user ID.
        username: Optional Telegram username.
        create_default_reminders: Whether to create default reminders
                                   for new users (default: True).

    Returns:
        tuple[User, bool]: A tuple of (user, created) where created
                          is True if a new user was created.

    Example:
        async with get_session() as session:
            user, created = await get_or_create_user(
                session, telegram_id=123456, username="johndoe"
            )
            if created:
                print("Welcome, new user!")
    """
    # Check if user exists
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        # Update username if changed
        if username is not None and existing_user.username != username:
            existing_user.username = username
        return existing_user, False

    # Create new user
    user = User(telegram_id=telegram_id, username=username)
    session.add(user)
    await session.flush()

    # Create default reminders for new user
    if create_default_reminders:
        await seed_default_reminders(session, user)

    return user, True


async def ensure_default_data() -> None:
    """
    Ensure all default data exists in the database.

    This is a convenience function to be called during application
    startup to make sure default tags are present.

    Example:
        # During app startup
        await init_db()
        await ensure_default_data()
    """
    async with get_session() as session:
        await seed_default_data(session)


async def migrate_add_snapshots() -> None:
    """
    Add data_snapshots table for rollback functionality.

    This migration creates the data_snapshots table if it doesn't exist,
    along with indexes for efficient querying by user_id and snapshot_date.

    The table stores point-in-time snapshots of user data that can be
    used to restore accounts, trades, and transactions to a previous state.

    Example:
        # During app startup or migration script
        await migrate_add_snapshots()
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # Create data_snapshots table
        await conn.execute(text('''
            CREATE TABLE IF NOT EXISTS data_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                snapshot_date DATE NOT NULL,
                snapshot_data TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        '''))

        # Create index on user_id for efficient user-based queries
        await conn.execute(text('''
            CREATE INDEX IF NOT EXISTS ix_data_snapshots_user_id
            ON data_snapshots(user_id)
        '''))

        # Create index on snapshot_date for date-based filtering
        await conn.execute(text('''
            CREATE INDEX IF NOT EXISTS ix_data_snapshots_snapshot_date
            ON data_snapshots(snapshot_date)
        '''))

        # Create composite index for user + date queries
        await conn.execute(text('''
            CREATE INDEX IF NOT EXISTS ix_data_snapshots_user_date
            ON data_snapshots(user_id, snapshot_date)
        '''))


async def run_all_migrations() -> None:
    """
    Run all database migrations.

    This function executes all migration functions in order.
    It's safe to call multiple times as each migration is idempotent.

    Example:
        # During app startup
        await run_all_migrations()
    """
    await migrate_add_snapshots()
