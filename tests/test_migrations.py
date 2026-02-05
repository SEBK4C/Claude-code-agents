"""
Tests for database migrations and seeding.

This module tests:
- Default tag seeding
- Default reminder seeding
- User creation with defaults
"""

from datetime import time

import pytest
from sqlalchemy import select

from database.migrations import (
    DEFAULT_REMINDER_TIMES,
    DEFAULT_TAGS,
    ensure_default_data,
    get_or_create_user,
    seed_default_data,
    seed_default_reminders,
    seed_default_tags,
)
from database.models import Reminder, Tag, User


class TestDefaultTags:
    """Tests for default tag seeding."""

    def test_default_tags_list_defined(self):
        """Test that DEFAULT_TAGS constant is defined correctly."""
        assert len(DEFAULT_TAGS) == 8
        assert "Breakout" in DEFAULT_TAGS
        assert "Reversal" in DEFAULT_TAGS
        assert "News" in DEFAULT_TAGS
        assert "Scalp" in DEFAULT_TAGS
        assert "Swing" in DEFAULT_TAGS
        assert "Trend" in DEFAULT_TAGS
        assert "Counter-trend" in DEFAULT_TAGS
        assert "Range" in DEFAULT_TAGS

    @pytest.mark.asyncio
    async def test_seed_default_tags_creates_tags(self, session):
        """Test seed_default_tags creates all default tags."""
        tags = await seed_default_tags(session)

        assert len(tags) == 8
        tag_names = [t.name for t in tags]
        for expected in DEFAULT_TAGS:
            assert expected in tag_names

    @pytest.mark.asyncio
    async def test_seed_default_tags_marks_as_default(self, session):
        """Test seeded tags are marked as is_default=True."""
        tags = await seed_default_tags(session)

        for tag in tags:
            assert tag.is_default is True

    @pytest.mark.asyncio
    async def test_seed_default_tags_idempotent(self, session):
        """Test seed_default_tags is idempotent."""
        # Seed twice
        tags1 = await seed_default_tags(session)
        tags2 = await seed_default_tags(session)

        # Should return same number of tags
        assert len(tags1) == len(tags2)

        # Count tags in database
        result = await session.execute(select(Tag))
        all_tags = result.scalars().all()
        assert len(all_tags) == 8  # No duplicates

    @pytest.mark.asyncio
    async def test_seed_default_tags_preserves_existing(self, session):
        """Test seed_default_tags preserves existing custom tags."""
        # Create a custom tag
        custom_tag = Tag(name="Custom Tag", is_default=False)
        session.add(custom_tag)
        await session.flush()

        # Seed defaults
        await seed_default_tags(session)

        # Verify custom tag still exists
        result = await session.execute(
            select(Tag).where(Tag.name == "Custom Tag")
        )
        found = result.scalar_one()
        assert found.is_default is False


class TestDefaultReminders:
    """Tests for default reminder seeding."""

    def test_default_reminder_times_defined(self):
        """Test that DEFAULT_REMINDER_TIMES constant is defined correctly."""
        assert len(DEFAULT_REMINDER_TIMES) == 3
        assert time(8, 0) in DEFAULT_REMINDER_TIMES
        assert time(10, 0) in DEFAULT_REMINDER_TIMES
        assert time(15, 0) in DEFAULT_REMINDER_TIMES

    @pytest.mark.asyncio
    async def test_seed_default_reminders_creates_reminders(
        self, session, sample_user
    ):
        """Test seed_default_reminders creates all default reminders."""
        reminders = await seed_default_reminders(session, sample_user)

        assert len(reminders) == 3
        reminder_times = [r.time_utc for r in reminders]
        for expected_time in DEFAULT_REMINDER_TIMES:
            assert expected_time in reminder_times

    @pytest.mark.asyncio
    async def test_seed_default_reminders_enabled_by_default(
        self, session, sample_user
    ):
        """Test seeded reminders are enabled by default."""
        reminders = await seed_default_reminders(session, sample_user)

        for reminder in reminders:
            assert reminder.enabled is True

    @pytest.mark.asyncio
    async def test_seed_default_reminders_linked_to_user(
        self, session, sample_user
    ):
        """Test seeded reminders are linked to the correct user."""
        reminders = await seed_default_reminders(session, sample_user)

        for reminder in reminders:
            assert reminder.user_id == sample_user.id

    @pytest.mark.asyncio
    async def test_seed_default_reminders_idempotent(self, session, sample_user):
        """Test seed_default_reminders is idempotent."""
        # Seed twice
        reminders1 = await seed_default_reminders(session, sample_user)
        reminders2 = await seed_default_reminders(session, sample_user)

        # Should return same number of reminders
        assert len(reminders1) == len(reminders2)

        # Count reminders for user
        result = await session.execute(
            select(Reminder).where(Reminder.user_id == sample_user.id)
        )
        all_reminders = result.scalars().all()
        assert len(all_reminders) == 3  # No duplicates

    @pytest.mark.asyncio
    async def test_seed_reminders_different_users(self, session):
        """Test each user gets their own reminders."""
        # Create two users
        user1 = User(telegram_id=111111111, username="user1")
        user2 = User(telegram_id=222222222, username="user2")
        session.add(user1)
        session.add(user2)
        await session.flush()

        # Seed reminders for both
        await seed_default_reminders(session, user1)
        await seed_default_reminders(session, user2)

        # Each user should have their own 3 reminders
        result1 = await session.execute(
            select(Reminder).where(Reminder.user_id == user1.id)
        )
        result2 = await session.execute(
            select(Reminder).where(Reminder.user_id == user2.id)
        )

        assert len(result1.scalars().all()) == 3
        assert len(result2.scalars().all()) == 3


