"""
Tag management handlers for the Telegram Trade Journal Bot.

This module provides:
- Tag list view with trade counts
- Tag creation and validation
- Tag deletion with confirmation
- View trades by tag
"""

import re
from typing import Optional

from sqlalchemy import delete, func, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_logger
from database.db import get_session
from database.models import Account, Tag, Trade, TradeStatus, TradeTag
from handlers.accounts import get_user_by_telegram_id
from utils.keyboards import back_cancel_keyboard, back_to_menu_keyboard, confirmation_keyboard

logger = get_logger(__name__)

# Conversation states
TAG_NAME = 0
TAG_CONFIRM_DELETE = 1

# Wizard data keys
TAG_WIZARD_KEY = "tag_wizard"

# Validation constants
MIN_TAG_NAME_LENGTH = 2
MAX_TAG_NAME_LENGTH = 30
MAX_TAGS_PER_USER = 20
TAG_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9\s]+$")


def tag_list_keyboard(
    tags: list[tuple[int, str, int, bool]],
    include_create: bool = True,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for tag list view.

    Args:
        tags: List of (tag_id, name, trade_count, is_default) tuples.
        include_create: Whether to include the Create Tag button.

    Returns:
        InlineKeyboardMarkup: Tag list keyboard.
    """
    keyboard = []

    for tag_id, name, count, is_default in tags:
        prefix = "[*] " if is_default else ""
        label = f"{prefix}{name} ({count} trades)"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"tag_view_{tag_id}"),
        ])

    if include_create:
        keyboard.append([
            InlineKeyboardButton("+ Create Tag", callback_data="tag_create"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_home"),
    ])

    return InlineKeyboardMarkup(keyboard)


def tag_detail_keyboard(tag_id: int) -> InlineKeyboardMarkup:
    """
    Create keyboard for tag detail view.

    Args:
        tag_id: The tag ID.

    Returns:
        InlineKeyboardMarkup: Tag detail keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "Toggle Default", callback_data=f"tag_toggle_default_{tag_id}"
            ),
        ],
        [
            InlineKeyboardButton("Delete Tag", callback_data=f"tag_delete_{tag_id}"),
        ],
        [
            InlineKeyboardButton("Back to Tags", callback_data="menu_tags"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def validate_tag_name(name: str) -> tuple[bool, str]:
    """
    Validate a tag name.

    Args:
        name: The tag name to validate.

    Returns:
        tuple: (is_valid, error_message)
    """
    if len(name) < MIN_TAG_NAME_LENGTH:
        return False, f"Tag name must be at least {MIN_TAG_NAME_LENGTH} characters."

    if len(name) > MAX_TAG_NAME_LENGTH:
        return False, f"Tag name must be at most {MAX_TAG_NAME_LENGTH} characters."

    if not TAG_NAME_PATTERN.match(name):
        return False, "Tag name can only contain letters, numbers, and spaces."

    return True, ""


async def get_tags_with_counts(user_id: int) -> list[tuple[int, str, int, bool]]:
    """
    Get all tags with trade counts for a user.

    Tags are sorted: defaults first, then alphabetically.

    Args:
        user_id: The internal user ID.

    Returns:
        list: List of (tag_id, name, trade_count, is_default) tuples.
    """
    async with get_session() as session:
        # Get user's account IDs for filtering trades
        account_result = await session.execute(
            select(Account.id)
            .where(Account.user_id == user_id)
            .where(Account.is_active == True)
        )
        account_ids = [row[0] for row in account_result.fetchall()]

        # Get all tags with counts
        result = await session.execute(
            select(
                Tag.id,
                Tag.name,
                Tag.is_default,
                func.count(TradeTag.trade_id).label("trade_count"),
            )
            .outerjoin(TradeTag, Tag.id == TradeTag.tag_id)
            .outerjoin(
                Trade,
                (TradeTag.trade_id == Trade.id) & (Trade.account_id.in_(account_ids)),
            )
            .group_by(Tag.id, Tag.name, Tag.is_default)
            .order_by(Tag.is_default.desc(), Tag.name)
        )

        tags = []
        for row in result.fetchall():
            tags.append((row[0], row[1], row[3] or 0, row[2]))

        return tags


async def get_tag_count() -> int:
    """
    Get total number of tags.

    Returns:
        int: Total tag count.
    """
    async with get_session() as session:
        result = await session.execute(select(func.count(Tag.id)))
        return result.scalar() or 0


# ============================================================================
# TAG LIST AND DETAIL
# ============================================================================


async def handle_tags_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the tags menu callback - show list of all tags.

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

        tags = await get_tags_with_counts(user.id)
        tag_count = len(tags)

        if not tags:
            message = (
                "You haven't created any tags yet.\n\n"
                "Tags help you categorize and filter your trades."
            )
        else:
            message = f"Your Tags ({tag_count}/{MAX_TAGS_PER_USER}):\n\n"
            message += "[*] = default tag (shown first in selection)\n\n"
            message += "Select a tag to view details:"

        can_create = tag_count < MAX_TAGS_PER_USER
        await query.edit_message_text(
            text=message,
            reply_markup=tag_list_keyboard(tags, include_create=can_create),
        )

    except Exception as e:
        logger.error("Error loading tags", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_tag_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle viewing a tag's details and trades.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    tag_id_str = query.data.replace("tag_view_", "")
    try:
        tag_id = int(tag_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get tag
            tag_result = await session.execute(
                select(Tag).where(Tag.id == tag_id)
            )
            tag = tag_result.scalar_one_or_none()

            if not tag:
                await query.edit_message_text(
                    "Tag not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get user's account IDs
            account_result = await session.execute(
                select(Account.id)
                .where(Account.user_id == user.id)
                .where(Account.is_active == True)
            )
            account_ids = [row[0] for row in account_result.fetchall()]

            # Get trades with this tag
            trades_result = await session.execute(
                select(Trade)
                .join(TradeTag, Trade.id == TradeTag.trade_id)
                .where(TradeTag.tag_id == tag_id)
                .where(Trade.account_id.in_(account_ids))
                .order_by(Trade.opened_at.desc())
                .limit(10)
            )
            trades = trades_result.scalars().all()

            # Count total trades
            count_result = await session.execute(
                select(func.count(Trade.id))
                .join(TradeTag, Trade.id == TradeTag.trade_id)
                .where(TradeTag.tag_id == tag_id)
                .where(Trade.account_id.in_(account_ids))
            )
            total_trades = count_result.scalar() or 0

            # Build message
            default_indicator = " (Default)" if tag.is_default else ""
            lines = [
                f"Tag: {tag.name}{default_indicator}",
                "=" * 30,
                "",
                f"Total Trades: {total_trades}",
                "",
            ]

            if trades:
                lines.append("Recent Trades:")
                for trade in trades[:5]:
                    status = "OPEN" if trade.status == TradeStatus.OPEN else "CLOSED"
                    lines.append(
                        f"  - {trade.instrument} {trade.direction.value.upper()} [{status}]"
                    )
                if total_trades > 5:
                    lines.append(f"  ... and {total_trades - 5} more")
            else:
                lines.append("No trades with this tag yet.")

            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=tag_detail_keyboard(tag_id),
            )

    except Exception as e:
        logger.error("Error viewing tag", error=str(e), tag_id=tag_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_tag_toggle_default(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Toggle a tag's default status.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    tag_id_str = query.data.replace("tag_toggle_default_", "")
    try:
        tag_id = int(tag_id_str)
    except ValueError:
        return

    try:
        async with get_session() as session:
            tag_result = await session.execute(
                select(Tag).where(Tag.id == tag_id)
            )
            tag = tag_result.scalar_one_or_none()

            if tag:
                tag.is_default = not tag.is_default
                await session.flush()

                status = "default" if tag.is_default else "not default"
                logger.info("Tag default toggled", tag_id=tag_id, is_default=tag.is_default)

                await query.edit_message_text(
                    f"Tag '{tag.name}' is now {status}.",
                    reply_markup=tag_detail_keyboard(tag_id),
                )
            else:
                await query.edit_message_text(
                    "Tag not found.",
                    reply_markup=back_to_menu_keyboard(),
                )

    except Exception as e:
        logger.error("Error toggling tag default", error=str(e), tag_id=tag_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# TAG CREATION
# ============================================================================


async def start_create_tag(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the tag creation flow.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()

    # Check tag limit
    tag_count = await get_tag_count()
    if tag_count >= MAX_TAGS_PER_USER:
        await query.edit_message_text(
            f"You've reached the maximum of {MAX_TAGS_PER_USER} tags.\n\n"
            "Please delete an existing tag before creating a new one.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    context.user_data[TAG_WIZARD_KEY] = {}

    await query.edit_message_text(
        "Create a new tag\n\n"
        f"Enter the tag name ({MIN_TAG_NAME_LENGTH}-{MAX_TAG_NAME_LENGTH} characters):\n"
        "Only letters, numbers, and spaces are allowed.",
        reply_markup=back_cancel_keyboard(back_data="menu_tags"),
    )

    return TAG_NAME


async def handle_tag_name_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle tag name input.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END or current state on error.
    """
    if not update.message or not update.message.text:
        return TAG_NAME

    name_input = update.message.text.strip()

    # Validate name
    is_valid, error_msg = validate_tag_name(name_input)
    if not is_valid:
        await update.message.reply_text(
            f"Invalid tag name: {error_msg}\n\nPlease try again:",
            reply_markup=back_cancel_keyboard(back_data="menu_tags"),
        )
        return TAG_NAME

    # Check uniqueness
    async with get_session() as session:
        existing = await session.execute(
            select(Tag).where(func.lower(Tag.name) == name_input.lower())
        )
        if existing.scalar_one_or_none():
            await update.message.reply_text(
                f"A tag named '{name_input}' already exists.\n\nPlease enter a different name:",
                reply_markup=back_cancel_keyboard(back_data="menu_tags"),
            )
            return TAG_NAME

        # Create the tag
        tag = Tag(name=name_input, is_default=False)
        session.add(tag)
        await session.flush()

        logger.info("Tag created", tag_id=tag.id, name=tag.name)

        await update.message.reply_text(
            f"Tag '{tag.name}' created successfully!",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(TAG_WIZARD_KEY, None)
    return ConversationHandler.END


async def cancel_tag_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the tag creation flow.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(TAG_WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Tag creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "Tag creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Tag creation ConversationHandler
tag_create_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_create_tag, pattern="^tag_create$"),
    ],
    states={
        TAG_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tag_name_input),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_tag_wizard),
        CallbackQueryHandler(cancel_tag_wizard, pattern="^cancel$"),
        CallbackQueryHandler(cancel_tag_wizard, pattern="^back$"),
        CallbackQueryHandler(cancel_tag_wizard, pattern="^menu_tags$"),
    ],
    per_message=False,
)


# ============================================================================
# TAG DELETION
# ============================================================================


async def handle_tag_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle tag deletion with confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if query.data.startswith("tag_delete_") and not query.data.startswith(
        "tag_delete_confirm_"
    ):
        tag_id_str = query.data.replace("tag_delete_", "")
        try:
            tag_id = int(tag_id_str)
        except ValueError:
            return

        context.user_data["delete_tag_id"] = tag_id

        await query.edit_message_text(
            "Are you sure you want to delete this tag?\n\n"
            "This will remove the tag from all trades but won't delete the trades.",
            reply_markup=confirmation_keyboard(
                confirm_text="Yes, Delete",
                cancel_text="No, Keep It",
                confirm_data=f"tag_delete_confirm_{tag_id}",
                cancel_data=f"tag_view_{tag_id}",
            ),
        )

    elif query.data.startswith("tag_delete_confirm_"):
        tag_id_str = query.data.replace("tag_delete_confirm_", "")
        try:
            tag_id = int(tag_id_str)
        except ValueError:
            return

        try:
            async with get_session() as session:
                # Delete TradeTag associations first
                await session.execute(
                    delete(TradeTag).where(TradeTag.tag_id == tag_id)
                )

                # Delete the tag
                tag_result = await session.execute(
                    select(Tag).where(Tag.id == tag_id)
                )
                tag = tag_result.scalar_one_or_none()

                if tag:
                    tag_name = tag.name
                    await session.delete(tag)
                    await session.flush()

                    logger.info("Tag deleted", tag_id=tag_id, name=tag_name)

                    await query.edit_message_text(
                        f"Tag '{tag_name}' has been deleted.",
                        reply_markup=back_to_menu_keyboard(),
                    )
                else:
                    await query.edit_message_text(
                        "Tag not found.",
                        reply_markup=back_to_menu_keyboard(),
                    )

        except Exception as e:
            logger.error("Error deleting tag", error=str(e), tag_id=tag_id)
            await query.edit_message_text(
                "An error occurred. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )

        context.user_data.pop("delete_tag_id", None)
