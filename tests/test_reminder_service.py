"""
Tests for the Reminder Service.

Tests cover:
- Service initialization
- Scheduler start/stop
- Reminder scheduling
- Reminder message generation
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.reminder_service import (
    DEFAULT_REMINDERS,
    ReminderService,
    get_reminder_service,
    reset_reminder_service,
)


class TestReminderServiceInitialization:
    """Tests for ReminderService initialization."""

    def test_initializes_not_running(self):
        """Test service initializes in stopped state."""
        service = ReminderService()
        assert service.is_running is False

    def test_initializes_without_bot(self):
        """Test service can initialize without bot instance."""
        service = ReminderService()
        assert service._bot is None

    def test_initializes_with_bot(self):
        """Test service can initialize with bot instance."""
        mock_bot = MagicMock()
        service = ReminderService(bot=mock_bot)
        assert service._bot is mock_bot


class TestReminderServiceBotManagement:
    """Tests for bot instance management."""

    def test_set_bot(self):
        """Test setting bot instance after initialization."""
        service = ReminderService()
        mock_bot = MagicMock()
        service.set_bot(mock_bot)
        assert service._bot is mock_bot


class TestReminderServiceStartStop:
    """Tests for service start and stop."""

    @pytest.mark.asyncio
    async def test_start_creates_scheduler(self):
        """Test starting service creates scheduler."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()

        assert service._scheduler is not None
        assert service.is_running is True

        # Cleanup
        await service.stop()

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Test calling start twice does not create duplicate schedulers."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()
            scheduler1 = service._scheduler
            await service.start()  # Should log warning but not create new scheduler
            scheduler2 = service._scheduler

        assert scheduler1 is scheduler2

        # Cleanup
        await service.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_scheduler(self):
        """Test stopping service clears scheduler."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()
            await service.stop()

        assert service._scheduler is None
        assert service.is_running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Test stopping service when not running is safe."""
        service = ReminderService()
        await service.stop()  # Should not raise
        assert service.is_running is False


class TestDefaultReminders:
    """Tests for default reminder configuration."""

    def test_default_reminders_exist(self):
        """Test default reminders are defined."""
        assert len(DEFAULT_REMINDERS) > 0

    def test_default_reminders_have_required_fields(self):
        """Test each default reminder has required fields."""
        for reminder in DEFAULT_REMINDERS:
            assert "time_utc" in reminder
            assert "label" in reminder
            assert "type" in reminder
            assert isinstance(reminder["time_utc"], time)

    def test_morning_reminder_exists(self):
        """Test morning reminder is defined at 08:00."""
        morning = [r for r in DEFAULT_REMINDERS if r["type"] == "morning"]
        assert len(morning) == 1
        assert morning[0]["time_utc"] == time(8, 0)

    def test_session_reminder_exists(self):
        """Test session check reminder is defined at 10:00."""
        session = [r for r in DEFAULT_REMINDERS if r["type"] == "session"]
        assert len(session) == 1
        assert session[0]["time_utc"] == time(10, 0)

    def test_review_reminder_exists(self):
        """Test review reminder is defined at 15:00."""
        review = [r for r in DEFAULT_REMINDERS if r["type"] == "review"]
        assert len(review) == 1
        assert review[0]["time_utc"] == time(15, 0)


class TestReminderScheduling:
    """Tests for reminder scheduling functionality."""

    @pytest.mark.asyncio
    async def test_add_reminder_schedules_job(self):
        """Test adding a reminder creates a scheduled job."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()

        # Mock the database session
        mock_reminder = MagicMock()
        mock_reminder.id = 1
        mock_reminder.time_utc = time(9, 0)
        mock_reminder.enabled = True

        with patch('services.reminder_service.get_session') as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_reminder
            mock_session.execute = AsyncMock(return_value=mock_result)

            await service.add_reminder(1, 12345)

        # Check job was scheduled
        job = service._scheduler.get_job("reminder_1")
        assert job is not None

        # Cleanup
        await service.stop()

    @pytest.mark.asyncio
    async def test_remove_reminder_unschedules_job(self):
        """Test removing a reminder removes the scheduled job."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()

        # Manually add a job
        service._scheduler.add_job(
            lambda: None,
            'cron',
            hour=9,
            minute=0,
            id="reminder_1",
        )

        await service.remove_reminder(1)

        job = service._scheduler.get_job("reminder_1")
        assert job is None

        # Cleanup
        await service.stop()


class TestGetNextRunTime:
    """Tests for getting next run time."""

    @pytest.mark.asyncio
    async def test_get_next_run_time_scheduled(self):
        """Test getting next run time for scheduled reminder."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()

        # Add a job
        service._scheduler.add_job(
            lambda: None,
            'cron',
            hour=9,
            minute=0,
            id="reminder_1",
        )

        next_run = service.get_next_run_time(1)
        assert next_run is not None

        # Cleanup
        await service.stop()

    @pytest.mark.asyncio
    async def test_get_next_run_time_not_scheduled(self):
        """Test getting next run time for non-existent reminder."""
        service = ReminderService()

        with patch.object(service, '_load_reminders', new_callable=AsyncMock):
            await service.start()

        next_run = service.get_next_run_time(999)
        assert next_run is None

        # Cleanup
        await service.stop()


class TestSingletonPattern:
    """Tests for singleton pattern."""

    def test_get_reminder_service_returns_same_instance(self):
        """Test get_reminder_service returns singleton."""
        reset_reminder_service()

        service1 = get_reminder_service()
        service2 = get_reminder_service()

        assert service1 is service2

        reset_reminder_service()

    def test_reset_clears_singleton(self):
        """Test reset_reminder_service clears the singleton."""
        service1 = get_reminder_service()
        reset_reminder_service()
        service2 = get_reminder_service()

        assert service1 is not service2

        reset_reminder_service()
