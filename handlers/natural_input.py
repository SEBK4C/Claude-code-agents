"""
Natural language trade input handlers for the Telegram Trade Journal Bot.

This module provides handlers for parsing and processing natural language
trade messages, allowing users to log trades by typing naturally.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import get_logger
from database.db import get_session
from database.models import (
    Account,
    Tag,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
)
from handlers.accounts import get_user_by_telegram_id
from services.trade_parser import (
    ParsedTrade,
    TradeAction,
    get_trade_parser,
)
from utils.helpers import (
    calculate_pnl,
    calculate_pnl_percent,
    format_currency,
)
from utils.keyboards import back_to_menu_keyboard

logger = get_logger(__name__)

# Context keys for natural trade input state
NATURAL_TRADE_KEY = "natural_trade"
NATURAL_TRADE_STATE_KEY = "natural_trade_state"

# States for missing field prompts
STATE_AWAITING_INSTRUMENT = "awaiting_instrument"
STATE_AWAITING_DIRECTION = "awaiting_direction"
STATE_AWAITING_ENTRY_PRICE = "awaiting_entry_price"
STATE_AWAITING_EXIT_PRICE = "awaiting_exit_price"
STATE_AWAITING_LOT_SIZE = "awaiting_lot_size"
STATE_AWAITING_ACCOUNT = "awaiting_account"
STATE_CONFIRM_OPEN = "confirm_open"
STATE_CONFIRM_CLOSE = "confirm_close"


def natural_trade_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """
    Create confirmation keyboard for natural trade input.

    Args:
        action: The action type ("open" or "close").

    Returns:
        InlineKeyboardMarkup: Confirmation keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data=f"natural_{action}_confirm"),
            InlineKeyboardButton("Cancel", callback_data="natural_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def account_select_keyboard(accounts: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    """
    Create account selection keyboard for natural trade.

    Args:
        accounts: List of (account_id, name) tuples.

    Returns:
        InlineKeyboardMarkup: Account selection keyboard.
    """
    keyboard = []
    for account_id, name in accounts:
        keyboard.append([
            InlineKeyboardButton(name, callback_data=f"natural_acc_{account_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("Cancel", callback_data="natural_cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def open_trade_select_keyboard(
    trades: list[tuple[int, str, str, Decimal]]
) -> InlineKeyboardMarkup:
    """
    Create keyboard for selecting an open trade to close.

    Args:
        trades: List of (trade_id, instrument, direction, entry_price) tuples.

    Returns:
        InlineKeyboardMarkup: Trade selection keyboard.
    """
    keyboard = []
    for trade_id, instrument, direction, entry_price in trades:
        label = f"{instrument} {direction.upper()} @ {entry_price}"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"natural_close_{trade_id}")
        ])
    keyboard.append([
        InlineKeyboardButton("Cancel", callback_data="natural_cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


async def get_user_accounts_list(
    session: AsyncSession, user_id: int
) -> list[tuple[int, str]]:
    """
    Get all active accounts for a user.

    Args:
        session: The database session.
        user_id: The internal user ID.

    Returns:
        list: List of (account_id, name) tuples.
    """
    result = await session.execute(
        select(Account.id, Account.name)
        .where(Account.user_id == user_id)
        .where(Account.is_active == True)
        .order_by(Account.name)
    )
    return [(row[0], row[1]) for row in result.fetchall()]


async def get_user_open_trades(
    session: AsyncSession,
    user_id: int,
    instrument: Optional[str] = None,
    direction: Optional[str] = None,
) -> list[Trade]:
    """
    Get open trades for a user, optionally filtered by instrument/direction.

    Args:
        session: The database session.
        user_id: The internal user ID.
        instrument: Optional instrument filter.
        direction: Optional direction filter.

    Returns:
        list[Trade]: List of matching open trades.
    """
    query = (
        select(Trade)
        .join(Account)
        .where(Account.user_id == user_id)
        .where(Trade.status == TradeStatus.OPEN)
        .options(selectinload(Trade.account))
    )

    if instrument:
        query = query.where(Trade.instrument == instrument.upper())

    if direction:
        direction_enum = (
            TradeDirection.LONG if direction.lower() == "long" else TradeDirection.SHORT
        )
        query = query.where(Trade.direction == direction_enum)

    result = await session.execute(query.order_by(Trade.opened_at.desc()))
    return list(result.scalars().all())


async def get_or_create_tags(session: AsyncSession, tag_names: list[str]) -> list[Tag]:
    """
    Get existing tags or create them if they don't exist.

    Args:
        session: The database session.
        tag_names: List of tag names.

    Returns:
        list[Tag]: List of Tag instances.
    """
    tags = []
    for name in tag_names:
        result = await session.execute(
            select(Tag).where(Tag.name == name)
        )
        tag = result.scalar_one_or_none()
        if not tag:
            tag = Tag(name=name, is_default=False)
            session.add(tag)
            await session.flush()
        tags.append(tag)
    return tags


async def handle_natural_trade_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Attempt to parse a message as a natural language trade.

    This handler should be called first for text messages to check if
    the user is trying to log a trade naturally.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        bool: True if message was handled as a trade, False otherwise.
    """
    if not update.message or not update.message.text:
        return False

    message = update.message.text.strip()
    telegram_id = update.effective_user.id if update.effective_user else None

    if not telegram_id:
        return False

    # Parse the message
    parser = get_trade_parser()
    parsed = parser.parse_trade_message(message)

    # Only handle if confidence is above threshold (0.5)
    if parsed.confidence < 0.5:
        logger.debug(
            "Message not recognized as trade",
            confidence=parsed.confidence,
            telegram_id=telegram_id,
        )
        return False

    logger.info(
        "Natural trade input detected",
        action=parsed.action.value,
        confidence=parsed.confidence,
        telegram_id=telegram_id,
    )

    # Store parsed data in context
    context.user_data[NATURAL_TRADE_KEY] = parsed.to_dict()

    # Get user
    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "Please use /start first to register.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return True

            # Get user accounts
            accounts = await get_user_accounts_list(session, user.id)
            if not accounts:
                await update.message.reply_text(
                    "You need to create a trading account first.\n\n"
                    "Go to Accounts > Create Account to set one up.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return True

            # Store user_id
            context.user_data[NATURAL_TRADE_KEY]["user_id"] = user.id

            # Check for missing required fields
            if parsed.missing_fields:
                return await _ask_missing_field(
                    update, context, parsed, accounts, user.id
                )

            # If we have one account, auto-select it
            if len(accounts) == 1:
                context.user_data[NATURAL_TRADE_KEY]["account_id"] = accounts[0][0]
            else:
                # Need to ask for account
                context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_ACCOUNT
                await update.message.reply_text(
                    "Select the account for this trade:",
                    reply_markup=account_select_keyboard(accounts),
                )
                return True

            # Route to appropriate confirmation
            if parsed.action == TradeAction.CLOSE:
                return await _confirm_close_trade(update, context, session, user.id)
            else:
                return await _confirm_open_trade(update, context)

    except Exception as e:
        logger.error("Error handling natural trade input", error=str(e))
        await update.message.reply_text(
            "An error occurred while processing your trade. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return True


async def _ask_missing_field(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    parsed: ParsedTrade,
    accounts: list[tuple[int, str]],
    user_id: int,
) -> bool:
    """
    Prompt user for the first missing required field.

    Args:
        update: The Telegram update object.
        context: The callback context.
        parsed: The parsed trade data.
        accounts: List of user accounts.
        user_id: The internal user ID.

    Returns:
        bool: True (message was handled).
    """
    missing = parsed.missing_fields

    if "instrument" in missing:
        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_INSTRUMENT
        await update.message.reply_text(
            "I detected a trade but couldn't identify the instrument.\n\n"
            "What instrument did you trade? (e.g., DAX, NASDAQ, EURUSD)"
        )
    elif "direction" in missing:
        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_DIRECTION
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Long", callback_data="natural_dir_long"),
                InlineKeyboardButton("Short", callback_data="natural_dir_short"),
            ],
            [InlineKeyboardButton("Cancel", callback_data="natural_cancel")],
        ])
        await update.message.reply_text(
            "What was your trade direction?",
            reply_markup=keyboard,
        )
    elif "entry_price" in missing:
        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_ENTRY_PRICE
        await update.message.reply_text(
            "What was your entry price?"
        )
    elif "exit_price" in missing:
        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_EXIT_PRICE
        await update.message.reply_text(
            "What was your exit price?"
        )
    elif "lot_size" in missing:
        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_LOT_SIZE
        await update.message.reply_text(
            "What was your position size? (e.g., 0.5, 1, 2)"
        )

    return True


