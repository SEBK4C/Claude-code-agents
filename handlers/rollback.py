"""
Rollback management handlers for the Telegram Trade Journal Bot.

This module provides:
- View available snapshots for data restoration
- Snapshot selection and detail viewing
- Confirmation flow for data rollback
- Execution of data restoration from snapshots
"""

from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

from config import get_logger
from database.db import get_session
from database.models import Account, DataSnapshot, Trade, User
from handlers.accounts import get_user_by_telegram_id
from services.snapshot_service import get_snapshot_service
from utils.keyboards import back_to_menu_keyboard

logger = get_logger(__name__)

# Conversation states
SELECTING_SNAPSHOT = 0
CONFIRMING_RESTORE = 1

# Context keys
ROLLBACK_KEY = "rollback_wizard"


def rollback_menu_keyboard(
    snapshots: list[DataSnapshot],
) -> InlineKeyboardMarkup:
    """
    Create the rollback menu keyboard with available snapshots.

    Args:
        snapshots: List of DataSnapshot objects to display.

    Returns:
        InlineKeyboardMarkup: Rollback menu keyboard with snapshot buttons.
    """
    keyboard = []
    snapshot_service = get_snapshot_service()

    for snapshot in snapshots:
        stats = snapshot_service.get_snapshot_stats(snapshot)
        # Format date as "Feb 4, 2026"
        date_str = snapshot.snapshot_date.strftime("%b %d, %Y")
        label = f"{date_str} - {stats['num_trades']} trades, {stats['num_accounts']} accounts"
        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"rollback_select_{snapshot.id}",
            ),
        ])

    if not snapshots:
        keyboard.append([
            InlineKeyboardButton(
                "No snapshots available",
                callback_data="rollback_noop",
            ),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_main"),
    ])

    return InlineKeyboardMarkup(keyboard)


