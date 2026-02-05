"""
Reminder management handlers for the Telegram Trade Journal Bot.

This module provides:
- Reminder schedule display
- Enable/Disable toggles
- Add and delete reminders
- Schedule visualization
"""

import re
from datetime import datetime, time
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_logger
from database.db import get_session
from database.models import Reminder, User
from handlers.accounts import get_user_by_telegram_id
from services.reminder_service import DEFAULT_REMINDERS, get_reminder_service
from utils.keyboards import back_cancel_keyboard, back_to_menu_keyboard

logger = get_logger(__name__)

# Conversation states
REMINDER_TIME_INPUT = 0

# Context keys
REMINDER_KEY = "reminder_wizard"

# Maximum number of reminders per user
MAX_REMINDERS = 10


def reminders_menu_keyboard(
    reminders: list[tuple[int, time, bool]],
    show_add: bool = True,
) -> InlineKeyboardMarkup:
    """
    Create the reminders management keyboard.

    Args:
        reminders: List of (reminder_id, time_utc, enabled) tuples.
        show_add: Whether to show the Add Reminder button.

    Returns:
        InlineKeyboardMarkup: Reminders menu keyboard.
    """
    keyboard = []

    for reminder_id, time_utc, enabled in reminders:
        status_icon = "[ON]" if enabled else "[OFF]"
        time_str = time_utc.strftime("%H:%M UTC")

        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {time_str}",
                callback_data=f"reminder_view_{reminder_id}",
            ),
        ])

    if show_add and len(reminders) < MAX_REMINDERS:
        keyboard.append([
            InlineKeyboardButton("+ Add Reminder", callback_data="reminder_add"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_main"),
    ])

    return InlineKeyboardMarkup(keyboard)


def reminder_detail_keyboard(
    reminder_id: int,
    is_enabled: bool,
    is_default: bool = False,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for reminder detail view.

    Args:
        reminder_id: The reminder ID.
        is_enabled: Whether the reminder is currently enabled.
        is_default: Whether this is a default reminder (affects delete option).

    Returns:
        InlineKeyboardMarkup: Reminder detail keyboard.
    """
    toggle_text = "Disable" if is_enabled else "Enable"
    toggle_data = f"reminder_toggle_{reminder_id}"

    keyboard = [
        [
            InlineKeyboardButton(toggle_text, callback_data=toggle_data),
        ],
    ]

    # Only show delete for non-default reminders
    if not is_default:
        keyboard.append([
            InlineKeyboardButton("Delete", callback_data=f"reminder_delete_{reminder_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Reminders", callback_data="menu_reminders"),
    ])

    return InlineKeyboardMarkup(keyboard)


def reminder_confirm_delete_keyboard(reminder_id: int) -> InlineKeyboardMarkup:
    """
    Create confirmation keyboard for deleting a reminder.

    Args:
        reminder_id: The reminder ID.

    Returns:
        InlineKeyboardMarkup: Delete confirmation keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "Yes, Delete",
                callback_data=f"reminder_confirm_delete_{reminder_id}",
            ),
            InlineKeyboardButton(
                "No, Keep It",
                callback_data=f"reminder_view_{reminder_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ensure_default_reminders(session: AsyncSession, user_id: int) -> None:
    """
    Ensure default reminders exist for a user.

    Creates the default morning, session, and review reminders if they don't exist.

    Args:
        session: Database session.
        user_id: Internal user ID.
    """
    # Check existing reminders
    existing_result = await session.execute(
        select(Reminder.time_utc).where(Reminder.user_id == user_id)
    )
    existing_times = {row[0] for row in existing_result.fetchall()}

    # Create missing default reminders
    for default in DEFAULT_REMINDERS:
        if default["time_utc"] not in existing_times:
            reminder = Reminder(
                user_id=user_id,
                time_utc=default["time_utc"],
                enabled=True,
            )
            session.add(reminder)

    await session.flush()


async def get_user_reminders(
    session: AsyncSession, user_id: int
) -> list[tuple[int, time, bool]]:
    """
    Get all reminders for a user.

    Args:
        session: Database session.
        user_id: Internal user ID.

    Returns:
        list: List of (reminder_id, time_utc, enabled) tuples sorted by time.
    """
    result = await session.execute(
        select(Reminder.id, Reminder.time_utc, Reminder.enabled)
        .where(Reminder.user_id == user_id)
        .order_by(Reminder.time_utc)
    )
    return [(row[0], row[1], row[2]) for row in result.fetchall()]


def is_default_reminder(time_utc: time) -> bool:
    """
    Check if a reminder time is one of the default times.

    Args:
        time_utc: The reminder time.

    Returns:
        bool: True if this is a default reminder time.
    """
    default_times = {d["time_utc"] for d in DEFAULT_REMINDERS}
    return time_utc in default_times


def get_next_reminder_time(
    reminders: list[tuple[int, time, bool]]
) -> Optional[tuple[time, str]]:
    """
    Get the next scheduled reminder time.

    Args:
        reminders: List of (reminder_id, time_utc, enabled) tuples.

    Returns:
        Optional[tuple]: (time, formatted_string) of next reminder, or None.
    """
    now = datetime.utcnow().time()
    enabled_reminders = [(rid, t, e) for rid, t, e in reminders if e]

    if not enabled_reminders:
        return None

    # Find next reminder today
    for rid, t, e in enabled_reminders:
        if t > now:
            return (t, t.strftime("%H:%M UTC today"))

    # If none today, return first one tomorrow
    first = enabled_reminders[0]
    return (first[1], first[1].strftime("%H:%M UTC tomorrow"))


async def handle_reminders_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the reminders menu callback - show all reminders.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first to register.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Ensure default reminders exist
            await ensure_default_reminders(session, user.id)
            await session.commit()

            # Get all reminders
            reminders = await get_user_reminders(session, user.id)

            # Build message
            enabled_count = sum(1 for _, _, e in reminders if e)
            message_lines = [
                "Reminder Schedule",
                "=" * 25,
                "",
                f"Total Reminders: {len(reminders)}",
                f"Enabled: {enabled_count}",
                "",
            ]

            # Add next reminder info
            next_reminder = get_next_reminder_time(reminders)
            if next_reminder:
                message_lines.append(f"Next: {next_reminder[1]}")
            else:
                message_lines.append("No reminders enabled")

            message_lines.append("")
            message_lines.append("Select a reminder to manage:")

            await query.edit_message_text(
                text="\n".join(message_lines),
                reply_markup=reminders_menu_keyboard(reminders),
            )

    except Exception as e:
        logger.error("Error loading reminders", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_reminder_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle reminder detail view.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    reminder_id_str = query.data.replace("reminder_view_", "")
    try:
        reminder_id = int(reminder_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            result = await session.execute(
                select(Reminder)
                .where(Reminder.id == reminder_id)
                .where(Reminder.user_id == user.id)
            )
            reminder = result.scalar_one_or_none()

            if not reminder:
                await query.edit_message_text(
                    "Reminder not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Determine reminder type
            hour = reminder.time_utc.hour
            if hour <= 9:
                reminder_type = "Morning Prep"
                reminder_desc = "Open positions and yesterday's P&L"
            elif hour <= 12:
                reminder_type = "Session Check"
                reminder_desc = "Current positions and session P&L"
            else:
                reminder_type = "Session Review"
                reminder_desc = "Today's trades, P&L, and win rate"

            status = "Enabled" if reminder.enabled else "Disabled"
            is_default = is_default_reminder(reminder.time_utc)

            # Get next run time from scheduler
            reminder_service = get_reminder_service()
            next_run = reminder_service.get_next_run_time(reminder_id)
            next_run_str = next_run.strftime("%Y-%m-%d %H:%M UTC") if next_run else "Not scheduled"

            # Last sent info
            last_sent_str = reminder.last_sent.strftime("%Y-%m-%d %H:%M UTC") if reminder.last_sent else "Never"

            message = (
                f"Reminder Details\n"
                f"{'=' * 25}\n\n"
                f"Time: {reminder.time_utc.strftime('%H:%M UTC')}\n"
                f"Type: {reminder_type}\n"
                f"Status: {status}\n"
                f"{'(Default reminder)' if is_default else ''}\n\n"
                f"What you'll receive:\n"
                f"- {reminder_desc}\n\n"
                f"Next Scheduled: {next_run_str}\n"
                f"Last Sent: {last_sent_str}"
            )

            await query.edit_message_text(
                text=message,
                reply_markup=reminder_detail_keyboard(
                    reminder_id, reminder.enabled, is_default
                ),
            )

    except Exception as e:
        logger.error("Error viewing reminder", error=str(e), reminder_id=reminder_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_reminder_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle reminder enable/disable toggle.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    reminder_id_str = query.data.replace("reminder_toggle_", "")
    try:
        reminder_id = int(reminder_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return

            result = await session.execute(
                select(Reminder)
                .where(Reminder.id == reminder_id)
                .where(Reminder.user_id == user.id)
            )
            reminder = result.scalar_one_or_none()

            if not reminder:
                return

            # Toggle enabled status
            reminder.enabled = not reminder.enabled
            await session.flush()

            # Update scheduler
            reminder_service = get_reminder_service()
            if reminder.enabled:
                await reminder_service.add_reminder(reminder_id, telegram_id)
            else:
                await reminder_service.remove_reminder(reminder_id)

            await session.commit()

            logger.info(
                "Reminder toggled",
                reminder_id=reminder_id,
                enabled=reminder.enabled,
                telegram_id=telegram_id,
            )

        # Refresh the view
        query.data = f"reminder_view_{reminder_id}"
        await handle_reminder_view(update, context)

    except Exception as e:
        logger.error("Error toggling reminder", error=str(e), reminder_id=reminder_id)


async def handle_reminder_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle reminder delete request - show confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    reminder_id_str = query.data.replace("reminder_delete_", "")
    try:
        reminder_id = int(reminder_id_str)
    except ValueError:
        return

    await query.edit_message_text(
        "Are you sure you want to delete this reminder?\n\n"
        "This action cannot be undone.",
        reply_markup=reminder_confirm_delete_keyboard(reminder_id),
    )


async def handle_reminder_confirm_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle confirmed reminder deletion.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    reminder_id_str = query.data.replace("reminder_confirm_delete_", "")
    try:
        reminder_id = int(reminder_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return

            result = await session.execute(
                select(Reminder)
                .where(Reminder.id == reminder_id)
                .where(Reminder.user_id == user.id)
            )
            reminder = result.scalar_one_or_none()

            if not reminder:
                await query.edit_message_text(
                    "Reminder not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Check if it's a default reminder
            if is_default_reminder(reminder.time_utc):
                await query.edit_message_text(
                    "Cannot delete default reminders. You can disable them instead.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Remove from scheduler
            reminder_service = get_reminder_service()
            await reminder_service.remove_reminder(reminder_id)

            # Delete from database
            await session.delete(reminder)
            await session.commit()

            logger.info(
                "Reminder deleted",
                reminder_id=reminder_id,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                "Reminder deleted successfully.",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error deleting reminder", error=str(e), reminder_id=reminder_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_reminder_add_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the add reminder flow.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    telegram_id = update.effective_user.id

    # Check reminder limit
    async with get_session() as session:
        user = await get_user_by_telegram_id(session, telegram_id)
        if not user:
            await query.edit_message_text(
                "User not found.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

        count_result = await session.execute(
            select(Reminder.id).where(Reminder.user_id == user.id)
        )
        count = len(list(count_result.fetchall()))

        if count >= MAX_REMINDERS:
            await query.edit_message_text(
                f"You have reached the maximum of {MAX_REMINDERS} reminders.\n"
                "Please delete a reminder before adding a new one.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

    context.user_data[REMINDER_KEY] = {}

    await query.edit_message_text(
        "Add New Reminder\n"
        "=" * 25 + "\n\n"
        "Enter the time for your reminder in HH:MM format (24-hour, UTC).\n\n"
        "Examples:\n"
        "  08:00 - Morning\n"
        "  13:30 - Afternoon\n"
        "  21:00 - Evening",
        reply_markup=back_cancel_keyboard(back_data="menu_reminders"),
    )

    return REMINDER_TIME_INPUT


async def handle_reminder_time_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle time input for new reminder.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state or END.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return REMINDER_TIME_INPUT

    time_input = update.message.text.strip()
    telegram_id = update.effective_user.id

    # Validate time format
    time_pattern = re.compile(r'^([01]?[0-9]|2[0-3]):([0-5][0-9])$')
    match = time_pattern.match(time_input)

    if not match:
        await update.message.reply_text(
            "Invalid time format. Please enter time in HH:MM format.\n"
            "Example: 08:00 or 14:30",
            reply_markup=back_cancel_keyboard(back_data="menu_reminders"),
        )
        return REMINDER_TIME_INPUT

    hour = int(match.group(1))
    minute = int(match.group(2))
    reminder_time = time(hour, minute)

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Check if time already exists
            existing_result = await session.execute(
                select(Reminder)
                .where(Reminder.user_id == user.id)
                .where(Reminder.time_utc == reminder_time)
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                await update.message.reply_text(
                    f"A reminder already exists for {reminder_time.strftime('%H:%M UTC')}.\n"
                    "Please choose a different time.",
                    reply_markup=back_cancel_keyboard(back_data="menu_reminders"),
                )
                return REMINDER_TIME_INPUT

            # Create new reminder
            reminder = Reminder(
                user_id=user.id,
                time_utc=reminder_time,
                enabled=True,
            )
            session.add(reminder)
            await session.flush()

            # Add to scheduler
            reminder_service = get_reminder_service()
            await reminder_service.add_reminder(reminder.id, telegram_id)

            await session.commit()

            logger.info(
                "Reminder created",
                reminder_id=reminder.id,
                time=str(reminder_time),
                telegram_id=telegram_id,
            )

            await update.message.reply_text(
                f"Reminder created for {reminder_time.strftime('%H:%M UTC')}!\n\n"
                "You will receive trading updates at this time daily.",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error creating reminder", error=str(e), telegram_id=telegram_id)
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(REMINDER_KEY, None)
    return ConversationHandler.END


async def handle_reminder_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the reminder creation flow.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(REMINDER_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        # Return to reminders menu
        await handle_reminders_menu(update, context)
    elif update.message:
        await update.message.reply_text(
            "Reminder creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Reminder add ConversationHandler
reminder_add_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_reminder_add_start, pattern="^reminder_add$"),
    ],
    states={
        REMINDER_TIME_INPUT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reminder_time_input),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(handle_reminder_cancel, pattern="^(menu_reminders|cancel|back)$"),
    ],
    per_message=False,
)