async def handle_missing_field_response(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Handle user response to a missing field prompt.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        bool: True if this was a missing field response, False otherwise.
    """
    if NATURAL_TRADE_STATE_KEY not in context.user_data:
        return False

    state = context.user_data[NATURAL_TRADE_STATE_KEY]
    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})

    if not trade_data:
        return False

    if not update.message or not update.message.text:
        return False

    text = update.message.text.strip()
    telegram_id = update.effective_user.id if update.effective_user else None

    if not telegram_id:
        return False

    try:
        if state == STATE_AWAITING_INSTRUMENT:
            # Validate instrument (2-20 chars, alphanumeric)
            instrument = text.upper()
            if not (2 <= len(instrument) <= 20):
                await update.message.reply_text(
                    "Please enter a valid instrument symbol (2-20 characters)."
                )
                return True
            trade_data["instrument"] = instrument
            trade_data["missing_fields"].remove("instrument")

        elif state == STATE_AWAITING_ENTRY_PRICE:
            try:
                price = Decimal(text.replace(",", "."))
                if price <= 0:
                    raise ValueError("Price must be positive")
                trade_data["entry_price"] = str(price)
                trade_data["missing_fields"].remove("entry_price")
            except (ValueError, InvalidOperation):
                await update.message.reply_text(
                    "Please enter a valid price (e.g., 18500 or 1.2345)."
                )
                return True

        elif state == STATE_AWAITING_EXIT_PRICE:
            try:
                price = Decimal(text.replace(",", "."))
                if price <= 0:
                    raise ValueError("Price must be positive")
                trade_data["exit_price"] = str(price)
                trade_data["missing_fields"].remove("exit_price")
            except (ValueError, InvalidOperation):
                await update.message.reply_text(
                    "Please enter a valid price (e.g., 18550 or 1.2400)."
                )
                return True

        elif state == STATE_AWAITING_LOT_SIZE:
            try:
                lot_size = Decimal(text.replace(",", "."))
                if lot_size <= 0:
                    raise ValueError("Lot size must be positive")
                trade_data["lot_size"] = str(lot_size)
                trade_data["missing_fields"].remove("lot_size")
            except (ValueError, InvalidOperation):
                await update.message.reply_text(
                    "Please enter a valid lot size (e.g., 0.5, 1, 2)."
                )
                return True

        else:
            return False

        # Check if more fields are missing
        context.user_data[NATURAL_TRADE_KEY] = trade_data

        if trade_data["missing_fields"]:
            # Create a mock ParsedTrade for the helper
            parsed = ParsedTrade(
                action=TradeAction(trade_data["action"]),
                instrument=trade_data.get("instrument"),
                direction=trade_data.get("direction"),
                entry_price=Decimal(trade_data["entry_price"]) if trade_data.get("entry_price") else None,
                exit_price=Decimal(trade_data["exit_price"]) if trade_data.get("exit_price") else None,
                missing_fields=trade_data["missing_fields"],
            )
            async with get_session() as session:
                user_id = trade_data["user_id"]
                accounts = await get_user_accounts_list(session, user_id)
                return await _ask_missing_field(
                    update, context, parsed, accounts, user_id
                )

        # All required fields collected - proceed to account selection or confirmation
        del context.user_data[NATURAL_TRADE_STATE_KEY]

        async with get_session() as session:
            user_id = trade_data["user_id"]
            accounts = await get_user_accounts_list(session, user_id)

            if "account_id" not in trade_data:
                if len(accounts) == 1:
                    trade_data["account_id"] = accounts[0][0]
                else:
                    context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_ACCOUNT
                    await update.message.reply_text(
                        "Select the account for this trade:",
                        reply_markup=account_select_keyboard(accounts),
                    )
                    return True

            # Route to confirmation
            if trade_data["action"] == "close":
                return await _confirm_close_trade(update, context, session, user_id)
            else:
                return await _confirm_open_trade(update, context)

    except Exception as e:
        logger.error("Error handling missing field response", error=str(e))
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)
        return True


async def handle_natural_direction_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle direction selection callback from keyboard.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})
    if not trade_data:
        # Stale state - return silently
        return

    direction = query.data.replace("natural_dir_", "")
    trade_data["direction"] = direction

    if "direction" in trade_data.get("missing_fields", []):
        trade_data["missing_fields"].remove("direction")

    context.user_data[NATURAL_TRADE_KEY] = trade_data

    # Check for more missing fields
    if trade_data["missing_fields"]:
        parsed = ParsedTrade(
            action=TradeAction(trade_data["action"]),
            instrument=trade_data.get("instrument"),
            direction=trade_data.get("direction"),
            missing_fields=trade_data["missing_fields"],
        )
        try:
            async with get_session() as session:
                user_id = trade_data["user_id"]
                accounts = await get_user_accounts_list(session, user_id)

                # Delete the keyboard message and send prompts
                await query.delete_message()

                # Create a fake update with message for the helper
                class FakeMessage:
                    async def reply_text(self, text, reply_markup=None):
                        await context.bot.send_message(
                            chat_id=update.effective_chat.id,
                            text=text,
                            reply_markup=reply_markup,
                        )

                class FakeUpdate:
                    message = FakeMessage()

                await _ask_missing_field(
                    FakeUpdate(), context, parsed, accounts, user_id
                )
        except Exception as e:
            logger.error("Error after direction selection", error=str(e))
        return

    # Clear state and proceed
    if NATURAL_TRADE_STATE_KEY in context.user_data:
        del context.user_data[NATURAL_TRADE_STATE_KEY]

    # Need to select account or confirm
    try:
        async with get_session() as session:
            user_id = trade_data["user_id"]
            accounts = await get_user_accounts_list(session, user_id)

            if "account_id" not in trade_data:
                if len(accounts) == 1:
                    trade_data["account_id"] = accounts[0][0]
                else:
                    context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_AWAITING_ACCOUNT
                    await query.edit_message_text(
                        "Select the account for this trade:",
                        reply_markup=account_select_keyboard(accounts),
                    )
                    return

            # Route to confirmation
            await query.delete_message()
            if trade_data["action"] == "close":
                await _confirm_close_trade_message(
                    context, update.effective_chat.id, session, user_id, trade_data
                )
            else:
                await _confirm_open_trade_message(
                    context, update.effective_chat.id, trade_data
                )

    except Exception as e:
        logger.error("Error in direction callback", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)


async def handle_natural_account_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle account selection callback from keyboard.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})
    if not trade_data:
        # Stale state - return silently
        return

    account_id = int(query.data.replace("natural_acc_", ""))
    trade_data["account_id"] = account_id
    context.user_data[NATURAL_TRADE_KEY] = trade_data

    # Clear awaiting state
    if context.user_data.get(NATURAL_TRADE_STATE_KEY) == STATE_AWAITING_ACCOUNT:
        del context.user_data[NATURAL_TRADE_STATE_KEY]

    try:
        async with get_session() as session:
            user_id = trade_data["user_id"]

            # Route to confirmation
            if trade_data["action"] == "close":
                await _confirm_close_trade_edit(
                    query, context, session, user_id, trade_data
                )
            else:
                await _confirm_open_trade_edit(query, context, trade_data)

    except Exception as e:
        logger.error("Error in account callback", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)


async def handle_natural_close_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle open trade selection for closing.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})
    if not trade_data:
        # Stale state - return silently
        return

    trade_id = int(query.data.replace("natural_close_", ""))
    trade_data["trade_id_to_close"] = trade_id
    context.user_data[NATURAL_TRADE_KEY] = trade_data

    # Show close confirmation
    try:
        async with get_session() as session:
            result = await session.execute(
                select(Trade)
                .where(Trade.id == trade_id)
                .options(selectinload(Trade.account))
            )
            trade = result.scalar_one_or_none()

            if not trade:
                await query.edit_message_text(
                    "Trade not found. Please try again.",
                    reply_markup=back_to_menu_keyboard(),
                )
                _clear_natural_trade_state(context)
                return

            exit_price = Decimal(trade_data["exit_price"])
            direction = trade.direction.value
            pnl = calculate_pnl(
                trade.entry_price, exit_price, direction, trade.lot_size
            )
            pnl_percent = calculate_pnl_percent(
                trade.entry_price, exit_price, direction
            )

            pnl_formatted = format_currency(pnl, trade.account.currency, include_sign=True)
            pnl_indicator = "profit" if pnl > 0 else "loss" if pnl < 0 else "break-even"

            summary = (
                f"**Close Trade Confirmation**\n\n"
                f"Instrument: {trade.instrument}\n"
                f"Direction: {direction.upper()}\n"
                f"Entry: {trade.entry_price}\n"
                f"Exit: {exit_price}\n"
                f"Size: {trade.lot_size} lots\n\n"
                f"**P&L: {pnl_formatted} ({pnl_percent:+.2f}%)** ({pnl_indicator})\n\n"
                f"Confirm closing this trade?"
            )

            context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_CLOSE
            await query.edit_message_text(
                summary,
                reply_markup=natural_trade_confirm_keyboard("close"),
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.error("Error in close select callback", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)


async def handle_natural_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle confirmation callback for opening/closing trades.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})
    if not trade_data:
        # Stale state - return silently
        return

    if query.data == "natural_open_confirm":
        await _save_open_trade(query, context, trade_data)
    elif query.data == "natural_close_confirm":
        await _save_close_trade(query, context, trade_data)


async def handle_natural_cancel_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle cancel callback for natural trade input.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer("Cancelled")

    _clear_natural_trade_state(context)

    await query.edit_message_text(
        "Trade input cancelled.",
        reply_markup=back_to_menu_keyboard(),
    )


async def _confirm_open_trade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """
    Show confirmation for opening a new trade.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        bool: True (message was handled).
    """
    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})

    summary = _build_open_trade_summary(trade_data)

    context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_OPEN
    await update.message.reply_text(
        summary,
        reply_markup=natural_trade_confirm_keyboard("open"),
        parse_mode="Markdown",
    )

    return True


async def _confirm_open_trade_edit(
    query, context: ContextTypes.DEFAULT_TYPE, trade_data: dict
) -> None:
    """Show open trade confirmation by editing message."""
    summary = _build_open_trade_summary(trade_data)

    context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_OPEN
    await query.edit_message_text(
        summary,
        reply_markup=natural_trade_confirm_keyboard("open"),
        parse_mode="Markdown",
    )


async def _confirm_open_trade_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, trade_data: dict
) -> None:
    """Show open trade confirmation by sending new message."""
    summary = _build_open_trade_summary(trade_data)

    context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_OPEN
    await context.bot.send_message(
        chat_id=chat_id,
        text=summary,
        reply_markup=natural_trade_confirm_keyboard("open"),
        parse_mode="Markdown",
    )


def _build_open_trade_summary(trade_data: dict) -> str:
    """Build summary text for opening a trade."""
    instrument = trade_data.get("instrument", "Unknown")
    direction = trade_data.get("direction", "unknown").upper()
    entry_price = trade_data.get("entry_price", "N/A")
    sl_price = trade_data.get("sl_price", "Not set")
    tp_price = trade_data.get("tp_price", "Not set")
    lot_size = trade_data.get("lot_size", "Not set")
    tags = trade_data.get("tags", [])

    summary = (
        f"**New Trade Confirmation**\n\n"
        f"Instrument: {instrument}\n"
        f"Direction: {direction}\n"
        f"Entry: {entry_price}\n"
        f"Stop Loss: {sl_price}\n"
        f"Take Profit: {tp_price}\n"
        f"Size: {lot_size} lots\n"
    )

    if tags:
        summary += f"Tags: {', '.join(tags)}\n"

    summary += "\nConfirm opening this trade?"

    return summary


async def _confirm_close_trade(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: AsyncSession,
    user_id: int,
) -> bool:
    """
    Show confirmation for closing a trade.

    Args:
        update: The Telegram update object.
        context: The callback context.
        session: The database session.
        user_id: The internal user ID.

    Returns:
        bool: True (message was handled).
    """
    trade_data = context.user_data.get(NATURAL_TRADE_KEY, {})

    instrument = trade_data.get("instrument")
    direction = trade_data.get("direction")

    # Find matching open trades
    open_trades = await get_user_open_trades(session, user_id, instrument, direction)

    if not open_trades:
        await update.message.reply_text(
            f"No open trades found for {instrument or 'any instrument'}.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)
        return True

    if len(open_trades) == 1:
        # Single match - show confirmation directly
        trade = open_trades[0]
        trade_data["trade_id_to_close"] = trade.id
        context.user_data[NATURAL_TRADE_KEY] = trade_data

        exit_price = Decimal(trade_data["exit_price"])
        pnl = calculate_pnl(
            trade.entry_price, exit_price, trade.direction.value, trade.lot_size
        )
        pnl_percent = calculate_pnl_percent(
            trade.entry_price, exit_price, trade.direction.value
        )

        pnl_formatted = format_currency(pnl, trade.account.currency, include_sign=True)
        pnl_indicator = "profit" if pnl > 0 else "loss" if pnl < 0 else "break-even"

        summary = (
            f"**Close Trade Confirmation**\n\n"
            f"Instrument: {trade.instrument}\n"
            f"Direction: {trade.direction.value.upper()}\n"
            f"Entry: {trade.entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Size: {trade.lot_size} lots\n\n"
            f"**P&L: {pnl_formatted} ({pnl_percent:+.2f}%)** ({pnl_indicator})\n\n"
            f"Confirm closing this trade?"
        )

        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_CLOSE
        await update.message.reply_text(
            summary,
            reply_markup=natural_trade_confirm_keyboard("close"),
            parse_mode="Markdown",
        )
    else:
        # Multiple matches - ask user to select
        trades_list = [
            (t.id, t.instrument, t.direction.value, t.entry_price)
            for t in open_trades
        ]
        await update.message.reply_text(
            f"Multiple open {instrument or ''} trades found. Select which to close:",
            reply_markup=open_trade_select_keyboard(trades_list),
        )

    return True


async def _confirm_close_trade_edit(
    query, context: ContextTypes.DEFAULT_TYPE, session: AsyncSession, user_id: int, trade_data: dict
) -> None:
    """Show close trade confirmation by editing message."""
    instrument = trade_data.get("instrument")
    direction = trade_data.get("direction")

    open_trades = await get_user_open_trades(session, user_id, instrument, direction)

    if not open_trades:
        await query.edit_message_text(
            f"No open trades found for {instrument or 'any instrument'}.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)
        return

    if len(open_trades) == 1:
        trade = open_trades[0]
        trade_data["trade_id_to_close"] = trade.id
        context.user_data[NATURAL_TRADE_KEY] = trade_data

        exit_price = Decimal(trade_data["exit_price"])
        pnl = calculate_pnl(
            trade.entry_price, exit_price, trade.direction.value, trade.lot_size
        )
        pnl_percent = calculate_pnl_percent(
            trade.entry_price, exit_price, trade.direction.value
        )

        pnl_formatted = format_currency(pnl, trade.account.currency, include_sign=True)
        pnl_indicator = "profit" if pnl > 0 else "loss" if pnl < 0 else "break-even"

        summary = (
            f"**Close Trade Confirmation**\n\n"
            f"Instrument: {trade.instrument}\n"
            f"Direction: {trade.direction.value.upper()}\n"
            f"Entry: {trade.entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Size: {trade.lot_size} lots\n\n"
            f"**P&L: {pnl_formatted} ({pnl_percent:+.2f}%)** ({pnl_indicator})\n\n"
            f"Confirm closing this trade?"
        )

        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_CLOSE
        await query.edit_message_text(
            summary,
            reply_markup=natural_trade_confirm_keyboard("close"),
            parse_mode="Markdown",
        )
    else:
        trades_list = [
            (t.id, t.instrument, t.direction.value, t.entry_price)
            for t in open_trades
        ]
        await query.edit_message_text(
            f"Multiple open {instrument or ''} trades found. Select which to close:",
            reply_markup=open_trade_select_keyboard(trades_list),
        )


async def _confirm_close_trade_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, session: AsyncSession, user_id: int, trade_data: dict
) -> None:
    """Show close trade confirmation by sending new message."""
    instrument = trade_data.get("instrument")
    direction = trade_data.get("direction")

    open_trades = await get_user_open_trades(session, user_id, instrument, direction)

    if not open_trades:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"No open trades found for {instrument or 'any instrument'}.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)
        return

    if len(open_trades) == 1:
        trade = open_trades[0]
        trade_data["trade_id_to_close"] = trade.id
        context.user_data[NATURAL_TRADE_KEY] = trade_data

        exit_price = Decimal(trade_data["exit_price"])
        pnl = calculate_pnl(
            trade.entry_price, exit_price, trade.direction.value, trade.lot_size
        )
        pnl_percent = calculate_pnl_percent(
            trade.entry_price, exit_price, trade.direction.value
        )

        pnl_formatted = format_currency(pnl, trade.account.currency, include_sign=True)
        pnl_indicator = "profit" if pnl > 0 else "loss" if pnl < 0 else "break-even"

        summary = (
            f"**Close Trade Confirmation**\n\n"
            f"Instrument: {trade.instrument}\n"
            f"Direction: {trade.direction.value.upper()}\n"
            f"Entry: {trade.entry_price}\n"
            f"Exit: {exit_price}\n"
            f"Size: {trade.lot_size} lots\n\n"
            f"**P&L: {pnl_formatted} ({pnl_percent:+.2f}%)** ({pnl_indicator})\n\n"
            f"Confirm closing this trade?"
        )

        context.user_data[NATURAL_TRADE_STATE_KEY] = STATE_CONFIRM_CLOSE
        await context.bot.send_message(
            chat_id=chat_id,
            text=summary,
            reply_markup=natural_trade_confirm_keyboard("close"),
            parse_mode="Markdown",
        )
    else:
        trades_list = [
            (t.id, t.instrument, t.direction.value, t.entry_price)
            for t in open_trades
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Multiple open {instrument or ''} trades found. Select which to close:",
            reply_markup=open_trade_select_keyboard(trades_list),
        )


async def _save_open_trade(
    query, context: ContextTypes.DEFAULT_TYPE, trade_data: dict
) -> None:
    """
    Save a new trade to the database.

    Args:
        query: The callback query.
        context: The callback context.
        trade_data: The trade data to save.
    """
    try:
        async with get_session() as session:
            account_id = trade_data["account_id"]

            # Get account for currency
            result = await session.execute(
                select(Account).where(Account.id == account_id)
            )
            account = result.scalar_one_or_none()
            if not account:
                await query.edit_message_text(
                    "Account not found. Please try again.",
                    reply_markup=back_to_menu_keyboard(),
                )
                _clear_natural_trade_state(context)
                return

            # Create trade
            direction = (
                TradeDirection.LONG
                if trade_data["direction"] == "long"
                else TradeDirection.SHORT
            )

            trade = Trade(
                account_id=account_id,
                instrument=trade_data["instrument"].upper(),
                direction=direction,
                entry_price=Decimal(trade_data["entry_price"]),
                lot_size=Decimal(trade_data.get("lot_size", "1")),
                status=TradeStatus.OPEN,
                sl_price=Decimal(trade_data["sl_price"]) if trade_data.get("sl_price") else None,
                tp_price=Decimal(trade_data["tp_price"]) if trade_data.get("tp_price") else None,
                opened_at=datetime.utcnow(),
            )
            session.add(trade)
            await session.flush()

            # Add tags if any
            if trade_data.get("tags"):
                tags = await get_or_create_tags(session, trade_data["tags"])
                for tag in tags:
                    trade_tag = TradeTag(trade_id=trade.id, tag_id=tag.id)
                    session.add(trade_tag)

            await session.commit()

            logger.info(
                "Natural trade opened",
                trade_id=trade.id,
                instrument=trade.instrument,
                direction=direction.value,
            )

            await query.edit_message_text(
                f"Trade opened successfully!\n\n"
                f"ID: #{trade.id}\n"
                f"{trade.instrument} {direction.value.upper()} @ {trade.entry_price}\n"
                f"Size: {trade.lot_size} lots",
                reply_markup=back_to_menu_keyboard(),
            )

            _clear_natural_trade_state(context)

    except Exception as e:
        logger.error("Error saving open trade", error=str(e))
        await query.edit_message_text(
            "An error occurred while saving the trade. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)


async def _save_close_trade(
    query, context: ContextTypes.DEFAULT_TYPE, trade_data: dict
) -> None:
    """
    Close an existing trade.

    Args:
        query: The callback query.
        context: The callback context.
        trade_data: The trade data including trade_id_to_close and exit_price.
    """
    try:
        async with get_session() as session:
            trade_id = trade_data["trade_id_to_close"]
            exit_price = Decimal(trade_data["exit_price"])

            result = await session.execute(
                select(Trade)
                .where(Trade.id == trade_id)
                .options(selectinload(Trade.account))
            )
            trade = result.scalar_one_or_none()

            if not trade:
                await query.edit_message_text(
                    "Trade not found. Please try again.",
                    reply_markup=back_to_menu_keyboard(),
                )
                _clear_natural_trade_state(context)
                return

            # Calculate P&L
            pnl = calculate_pnl(
                trade.entry_price, exit_price, trade.direction.value, trade.lot_size
            )
            pnl_percent = calculate_pnl_percent(
                trade.entry_price, exit_price, trade.direction.value
            )

            # Update trade
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.pnl_percent = pnl_percent
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.utcnow()

            # Update account balance
            trade.account.current_balance += pnl

            await session.commit()

            logger.info(
                "Natural trade closed",
                trade_id=trade.id,
                pnl=str(pnl),
            )

            pnl_formatted = format_currency(pnl, trade.account.currency, include_sign=True)
            pnl_indicator = "profit" if pnl > 0 else "loss" if pnl < 0 else "break-even"

            await query.edit_message_text(
                f"Trade closed successfully!\n\n"
                f"ID: #{trade.id}\n"
                f"{trade.instrument} {trade.direction.value.upper()}\n"
                f"Entry: {trade.entry_price} -> Exit: {exit_price}\n\n"
                f"**P&L: {pnl_formatted} ({pnl_percent:+.2f}%)** ({pnl_indicator})",
                reply_markup=back_to_menu_keyboard(),
                parse_mode="Markdown",
            )

            _clear_natural_trade_state(context)

    except Exception as e:
        logger.error("Error closing trade", error=str(e))
        await query.edit_message_text(
            "An error occurred while closing the trade. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        _clear_natural_trade_state(context)


def _clear_natural_trade_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all natural trade input state from context."""
    if NATURAL_TRADE_KEY in context.user_data:
        del context.user_data[NATURAL_TRADE_KEY]
    if NATURAL_TRADE_STATE_KEY in context.user_data:
        del context.user_data[NATURAL_TRADE_STATE_KEY]


# Required import for InvalidOperation in type hints
from decimal import InvalidOperation