def rollback_confirm_keyboard(snapshot_id: int) -> InlineKeyboardMarkup:
    """
    Create confirmation keyboard for restoring a snapshot.

    Args:
        snapshot_id: The ID of the snapshot to confirm restoration.

    Returns:
        InlineKeyboardMarkup: Confirm/Cancel keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "Confirm Restore",
                callback_data=f"rollback_confirm_{snapshot_id}",
            ),
            InlineKeyboardButton(
                "Cancel",
                callback_data="rollback_cancel",
            ),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_current_stats(
    session: AsyncSession, user_id: int
) -> dict[str, int]:
    """
    Get current data statistics for a user.

    Args:
        session: Database session.
        user_id: Internal user ID.

    Returns:
        dict: Statistics including num_accounts and num_trades.
    """
    # Count accounts
    accounts_result = await session.execute(
        select(func.count(Account.id)).where(Account.user_id == user_id)
    )
    num_accounts = accounts_result.scalar() or 0

    # Get account IDs
    account_ids_result = await session.execute(
        select(Account.id).where(Account.user_id == user_id)
    )
    account_ids = [row[0] for row in account_ids_result.fetchall()]

    # Count trades across all accounts
    num_trades = 0
    if account_ids:
        trades_result = await session.execute(
            select(func.count(Trade.id)).where(Trade.account_id.in_(account_ids))
        )
        num_trades = trades_result.scalar() or 0

    return {
        "num_accounts": num_accounts,
        "num_trades": num_trades,
    }


async def handle_rollback_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle the rollback menu callback - show available snapshots.

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

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first to register.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Get snapshots from last 7 days
            snapshot_service = get_snapshot_service()
            snapshots = await snapshot_service.list_snapshots(user.id, days=7)

            # Build message
            message_lines = [
                "Data Rollback",
                "=" * 25,
                "",
            ]

            if snapshots:
                message_lines.extend([
                    f"Found {len(snapshots)} snapshot(s) from the last 7 days.",
                    "",
                    "Select a date to restore your data:",
                    "",
                    "WARNING: Restoring will replace ALL current data.",
                ])
            else:
                message_lines.extend([
                    "No snapshots available.",
                    "",
                    "Snapshots are created automatically when you",
                    "add or modify trades, accounts, or transactions.",
                ])

            await query.edit_message_text(
                text="\n".join(message_lines),
                reply_markup=rollback_menu_keyboard(snapshots),
            )

            # Store user_id for later use
            context.user_data[ROLLBACK_KEY] = {"user_id": user.id}

            return SELECTING_SNAPSHOT

    except Exception as e:
        logger.error("Error loading rollback menu", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_rollback_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle snapshot selection - show snapshot details and confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    # Handle no-op callback
    if query.data == "rollback_noop":
        return SELECTING_SNAPSHOT

    # Extract snapshot ID
    snapshot_id_str = query.data.replace("rollback_select_", "")
    try:
        snapshot_id = int(snapshot_id_str)
    except ValueError:
        logger.warning("Invalid snapshot ID in callback", data=query.data)
        return SELECTING_SNAPSHOT

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Get snapshot
            snapshot_result = await session.execute(
                select(DataSnapshot)
                .where(DataSnapshot.id == snapshot_id)
                .where(DataSnapshot.user_id == user.id)
            )
            snapshot = snapshot_result.scalar_one_or_none()

            if not snapshot:
                await query.edit_message_text(
                    "Snapshot not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Get snapshot stats
            snapshot_service = get_snapshot_service()
            snapshot_stats = snapshot_service.get_snapshot_stats(snapshot)

            # Get current stats
            current_stats = await get_current_stats(session, user.id)

            # Format snapshot date
            date_str = snapshot.snapshot_date.strftime("%b %d, %Y")

            # Build confirmation message
            message_lines = [
                "Restore Data?",
                "=" * 25,
                "",
                f"This will restore your data to {date_str}.",
                "",
                f"Current: {current_stats['num_trades']} trades, {current_stats['num_accounts']} accounts",
                f"Snapshot: {snapshot_stats['num_trades']} trades, {snapshot_stats['num_accounts']} accounts",
                "",
                "WARNING: This action cannot be undone!",
                "All current data will be replaced.",
            ]

            await query.edit_message_text(
                text="\n".join(message_lines),
                reply_markup=rollback_confirm_keyboard(snapshot_id),
            )

            # Store snapshot_id for confirmation
            context.user_data[ROLLBACK_KEY] = {
                "user_id": user.id,
                "snapshot_id": snapshot_id,
            }

            return CONFIRMING_RESTORE

    except Exception as e:
        logger.error(
            "Error selecting snapshot",
            error=str(e),
            snapshot_id=snapshot_id,
            telegram_id=telegram_id,
        )
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_rollback_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle rollback confirmation - execute the restore.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    # Extract snapshot ID
    snapshot_id_str = query.data.replace("rollback_confirm_", "")
    try:
        snapshot_id = int(snapshot_id_str)
    except ValueError:
        logger.warning("Invalid snapshot ID in confirm callback", data=query.data)
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    # Get user_id from context
    rollback_data = context.user_data.get(ROLLBACK_KEY, {})
    user_id = rollback_data.get("user_id")

    if not user_id:
        # Fallback: get user from database
        try:
            async with get_session() as session:
                user = await get_user_by_telegram_id(session, telegram_id)
                if user:
                    user_id = user.id
        except Exception:
            pass

    if not user_id:
        await query.edit_message_text(
            "Session expired. Please start again.",
            reply_markup=back_to_menu_keyboard(),
        )
        context.user_data.pop(ROLLBACK_KEY, None)
        return ConversationHandler.END

    try:
        # Show "restoring..." message
        await query.edit_message_text(
            "Restoring data...\n\nPlease wait, this may take a moment.",
        )

        # Execute restore
        snapshot_service = get_snapshot_service()
        success, message = await snapshot_service.restore_snapshot(snapshot_id, user_id)

        if success:
            logger.info(
                "Data rollback completed",
                snapshot_id=snapshot_id,
                user_id=user_id,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                f"Data Restored Successfully!\n"
                f"{'=' * 25}\n\n"
                f"{message}\n\n"
                "Your data has been restored to the selected snapshot.",
                reply_markup=back_to_menu_keyboard(),
            )
        else:
            logger.warning(
                "Data rollback failed",
                snapshot_id=snapshot_id,
                user_id=user_id,
                message=message,
            )

            await query.edit_message_text(
                f"Restore Failed\n"
                f"{'=' * 25}\n\n"
                f"{message}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error(
            "Error during rollback",
            error=str(e),
            snapshot_id=snapshot_id,
            user_id=user_id,
            telegram_id=telegram_id,
        )
        await query.edit_message_text(
            "An error occurred during restore. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(ROLLBACK_KEY, None)
    return ConversationHandler.END


async def handle_rollback_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle rollback cancellation - return to main menu.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "Rollback cancelled.\n\nNo changes were made to your data.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(ROLLBACK_KEY, None)
    return ConversationHandler.END


async def handle_rollback_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle back navigation during rollback - return to snapshot list.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The conversation state for selecting snapshot.
    """
    # Re-trigger the menu to show snapshot list
    return await handle_rollback_menu(update, context)


# Rollback ConversationHandler
rollback_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(handle_rollback_menu, pattern="^menu_rollback$"),
    ],
    states={
        SELECTING_SNAPSHOT: [
            CallbackQueryHandler(handle_rollback_select, pattern=r"^rollback_select_\d+$"),
            CallbackQueryHandler(handle_rollback_select, pattern="^rollback_noop$"),
            CallbackQueryHandler(handle_rollback_cancel, pattern="^rollback_cancel$"),
            CallbackQueryHandler(handle_rollback_cancel, pattern="^menu_main$"),
        ],
        CONFIRMING_RESTORE: [
            CallbackQueryHandler(handle_rollback_confirm, pattern=r"^rollback_confirm_\d+$"),
            CallbackQueryHandler(handle_rollback_cancel, pattern="^rollback_cancel$"),
            CallbackQueryHandler(handle_rollback_back, pattern="^rollback_back$"),
            CallbackQueryHandler(handle_rollback_cancel, pattern="^menu_main$"),
        ],
    },
    fallbacks=[
        CallbackQueryHandler(handle_rollback_cancel, pattern="^(rollback_cancel|menu_main|menu_home)$"),
    ],
    per_message=False,
)