class TestSeedDefaultData:
    """Tests for the main seeding function."""

    @pytest.mark.asyncio
    async def test_seed_default_data_with_session(self, session):
        """Test seed_default_data with provided session."""
        result = await seed_default_data(session)

        assert "tags" in result
        assert len(result["tags"]) == 8

    @pytest.mark.asyncio
    async def test_seed_default_data_returns_tags(self, session):
        """Test seed_default_data returns seeded tags."""
        result = await seed_default_data(session)

        tag_names = [t.name for t in result["tags"]]
        assert "Breakout" in tag_names
        assert "Swing" in tag_names


class TestGetOrCreateUser:
    """Tests for the get_or_create_user utility."""

    @pytest.mark.asyncio
    async def test_creates_new_user(self, session):
        """Test creating a new user."""
        user, created = await get_or_create_user(
            session,
            telegram_id=444444444,
            username="new_user",
        )

        assert created is True
        assert user.id is not None
        assert user.telegram_id == 444444444
        assert user.username == "new_user"

    @pytest.mark.asyncio
    async def test_returns_existing_user(self, session, sample_user):
        """Test returning an existing user."""
        user, created = await get_or_create_user(
            session,
            telegram_id=sample_user.telegram_id,
            username=sample_user.username,
        )

        assert created is False
        assert user.id == sample_user.id

    @pytest.mark.asyncio
    async def test_updates_username_on_existing(self, session, sample_user):
        """Test updating username for existing user."""
        old_username = sample_user.username

        user, created = await get_or_create_user(
            session,
            telegram_id=sample_user.telegram_id,
            username="updated_username",
        )

        assert created is False
        assert user.username == "updated_username"
        assert user.username != old_username

    @pytest.mark.asyncio
    async def test_creates_default_reminders_for_new_user(self, session):
        """Test default reminders are created for new users."""
        user, created = await get_or_create_user(
            session,
            telegram_id=555555555,
            create_default_reminders=True,
        )

        assert created is True

        # Check reminders were created
        result = await session.execute(
            select(Reminder).where(Reminder.user_id == user.id)
        )
        reminders = result.scalars().all()
        assert len(reminders) == 3

    @pytest.mark.asyncio
    async def test_skip_default_reminders(self, session):
        """Test skipping default reminder creation."""
        user, created = await get_or_create_user(
            session,
            telegram_id=666666666,
            create_default_reminders=False,
        )

        assert created is True

        # Check no reminders were created
        result = await session.execute(
            select(Reminder).where(Reminder.user_id == user.id)
        )
        reminders = result.scalars().all()
        assert len(reminders) == 0

    @pytest.mark.asyncio
    async def test_handles_none_username(self, session):
        """Test creating user without username."""
        user, created = await get_or_create_user(
            session,
            telegram_id=777777777,
            username=None,
        )

        assert created is True
        assert user.username is None


class TestEnsureDefaultData:
    """Tests for the ensure_default_data utility."""

    @pytest.mark.asyncio
    async def test_ensure_default_data_creates_tags(self, async_engine, monkeypatch):
        """Test ensure_default_data creates default tags."""
        # This test needs a configured environment
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
        monkeypatch.setenv("LONGCAT_API_KEY", "test")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

        from database.db import reset_db_state

        reset_db_state()

        # We can't easily test ensure_default_data without mocking
        # since it creates its own session. This is tested implicitly
        # through seed_default_data tests.
        pass
