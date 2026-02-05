"""
Reminder Service for the Telegram Trade Journal Bot.

This module provides:
- Scheduled reminder delivery using APScheduler
- Morning prep, session check, and US session review reminders
- Dynamic schedule management from database
"""

import asyncio
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from config import get_config, get_logger
from database.db import get_session
from database.models import Account, Reminder, Trade, TradeStatus, User

logger = get_logger(__name__)

# Default reminder configurations
DEFAULT_REMINDERS = [
    {
        "time_utc": time(8, 0),  # 08:00 UTC
        "label": "Morning Prep",
        "type": "morning",
    },
    {
        "time_utc": time(10, 0),  # 10:00 UTC
        "label": "Session Check",
        "type": "session",
    },
    {
        "time_utc": time(15, 0),  # 15:00 UTC
        "label": "US Session Review",
        "type": "review",
    },
]


class ReminderService:
    """
    Service class for managing and delivering scheduled reminders.

    Provides methods to:
    - Start and stop the scheduler
    - Load reminders from database
    - Send reminder messages
    - Update schedule dynamically
    """

    def __init__(self, bot: Optional[Bot] = None) -> None:
        """
        Initialize the reminder service.

        Args:
            bot: Optional Telegram Bot instance for sending messages.
        """
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._bot: Optional[Bot] = bot
        self._running: bool = False
        logger.info("ReminderService initialized")

    @property
    def is_running(self) -> bool:
        """Check if the scheduler is running."""
        return self._running and self._scheduler is not None

    def set_bot(self, bot: Bot) -> None:
        """
        Set the Telegram bot instance.

        Args:
            bot: The Telegram Bot instance.
        """
        self._bot = bot
        logger.info("Bot instance set for ReminderService")

    async def start(self) -> None:
        """
        Start the reminder scheduler.

        Loads all enabled reminders from the database and schedules them.
        """
        if self._running:
            logger.warning("ReminderService already running")
            return

        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # Load reminders from database
        await self._load_reminders()

        self._scheduler.start()
        self._running = True
        logger.info("ReminderService started")

    async def stop(self) -> None:
        """
        Stop the reminder scheduler.

        Shuts down the scheduler and clears all jobs.
        """
        if not self._running or not self._scheduler:
            logger.warning("ReminderService not running")
            return

        self._scheduler.shutdown(wait=False)
        self._scheduler = None
        self._running = False
        logger.info("ReminderService stopped")

    async def _load_reminders(self) -> None:
        """
        Load all enabled reminders from database and schedule them.
        """
        if not self._scheduler:
            return

        try:
            async with get_session() as session:
                # Get all enabled reminders
                result = await session.execute(
                    select(Reminder, User.telegram_id)
                    .join(User, Reminder.user_id == User.id)
                    .where(Reminder.enabled == True)
                )

                reminders = result.fetchall()

                for reminder, telegram_id in reminders:
                    self._schedule_reminder(reminder, telegram_id)

                logger.info("Loaded reminders", count=len(reminders))

        except Exception as e:
            logger.error("Failed to load reminders", error=str(e))

    def _schedule_reminder(self, reminder: Reminder, telegram_id: int) -> None:
        """
        Schedule a single reminder.

        Args:
            reminder: The Reminder model instance.
            telegram_id: The user's Telegram ID.
        """
        if not self._scheduler:
            return

        job_id = f"reminder_{reminder.id}"

        # Remove existing job if any
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

        # Create cron trigger for the reminder time
        trigger = CronTrigger(
            hour=reminder.time_utc.hour,
            minute=reminder.time_utc.minute,
            timezone="UTC",
        )

        # Add job
        self._scheduler.add_job(
            self._send_reminder,
            trigger,
            id=job_id,
            args=[reminder.id, telegram_id],
            replace_existing=True,
        )

        logger.debug(
            "Scheduled reminder",
            reminder_id=reminder.id,
            time=str(reminder.time_utc),
            telegram_id=telegram_id,
        )

    async def _send_reminder(self, reminder_id: int, telegram_id: int) -> None:
        """
        Send a reminder message to a user.

        Args:
            reminder_id: The reminder ID.
            telegram_id: The user's Telegram ID.
        """
        if not self._bot:
            logger.warning("Bot not set, cannot send reminder")
            return

        try:
            async with get_session() as session:
                # Get reminder
                result = await session.execute(
                    select(Reminder).where(Reminder.id == reminder_id)
                )
                reminder = result.scalar_one_or_none()

                if not reminder or not reminder.enabled:
                    return

                # Check if already sent today (avoid duplicates)
                today = datetime.utcnow().date()
                if reminder.last_sent and reminder.last_sent.date() == today:
                    logger.debug("Reminder already sent today", reminder_id=reminder_id)
                    return

                # Get user
                user_result = await session.execute(
                    select(User).where(User.id == reminder.user_id)
                )
                user = user_result.scalar_one_or_none()

                if not user:
                    return

                # Determine reminder type based on time
                hour = reminder.time_utc.hour
                if hour <= 9:
                    message = await self._generate_morning_reminder(session, user.id)
                elif hour <= 12:
                    message = await self._generate_session_reminder(session, user.id)
                else:
                    message = await self._generate_review_reminder(session, user.id)

                # Send message
                await self._bot.send_message(
                    chat_id=telegram_id,
                    text=message,
                    parse_mode="HTML",
                )

                # Update last_sent
                reminder.last_sent = datetime.utcnow()
                await session.commit()

                logger.info(
                    "Reminder sent",
                    reminder_id=reminder_id,
                    telegram_id=telegram_id,
                )

        except Exception as e:
            logger.error(
                "Failed to send reminder",
                reminder_id=reminder_id,
                error=str(e),
            )

    async def _generate_morning_reminder(
        self, session: AsyncSession, user_id: int
    ) -> str:
        """
        Generate morning prep reminder content.

        Shows open positions and yesterday's P&L.

        Args:
            session: Database session.
            user_id: Internal user ID.

        Returns:
            str: Formatted reminder message.
        """
        lines = [
            "<b>Good Morning! Time for your Trading Prep</b>",
            "",
        ]

        # Get open positions
        accounts_result = await session.execute(
            select(Account.id).where(Account.user_id == user_id).where(Account.is_active == True)
        )
        account_ids = [row[0] for row in accounts_result.fetchall()]

        if account_ids:
            open_result = await session.execute(
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.OPEN)
            )
            open_trades = list(open_result.scalars().all())

            lines.append(f"<b>Open Positions:</b> {len(open_trades)}")

            for trade in open_trades[:5]:  # Show top 5
                lines.append(f"  - {trade.instrument} ({trade.direction.value.upper()})")

            if len(open_trades) > 5:
                lines.append(f"  ... and {len(open_trades) - 5} more")

            # Get yesterday's P&L
            yesterday = datetime.utcnow().date() - timedelta(days=1)
            yesterday_start = datetime.combine(yesterday, datetime.min.time())
            yesterday_end = datetime.combine(yesterday, datetime.max.time())

            yesterday_result = await session.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.closed_at >= yesterday_start)
                .where(Trade.closed_at <= yesterday_end)
            )
            yesterday_pnl = yesterday_result.scalar() or Decimal("0")

            lines.append("")
            pnl_sign = "+" if yesterday_pnl >= 0 else ""
            lines.append(f"<b>Yesterday's P&L:</b> {pnl_sign}${yesterday_pnl:.2f}")

        lines.append("")
        lines.append("Have a great trading day!")

        return "\n".join(lines)

    async def _generate_session_reminder(
        self, session: AsyncSession, user_id: int
    ) -> str:
        """
        Generate session check reminder content.

        Shows current open positions and session P&L.

        Args:
            session: Database session.
            user_id: Internal user ID.

        Returns:
            str: Formatted reminder message.
        """
        lines = [
            "<b>Mid-Session Check</b>",
            "",
        ]

        # Get account IDs
        accounts_result = await session.execute(
            select(Account.id).where(Account.user_id == user_id).where(Account.is_active == True)
        )
        account_ids = [row[0] for row in accounts_result.fetchall()]

        if account_ids:
            # Open positions
            open_result = await session.execute(
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.OPEN)
            )
            open_trades = list(open_result.scalars().all())

            lines.append(f"<b>Open Positions:</b> {len(open_trades)}")

            for trade in open_trades:
                sl_tp_info = ""
                if trade.sl_price:
                    sl_tp_info += f" SL:{trade.sl_price}"
                if trade.tp_price:
                    sl_tp_info += f" TP:{trade.tp_price}"
                lines.append(f"  - {trade.instrument} @ {trade.entry_price}{sl_tp_info}")

            # Today's session P&L
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())

            today_result = await session.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.closed_at >= today_start)
            )
            today_pnl = today_result.scalar() or Decimal("0")

            lines.append("")
            pnl_sign = "+" if today_pnl >= 0 else ""
            lines.append(f"<b>Session P&L:</b> {pnl_sign}${today_pnl:.2f}")

        lines.append("")
        lines.append("Stay focused and manage your risk!")

        return "\n".join(lines)

    async def _generate_review_reminder(
        self, session: AsyncSession, user_id: int
    ) -> str:
        """
        Generate US session review reminder content.

        Shows today's trades, P&L, and win rate.

        Args:
            session: Database session.
            user_id: Internal user ID.

        Returns:
            str: Formatted reminder message.
        """
        lines = [
            "<b>US Session Review</b>",
            "",
        ]

        # Get account IDs
        accounts_result = await session.execute(
            select(Account.id).where(Account.user_id == user_id).where(Account.is_active == True)
        )
        account_ids = [row[0] for row in accounts_result.fetchall()]

        if account_ids:
            today = datetime.utcnow().date()
            today_start = datetime.combine(today, datetime.min.time())

            # Today's closed trades
            today_trades_result = await session.execute(
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.closed_at >= today_start)
            )
            today_trades = list(today_trades_result.scalars().all())

            total_trades = len(today_trades)
            winning_trades = sum(1 for t in today_trades if t.pnl and t.pnl > 0)
            losing_trades = sum(1 for t in today_trades if t.pnl and t.pnl < 0)
            total_pnl = sum(t.pnl for t in today_trades if t.pnl) or Decimal("0")

            lines.append(f"<b>Today's Trades:</b> {total_trades}")
            lines.append(f"  Wins: {winning_trades}")
            lines.append(f"  Losses: {losing_trades}")

            if total_trades > 0:
                win_rate = (winning_trades / total_trades) * 100
                lines.append(f"  Win Rate: {win_rate:.1f}%")

            lines.append("")
            pnl_sign = "+" if total_pnl >= 0 else ""
            lines.append(f"<b>Today's P&L:</b> {pnl_sign}${total_pnl:.2f}")

            # Show recent trades
            if today_trades:
                lines.append("")
                lines.append("<b>Recent Trades:</b>")
                for trade in today_trades[-5:]:
                    pnl_str = f"+${trade.pnl:.2f}" if trade.pnl and trade.pnl >= 0 else f"-${abs(trade.pnl):.2f}" if trade.pnl else "N/A"
                    lines.append(f"  - {trade.instrument}: {pnl_str}")

        lines.append("")
        lines.append("Review your trades and prepare for tomorrow!")

        return "\n".join(lines)

    async def add_reminder(self, reminder_id: int, telegram_id: int) -> None:
        """
        Add a new reminder to the schedule.

        Args:
            reminder_id: The reminder ID.
            telegram_id: The user's Telegram ID.
        """
        if not self._scheduler:
            return

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Reminder).where(Reminder.id == reminder_id)
                )
                reminder = result.scalar_one_or_none()

                if reminder and reminder.enabled:
                    self._schedule_reminder(reminder, telegram_id)
                    logger.info("Added reminder to schedule", reminder_id=reminder_id)

        except Exception as e:
            logger.error("Failed to add reminder", reminder_id=reminder_id, error=str(e))

    async def remove_reminder(self, reminder_id: int) -> None:
        """
        Remove a reminder from the schedule.

        Args:
            reminder_id: The reminder ID.
        """
        if not self._scheduler:
            return

        job_id = f"reminder_{reminder_id}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Removed reminder from schedule", reminder_id=reminder_id)
        except Exception as e:
            logger.debug("Reminder job not found", reminder_id=reminder_id, error=str(e))

    async def update_reminder(self, reminder_id: int, telegram_id: int) -> None:
        """
        Update a reminder in the schedule.

        Args:
            reminder_id: The reminder ID.
            telegram_id: The user's Telegram ID.
        """
        await self.remove_reminder(reminder_id)
        await self.add_reminder(reminder_id, telegram_id)

    async def reload_all_reminders(self) -> None:
        """
        Reload all reminders from database.

        Clears existing schedule and reloads everything.
        """
        if not self._scheduler:
            return

        # Remove all existing jobs
        self._scheduler.remove_all_jobs()

        # Reload from database
        await self._load_reminders()
        logger.info("Reloaded all reminders")

    def get_next_run_time(self, reminder_id: int) -> Optional[datetime]:
        """
        Get the next scheduled run time for a reminder.

        Args:
            reminder_id: The reminder ID.

        Returns:
            Optional[datetime]: Next run time, or None if not scheduled.
        """
        if not self._scheduler:
            return None

        job_id = f"reminder_{reminder_id}"
        try:
            job = self._scheduler.get_job(job_id)
            if job:
                return job.next_run_time
        except Exception:
            pass

        return None


# Module-level singleton instance
_reminder_service: Optional[ReminderService] = None


def get_reminder_service() -> ReminderService:
    """
    Get or create the global reminder service instance.

    Returns:
        ReminderService: The global reminder service singleton.
    """
    global _reminder_service
    if _reminder_service is None:
        _reminder_service = ReminderService()
    return _reminder_service


def reset_reminder_service() -> None:
    """
    Reset the global reminder service instance.

    Useful for testing or reconfiguration.
    """
    global _reminder_service
    if _reminder_service and _reminder_service.is_running:
        # Note: This should be called with asyncio.run() in tests
        pass
    _reminder_service = None


async def shutdown_reminder_service() -> None:
    """
    Gracefully shutdown the reminder service.

    Stops the scheduler and resets the singleton.
    """
    global _reminder_service
    if _reminder_service and _reminder_service.is_running:
        await _reminder_service.stop()
    _reminder_service = None
