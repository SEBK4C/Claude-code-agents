"""
Trade entry and management handlers for the Telegram Trade Journal Bot.

This module provides:
- 12-step trade entry wizard (ConversationHandler)
- Trade listing (open and closed)
- Trade detail views
- Close trade flow
- Trade editing and deletion
"""

import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import get_logger
from database.db import get_session
from database.models import (
    Account,
    Strategy,
    Tag,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
)
from handlers.accounts import get_user_by_telegram_id
from utils.helpers import (
    calculate_pnl,
    calculate_pnl_percent,
    format_currency,
    format_datetime,
    format_trade_summary,
)
from services.pnl_service import get_pnl_service
from services.price_service import get_price_service
from utils.keyboards import (
    back_cancel_keyboard,
    back_to_menu_keyboard,
    confirmation_keyboard,
    direction_keyboard,
    instrument_keyboard,
    pagination_keyboard,
    strategy_select_keyboard,
    tag_select_keyboard,
)
from utils.validation import validate_lot_size, validate_price, validate_sl_tp, validate_instrument

logger = get_logger(__name__)

# Conversation states for 12-step trade wizard
(
    SELECT_ACCOUNT,
    SELECT_INSTRUMENT,
    SELECT_DIRECTION,
    ENTER_ENTRY,
    ENTER_SL,
    ENTER_TP,
    ENTER_LOT,
    SELECT_STRATEGY,
    SELECT_TAGS,
    ENTER_NOTES,
    UPLOAD_SCREENSHOT,
    CONFIRM,
) = range(12)

# Close trade states
CLOSE_ENTER_EXIT = 20
CLOSE_CONFIRM = 21

# Edit trade states
EDIT_SL = 30
EDIT_TP = 31
EDIT_NOTES = 32
EDIT_INSTRUMENT = 33
EDIT_ENTRY = 34
EDIT_LOTSIZE = 35
EDIT_EXIT = 36
EDIT_SCREENSHOT = 37
EDIT_TAGS = 38
EDIT_STRATEGY = 39

# Wizard data keys
TRADE_WIZARD_KEY = "trade_wizard"
CLOSE_WIZARD_KEY = "close_wizard"
EDIT_WIZARD_KEY = "edit_wizard"

# Pagination settings
TRADES_PER_PAGE = 5

# ============================================================================
# TRADE WIZARD UX - STEP TRACKING AND CONTEXT DISPLAY (F2)
# ============================================================================

# Trade wizard step definitions with metadata for UX
TRADE_STEPS: dict[str, dict] = {
    "account": {
        "number": 1,
        "total": 12,
        "label": "Select Account",
        "input_type": "buttons",
        "skippable": False,
    },
    "instrument": {
        "number": 2,
        "total": 12,
        "label": "Select Instrument",
        "input_type": "buttons",
        "skippable": False,
    },
    "direction": {
        "number": 3,
        "total": 12,
        "label": "Select Direction",
        "input_type": "buttons",
        "skippable": False,
    },
    "entry_price": {
        "number": 4,
        "total": 12,
        "label": "Entry Price",
        "input_type": "text",
        "format_hint": "e.g. `18500.50`",
        "example": "18500.50",
        "skippable": False,
    },
    "sl_price": {
        "number": 5,
        "total": 12,
        "label": "Stop Loss",
        "input_type": "text",
        "format_hint": "e.g. `18400.00`",
        "example": "18400.00",
        "skippable": True,
    },
    "tp_price": {
        "number": 6,
        "total": 12,
        "label": "Take Profit",
        "input_type": "text",
        "format_hint": "e.g. `18700.00`",
        "example": "18700.00",
        "skippable": True,
    },
    "lot_size": {
        "number": 7,
        "total": 12,
        "label": "Lot Size",
        "input_type": "text",
        "format_hint": "e.g. `0.50` or `1.0`",
        "example": "0.50",
        "skippable": False,
    },
    "strategy": {
        "number": 8,
        "total": 12,
        "label": "Strategy",
        "input_type": "buttons",
        "skippable": True,
    },
    "tags": {
        "number": 9,
        "total": 12,
        "label": "Tags",
        "input_type": "buttons",
        "skippable": True,
    },
    "notes": {
        "number": 10,
        "total": 12,
        "label": "Notes",
        "input_type": "text",
        "format_hint": "Any text",
        "example": "Strong breakout with volume",
        "skippable": True,
    },
    "screenshot": {
        "number": 11,
        "total": 12,
        "label": "Screenshot",
        "input_type": "photo",
        "skippable": True,
    },
    "confirm": {
        "number": 12,
        "total": 12,
        "label": "Confirm Trade",
        "input_type": "buttons",
        "skippable": False,
    },
}


def _build_step_header(step_key: str) -> str:
    """
    Build a formatted step header for wizard prompts.

    Args:
        step_key: The key identifying the current step (e.g., "entry_price").

    Returns:
        str: Formatted header like "*Step 4/12 - Entry Price*"
    """
    step_info = TRADE_STEPS.get(step_key, {})
    step_num = step_info.get("number", 0)
    total = step_info.get("total", 12)
    label = step_info.get("label", "Unknown Step")
    return f"*Step {step_num}/{total} - {label}*"


def _build_context_display(wizard_data: dict) -> str:
    """
    Build a context display showing accumulated trade data.

    Args:
        wizard_data: The trade wizard data dictionary.

    Returns:
        str: Formatted context string showing current trade details.
    """
    parts = []

    # Instrument and direction are the core context
    instrument = wizard_data.get("instrument")
    direction = wizard_data.get("direction")

    if instrument and direction:
        # Use emoji for direction indicator
        dir_emoji = "+" if direction == "LONG" else "-" if direction == "SHORT" else ""
        parts.append(f"_{instrument} | {dir_emoji}{direction}_")
    elif instrument:
        parts.append(f"_{instrument}_")

    # Build price context line
    price_parts = []
    entry_price = wizard_data.get("entry_price")
    sl_price = wizard_data.get("sl_price")
    tp_price = wizard_data.get("tp_price")
    lot_size = wizard_data.get("lot_size")

    if entry_price:
        price_parts.append(f"Entry: {entry_price}")
    if sl_price:
        price_parts.append(f"SL: {sl_price}")
    if tp_price:
        price_parts.append(f"TP: {tp_price}")
    if lot_size:
        price_parts.append(f"Size: {lot_size}")

    if price_parts:
        parts.append(" | ".join(price_parts))

    return "\n".join(parts) if parts else ""


def _build_text_input_prompt(
    step_key: str,
    wizard_data: dict,
    field_description: str,
    current_value: Optional[str] = None,
    validation_hint: Optional[str] = None,
) -> str:
    """
    Build a complete prompt for text input steps.

    Args:
        step_key: The step key (e.g., "entry_price").
        wizard_data: The trade wizard data dictionary.
        field_description: Description of what to enter.
        current_value: Current value if editing.
        validation_hint: Optional hint about validation rules.

    Returns:
        str: Complete formatted prompt message.
    """
    step_info = TRADE_STEPS.get(step_key, {})
    format_hint = step_info.get("format_hint", "")

    lines = []

    # Header
    lines.append(_build_step_header(step_key))

    # Context display
    context = _build_context_display(wizard_data)
    if context:
        lines.append(context)

    # Empty line for visual separation
    lines.append("")

    # Input prompt with format hint
    if format_hint:
        lines.append(f"{field_description} ({format_hint}):")
    else:
        lines.append(f"{field_description}:")

    # Current value if editing
    if current_value:
        lines.append(f"Current: `{current_value}`")

    # Validation hint if provided
    if validation_hint:
        lines.append(f"\n{validation_hint}")

    return "\n".join(lines)


def _build_validation_error(
    step_key: str,
    wizard_data: dict,
    error_message: str,
    retry_hint: str,
) -> str:
    """
    Build a helpful validation error message.

    Args:
        step_key: The step key for context.
        wizard_data: The trade wizard data dictionary.
        error_message: The specific validation error.
        retry_hint: Hint about correct format.

    Returns:
        str: Formatted error message.
    """
    lines = []

    # Warning emoji and error
    lines.append(f"! {error_message}")
    lines.append("")

    # Step header reminder
    lines.append(_build_step_header(step_key))

    # Context display
    context = _build_context_display(wizard_data)
    if context:
        lines.append(context)

    lines.append("")
    lines.append(retry_hint)

    return "\n".join(lines)


def _build_sl_validation_error(
    entry_price: Decimal,
    sl_price: Decimal,
    direction: str,
) -> str:
    """
    Build a specific validation error for stop-loss position.

    Args:
        entry_price: The entry price.
        sl_price: The attempted stop-loss price.
        direction: Trade direction ("LONG" or "SHORT").

    Returns:
        str: Formatted error message with clear explanation.
    """
    if direction == "LONG":
        return (
            f"! {direction} trade: SL ({sl_price}) should be *below* entry ({entry_price}).\n"
            f"Your stop-loss must protect against the trade moving against you."
        )
    else:
        return (
            f"! {direction} trade: SL ({sl_price}) should be *above* entry ({entry_price}).\n"
            f"Your stop-loss must protect against the trade moving against you."
        )


def _build_tp_validation_error(
    entry_price: Decimal,
    tp_price: Decimal,
    direction: str,
) -> str:
    """
    Build a specific validation error for take-profit position.

    Args:
        entry_price: The entry price.
        tp_price: The attempted take-profit price.
        direction: Trade direction ("LONG" or "SHORT").

    Returns:
        str: Formatted error message with clear explanation.
    """
    if direction == "LONG":
        return (
            f"! {direction} trade: TP ({tp_price}) should be *above* entry ({entry_price}).\n"
            f"Your take-profit should be where you expect the price to go."
        )
    else:
        return (
            f"! {direction} trade: TP ({tp_price}) should be *below* entry ({entry_price}).\n"
            f"Your take-profit should be where you expect the price to go."
        )


def _step_keyboard(include_skip: bool = False) -> InlineKeyboardMarkup:
    """
    Create a standard step keyboard with Skip and Cancel options.

    This is the enhanced version of trade_wizard_keyboard with clearer icons.

    Args:
        include_skip: Whether to include a Skip button.

    Returns:
        InlineKeyboardMarkup: Navigation keyboard.
    """
    keyboard = []

    # Row 1: Skip (optional) and Cancel
    row1 = []
    if include_skip:
        row1.append(InlineKeyboardButton(">> Skip", callback_data="tw_skip"))
    row1.append(InlineKeyboardButton("X Cancel", callback_data="tw_cancel"))
    keyboard.append(row1)

    # Row 2: Back button (always present)
    keyboard.append([
        InlineKeyboardButton("<< Back", callback_data="tw_back"),
    ])

    return InlineKeyboardMarkup(keyboard)


def trade_wizard_keyboard(include_skip: bool = False) -> InlineKeyboardMarkup:
    """
    Create a navigation keyboard for the trade wizard.

    Args:
        include_skip: Whether to include a Skip button.

    Returns:
        InlineKeyboardMarkup: Navigation keyboard.
    """
    buttons = []
    if include_skip:
        buttons.append(InlineKeyboardButton("Skip", callback_data="tw_skip"))

    keyboard = [[*buttons]] if buttons else []
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="tw_back"),
        InlineKeyboardButton("Cancel", callback_data="tw_cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


def trade_wizard_account_keyboard(
    accounts: list[tuple[int, str]],
) -> InlineKeyboardMarkup:
    """
    Create account selection keyboard for trade wizard.

    Args:
        accounts: List of (account_id, account_name) tuples.

    Returns:
        InlineKeyboardMarkup: Account selection keyboard.
    """
    keyboard = []

    for account_id, account_name in accounts:
        keyboard.append([
            InlineKeyboardButton(
                account_name,
                callback_data=f"tw_acc_{account_id}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton("Cancel", callback_data="tw_cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


def trade_detail_keyboard(
    trade_id: int, is_open: bool = True
) -> InlineKeyboardMarkup:
    """
    Create a keyboard for trade detail view.

    Args:
        trade_id: The trade ID.
        is_open: Whether the trade is still open.

    Returns:
        InlineKeyboardMarkup: Trade detail action keyboard.
    """
    keyboard = []

    if is_open:
        keyboard.append([
            InlineKeyboardButton("Close Trade", callback_data=f"trade_close_{trade_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("Edit Trade", callback_data=f"trade_edit_{trade_id}"),
    ])
    keyboard.append([
        InlineKeyboardButton("Delete", callback_data=f"trade_delete_{trade_id}"),
    ])
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="menu_open_trades" if is_open else "menu_history"),
    ])

    return InlineKeyboardMarkup(keyboard)


def edit_field_keyboard(
    trade_id: int, is_open: bool = True
) -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting which field to edit.

    Args:
        trade_id: The trade ID.
        is_open: Whether the trade is still open.

    Returns:
        InlineKeyboardMarkup: Edit field selection keyboard.
    """
    keyboard = []

    # Core trade fields - always editable
    keyboard.append([
        InlineKeyboardButton("Instrument", callback_data=f"edit_field_instrument_{trade_id}"),
        InlineKeyboardButton("Direction", callback_data=f"edit_field_direction_{trade_id}"),
    ])
    keyboard.append([
        InlineKeyboardButton("Entry Price", callback_data=f"edit_field_entry_{trade_id}"),
        InlineKeyboardButton("Lot Size", callback_data=f"edit_field_lotsize_{trade_id}"),
    ])

    # SL/TP - common edits
    keyboard.append([
        InlineKeyboardButton("Stop Loss", callback_data=f"trade_edit_sl_{trade_id}"),
        InlineKeyboardButton("Take Profit", callback_data=f"trade_edit_tp_{trade_id}"),
    ])

    # Exit price - only for closed trades
    if not is_open:
        keyboard.append([
            InlineKeyboardButton("Exit Price", callback_data=f"edit_field_exit_{trade_id}"),
        ])

    # Strategy and Tags
    keyboard.append([
        InlineKeyboardButton("Strategy", callback_data=f"edit_field_strategy_{trade_id}"),
        InlineKeyboardButton("Tags", callback_data=f"edit_field_tags_{trade_id}"),
    ])

    # Notes and Screenshot
    keyboard.append([
        InlineKeyboardButton("Notes", callback_data=f"trade_edit_notes_{trade_id}"),
        InlineKeyboardButton("Screenshot", callback_data=f"edit_field_screenshot_{trade_id}"),
    ])

    # Back button
    keyboard.append([
        InlineKeyboardButton("Back", callback_data=f"trade_detail_{trade_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def open_trades_keyboard(
    trades: list[tuple[int, str, str, Decimal, str]],
    filter_account_id: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for open trades list.

    Args:
        trades: List of (trade_id, instrument, direction, entry_price, pnl_indicator) tuples.
        filter_account_id: Optional account ID to filter by.

    Returns:
        InlineKeyboardMarkup: Open trades list keyboard.
    """
    keyboard = []

    for trade_id, instrument, direction, entry_price, pnl_indicator in trades:
        label = f"{instrument} {direction.upper()} @ {entry_price} {pnl_indicator}"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"trade_detail_{trade_id}"),
        ])

    # Filter option
    if filter_account_id:
        keyboard.append([
            InlineKeyboardButton("Clear Filter", callback_data="open_trades_filter_clear"),
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("Filter by Account", callback_data="open_trades_filter"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_home"),
    ])

    return InlineKeyboardMarkup(keyboard)


async def get_user_strategies(
    session: AsyncSession, user_id: int
) -> list[tuple[int, str]]:
    """
    Get all strategies for a user.

    Args:
        session: The database session.
        user_id: The internal user ID.

    Returns:
        list: List of (strategy_id, name) tuples.
    """
    result = await session.execute(
        select(Strategy.id, Strategy.name)
        .where(Strategy.user_id == user_id)
        .order_by(Strategy.name)
    )
    return [(row[0], row[1]) for row in result.fetchall()]


async def get_all_tags(session: AsyncSession) -> list[tuple[int, str]]:
    """
    Get all available tags.

    Args:
        session: The database session.

    Returns:
        list: List of (tag_id, name) tuples.
    """
    result = await session.execute(
        select(Tag.id, Tag.name).order_by(Tag.name)
    )
    return [(row[0], row[1]) for row in result.fetchall()]


async def get_user_accounts(
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


def build_wizard_progress(step: int, step_name: str) -> str:
    """
    Build the wizard progress indicator string.

    Args:
        step: Current step number (1-12).
        step_name: Name of the current step.

    Returns:
        str: Formatted progress string.
    """
    return f"Step {step}/12: {step_name}"


def _recalculate_pnl(trade: Trade) -> None:
    """
    Recalculate and update P&L fields for a closed trade.

    This should be called whenever entry_price, exit_price, lot_size,
    or direction changes on a closed trade.

    Args:
        trade: The Trade object to recalculate. Must have exit_price set.
    """
    if trade.exit_price is None:
        # Cannot calculate P&L without exit price
        return

    # Calculate absolute P&L
    trade.pnl = calculate_pnl(
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        direction=trade.direction.value,
        lot_size=trade.lot_size,
    )

    # Calculate percentage P&L
    trade.pnl_percent = calculate_pnl_percent(
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        direction=trade.direction.value,
    )


# ============================================================================
# TRADE ENTRY WIZARD - STEPS 1-4 (F11)
# ============================================================================


async def start_trade_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the trade entry wizard (Step 1: Select Account).

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

            accounts = await get_user_accounts(session, user.id)

            if not accounts:
                await query.edit_message_text(
                    "You need to create a trading account first.\n\n"
                    "Go to Accounts > Create Account to set one up.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Initialize wizard state
            context.user_data[TRADE_WIZARD_KEY] = {
                "user_id": user.id,
                "step_history": [],
            }

            progress = build_wizard_progress(1, "Select Account")
            await query.edit_message_text(
                f"{progress}\n\n"
                "Select the trading account for this trade:",
                reply_markup=trade_wizard_account_keyboard(accounts),
            )

            return SELECT_ACCOUNT

    except Exception as e:
        logger.error("Error starting trade wizard", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_account_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle account selection (Step 1 -> Step 2: Select Instrument).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return SELECT_ACCOUNT

    await query.answer()

    # Parse account ID
    account_id_str = query.data.replace("tw_acc_", "")
    try:
        account_id = int(account_id_str)
    except ValueError:
        return SELECT_ACCOUNT

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["account_id"] = account_id
    wizard_data["step_history"].append(SELECT_ACCOUNT)

    progress = build_wizard_progress(2, "Select Instrument")
    await query.edit_message_text(
        f"{progress}\n\n"
        "Select the trading instrument:",
        reply_markup=instrument_keyboard(),
    )

    return SELECT_INSTRUMENT


async def handle_instrument_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle instrument selection (Step 2 -> Step 3: Select Direction).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return SELECT_INSTRUMENT

    await query.answer()

    if query.data == "instrument_custom":
        await query.edit_message_text(
            "Enter the custom instrument symbol (e.g., AAPL, BTCUSD):",
            reply_markup=trade_wizard_keyboard(),
        )
        return SELECT_INSTRUMENT

    # Parse instrument
    instrument = query.data.replace("instrument_", "")

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["instrument"] = instrument
    wizard_data["step_history"].append(SELECT_INSTRUMENT)

    progress = build_wizard_progress(3, "Select Direction")
    await query.edit_message_text(
        f"{progress}\n\n"
        "Select the trade direction:",
        reply_markup=direction_keyboard(),
    )

    return SELECT_DIRECTION


async def handle_instrument_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle custom instrument text input.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return SELECT_INSTRUMENT

    instrument = update.message.text.strip().upper()

    if len(instrument) < 2 or len(instrument) > 20:
        await update.message.reply_text(
            "Invalid instrument. Please enter a 2-20 character symbol.",
            reply_markup=trade_wizard_keyboard(),
        )
        return SELECT_INSTRUMENT

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["instrument"] = instrument
    wizard_data["step_history"].append(SELECT_INSTRUMENT)

    progress = build_wizard_progress(3, "Select Direction")
    await update.message.reply_text(
        f"{progress}\n\n"
        "Select the trade direction:",
        reply_markup=direction_keyboard(),
    )

    return SELECT_DIRECTION


async def handle_direction_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle direction selection (Step 3 -> Step 4: Enter Entry Price).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return SELECT_DIRECTION

    await query.answer()

    # Parse direction
    direction_str = query.data.replace("direction_", "").upper()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["direction"] = direction_str
    wizard_data["step_history"].append(SELECT_DIRECTION)

    # Build enhanced prompt with step header and context
    prompt = _build_text_input_prompt(
        step_key="entry_price",
        wizard_data=wizard_data,
        field_description="Enter entry price",
    )

    await query.edit_message_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=False),
        parse_mode="Markdown",
    )

    return ENTER_ENTRY


async def handle_entry_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle entry price input (Step 4 -> Step 5: Enter SL).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return ENTER_ENTRY

    price_input = update.message.text.strip()
    validation = validate_price(price_input)
    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})

    if not validation.is_valid:
        # Build helpful validation error with context
        error_msg = _build_validation_error(
            step_key="entry_price",
            wizard_data=wizard_data,
            error_message=validation.error or "Invalid price format",
            retry_hint="Enter a number like `18500.50` or `1.2345`:",
        )
        await update.message.reply_text(
            error_msg,
            reply_markup=_step_keyboard(include_skip=False),
            parse_mode="Markdown",
        )
        return ENTER_ENTRY

    wizard_data["entry_price"] = validation.value
    wizard_data["step_history"].append(ENTER_ENTRY)

    # Build enhanced prompt for SL with direction-aware hint
    direction = wizard_data.get("direction", "LONG")
    hint = "below" if direction == "LONG" else "above"

    prompt = _build_text_input_prompt(
        step_key="sl_price",
        wizard_data=wizard_data,
        field_description=f"Enter stop-loss price ({hint} entry for {direction})",
        validation_hint="Press *>> Skip* if you don't want to set a stop-loss.",
    )

    await update.message.reply_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )

    return ENTER_SL


# ============================================================================
# TRADE ENTRY WIZARD - STEPS 5-8 (F12)
# ============================================================================


async def handle_sl_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle stop-loss price input (Step 5 -> Step 6: Enter TP).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return ENTER_SL

    sl_input = update.message.text.strip()
    validation = validate_price(sl_input)
    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    entry_price = wizard_data.get("entry_price")
    direction = wizard_data.get("direction", "LONG")

    if not validation.is_valid:
        # Build helpful validation error with context
        error_msg = _build_validation_error(
            step_key="sl_price",
            wizard_data=wizard_data,
            error_message=validation.error or "Invalid price format",
            retry_hint="Enter a number like `18400.00` or press *>> Skip*:",
        )
        await update.message.reply_text(
            error_msg,
            reply_markup=_step_keyboard(include_skip=True),
            parse_mode="Markdown",
        )
        return ENTER_SL

    # Validate SL position relative to entry and direction
    sl_validation = validate_sl_tp(entry_price, validation.value, None, direction)
    if not sl_validation.is_valid:
        # Build specific SL validation error with clear explanation
        error_msg = _build_sl_validation_error(
            entry_price=entry_price,
            sl_price=validation.value,
            direction=direction,
        )
        await update.message.reply_text(
            error_msg + "\n\nEnter a valid stop-loss price or press *>> Skip*:",
            reply_markup=_step_keyboard(include_skip=True),
            parse_mode="Markdown",
        )
        return ENTER_SL

    wizard_data["sl_price"] = validation.value
    wizard_data["step_history"].append(ENTER_SL)

    return await _proceed_to_tp(update, context, wizard_data)


async def handle_sl_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping stop-loss entry.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return ENTER_SL

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["sl_price"] = None
    wizard_data["step_history"].append(ENTER_SL)

    return await _proceed_to_tp_callback(query, context, wizard_data)


async def _proceed_to_tp(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to TP entry from message handler."""
    direction = wizard_data.get("direction", "LONG")
    hint = "above" if direction == "LONG" else "below"

    prompt = _build_text_input_prompt(
        step_key="tp_price",
        wizard_data=wizard_data,
        field_description=f"Enter take-profit price ({hint} entry for {direction})",
        validation_hint="Press *>> Skip* if you don't want to set a take-profit.",
    )

    await update.message.reply_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )

    return ENTER_TP


async def _proceed_to_tp_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to TP entry from callback handler."""
    direction = wizard_data.get("direction", "LONG")
    hint = "above" if direction == "LONG" else "below"

    prompt = _build_text_input_prompt(
        step_key="tp_price",
        wizard_data=wizard_data,
        field_description=f"Enter take-profit price ({hint} entry for {direction})",
        validation_hint="Press *>> Skip* if you don't want to set a take-profit.",
    )

    await query.edit_message_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )

    return ENTER_TP


async def handle_tp_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle take-profit price input (Step 6 -> Step 7: Enter Lot Size).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return ENTER_TP

    tp_input = update.message.text.strip()
    validation = validate_price(tp_input)
    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    entry_price = wizard_data.get("entry_price")
    direction = wizard_data.get("direction", "LONG")

    if not validation.is_valid:
        # Build helpful validation error with context
        error_msg = _build_validation_error(
            step_key="tp_price",
            wizard_data=wizard_data,
            error_message=validation.error or "Invalid price format",
            retry_hint="Enter a number like `18700.00` or press *>> Skip*:",
        )
        await update.message.reply_text(
            error_msg,
            reply_markup=_step_keyboard(include_skip=True),
            parse_mode="Markdown",
        )
        return ENTER_TP

    # Validate TP position relative to entry and direction
    tp_validation = validate_sl_tp(entry_price, None, validation.value, direction)
    if not tp_validation.is_valid:
        # Build specific TP validation error with clear explanation
        error_msg = _build_tp_validation_error(
            entry_price=entry_price,
            tp_price=validation.value,
            direction=direction,
        )
        await update.message.reply_text(
            error_msg + "\n\nEnter a valid take-profit price or press *>> Skip*:",
            reply_markup=_step_keyboard(include_skip=True),
            parse_mode="Markdown",
        )
        return ENTER_TP

    wizard_data["tp_price"] = validation.value
    wizard_data["step_history"].append(ENTER_TP)

    return await _proceed_to_lot_size(update, context, wizard_data)


async def handle_tp_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping take-profit entry.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return ENTER_TP

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["tp_price"] = None
    wizard_data["step_history"].append(ENTER_TP)

    return await _proceed_to_lot_size_callback(query, context, wizard_data)


async def _proceed_to_lot_size(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to lot size entry from message handler."""
    prompt = _build_text_input_prompt(
        step_key="lot_size",
        wizard_data=wizard_data,
        field_description="Enter lot size (min 0.01)",
    )

    await update.message.reply_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=False),
        parse_mode="Markdown",
    )

    return ENTER_LOT


async def _proceed_to_lot_size_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to lot size entry from callback handler."""
    prompt = _build_text_input_prompt(
        step_key="lot_size",
        wizard_data=wizard_data,
        field_description="Enter lot size (min 0.01)",
    )

    await query.edit_message_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=False),
        parse_mode="Markdown",
    )

    return ENTER_LOT


async def handle_lot_size(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle lot size input (Step 7 -> Step 8: Select Strategy).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return ENTER_LOT

    lot_input = update.message.text.strip()
    validation = validate_lot_size(lot_input)
    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})

    if not validation.is_valid:
        # Build helpful validation error with context
        error_msg = _build_validation_error(
            step_key="lot_size",
            wizard_data=wizard_data,
            error_message=validation.error or "Invalid lot size format",
            retry_hint="Enter a number like `0.50` or `1.0` (min 0.01, max 1000):",
        )
        await update.message.reply_text(
            error_msg,
            reply_markup=_step_keyboard(include_skip=False),
            parse_mode="Markdown",
        )
        return ENTER_LOT

    wizard_data["lot_size"] = validation.value
    wizard_data["step_history"].append(ENTER_LOT)

    # Get user's strategies
    telegram_id = update.effective_user.id
    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if user:
                strategies = await get_user_strategies(session, user.id)
            else:
                strategies = []

        # Build enhanced prompt for strategy selection
        header = _build_step_header("strategy")
        context_display = _build_context_display(wizard_data)

        prompt = f"{header}\n{context_display}\n\nSelect a trading strategy for this trade:\n\nPress *Skip* if you don't want to assign a strategy."

        await update.message.reply_text(
            prompt,
            reply_markup=strategy_select_keyboard(strategies, include_skip=True),
            parse_mode="Markdown",
        )

        return SELECT_STRATEGY

    except Exception as e:
        logger.error("Error loading strategies", error=str(e))
        # Proceed without strategy selection
        wizard_data["strategy_id"] = None
        return await _proceed_to_tags(update, context, wizard_data)


# ============================================================================
# TRADE ENTRY WIZARD - STEPS 9-12 (F13)
# ============================================================================


async def handle_strategy_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle strategy selection (Step 8 -> Step 9: Select Tags).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return SELECT_STRATEGY

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})

    if query.data == "strategy_skip":
        wizard_data["strategy_id"] = None
    else:
        strategy_id_str = query.data.replace("strategy_select_", "")
        try:
            wizard_data["strategy_id"] = int(strategy_id_str)
        except ValueError:
            return SELECT_STRATEGY

    wizard_data["step_history"].append(SELECT_STRATEGY)

    return await _proceed_to_tags_callback(query, context, wizard_data)


async def _proceed_to_tags(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to tags from message handler."""
    wizard_data["selected_tags"] = set()

    try:
        async with get_session() as session:
            tags = await get_all_tags(session)

        progress = build_wizard_progress(9, "Select Tags")
        await update.message.reply_text(
            f"{progress}\n\n"
            "Select tags for this trade (tap to toggle):\n\n"
            "Press Done when finished.",
            reply_markup=tag_select_keyboard(tags, wizard_data["selected_tags"]),
        )

        return SELECT_TAGS

    except Exception as e:
        logger.error("Error loading tags", error=str(e))
        # Proceed without tags
        wizard_data["selected_tags"] = set()
        return await _proceed_to_notes(update, context, wizard_data)


async def _proceed_to_tags_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to tags from callback handler."""
    wizard_data["selected_tags"] = set()

    try:
        async with get_session() as session:
            tags = await get_all_tags(session)

        progress = build_wizard_progress(9, "Select Tags")
        await query.edit_message_text(
            f"{progress}\n\n"
            "Select tags for this trade (tap to toggle):\n\n"
            "Press Done when finished.",
            reply_markup=tag_select_keyboard(tags, wizard_data["selected_tags"]),
        )

        return SELECT_TAGS

    except Exception as e:
        logger.error("Error loading tags", error=str(e))
        # Proceed without tags
        wizard_data["selected_tags"] = set()
        return await _proceed_to_notes_callback(query, context, wizard_data)


async def handle_tag_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle tag toggle in multi-select.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The current conversation state (stay on tags).
    """
    query = update.callback_query
    if not query or not query.data:
        return SELECT_TAGS

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})

    if query.data == "tags_done":
        wizard_data["step_history"].append(SELECT_TAGS)
        return await _proceed_to_notes_callback(query, context, wizard_data)

    if query.data == "tags_clear":
        wizard_data["selected_tags"] = set()
        try:
            async with get_session() as session:
                tags = await get_all_tags(session)
            progress = build_wizard_progress(9, "Select Tags")
            await query.edit_message_text(
                f"{progress}\n\n"
                "Select tags for this trade (tap to toggle):\n\n"
                "Press Done when finished.",
                reply_markup=tag_select_keyboard(tags, wizard_data["selected_tags"]),
            )
        except Exception:
            pass
        return SELECT_TAGS

    # Toggle the tag
    tag_id_str = query.data.replace("tag_toggle_", "")
    try:
        tag_id = int(tag_id_str)
        if tag_id in wizard_data.get("selected_tags", set()):
            wizard_data["selected_tags"].discard(tag_id)
        else:
            wizard_data.setdefault("selected_tags", set()).add(tag_id)
    except ValueError:
        return SELECT_TAGS

    # Refresh the keyboard
    try:
        async with get_session() as session:
            tags = await get_all_tags(session)
        progress = build_wizard_progress(9, "Select Tags")
        await query.edit_message_text(
            f"{progress}\n\n"
            "Select tags for this trade (tap to toggle):\n\n"
            "Press Done when finished.",
            reply_markup=tag_select_keyboard(tags, wizard_data["selected_tags"]),
        )
    except Exception:
        pass

    return SELECT_TAGS


async def _proceed_to_notes(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to notes from message handler."""
    prompt = _build_text_input_prompt(
        step_key="notes",
        wizard_data=wizard_data,
        field_description="Enter any notes for this trade",
        validation_hint="Press *>> Skip* to continue without notes.",
    )

    await update.message.reply_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )
    return ENTER_NOTES


async def _proceed_to_notes_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to notes from callback handler."""
    prompt = _build_text_input_prompt(
        step_key="notes",
        wizard_data=wizard_data,
        field_description="Enter any notes for this trade",
        validation_hint="Press *>> Skip* to continue without notes.",
    )

    await query.edit_message_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )
    return ENTER_NOTES


async def handle_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle notes input (Step 10 -> Step 11: Upload Screenshot).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return ENTER_NOTES

    notes = update.message.text.strip()

    # Basic validation - notes too long
    if len(notes) > 2000:
        wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
        error_msg = _build_validation_error(
            step_key="notes",
            wizard_data=wizard_data,
            error_message="Notes are too long (max 2000 characters)",
            retry_hint=f"Your notes are {len(notes)} characters. Please shorten them or press *>> Skip*:",
        )
        await update.message.reply_text(
            error_msg,
            reply_markup=_step_keyboard(include_skip=True),
            parse_mode="Markdown",
        )
        return ENTER_NOTES

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["notes"] = notes
    wizard_data["step_history"].append(ENTER_NOTES)

    return await _proceed_to_screenshot(update, context, wizard_data)


async def handle_notes_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping notes entry.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return ENTER_NOTES

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["notes"] = None
    wizard_data["step_history"].append(ENTER_NOTES)

    return await _proceed_to_screenshot_callback(query, context, wizard_data)


async def _proceed_to_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to screenshot from message handler."""
    header = _build_step_header("screenshot")
    context_display = _build_context_display(wizard_data)

    prompt = f"{header}\n{context_display}\n\nUpload a screenshot of the trade chart:\n\nPress *>> Skip* to continue without a screenshot."

    await update.message.reply_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )
    return UPLOAD_SCREENSHOT


async def _proceed_to_screenshot_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to proceed to screenshot from callback handler."""
    header = _build_step_header("screenshot")
    context_display = _build_context_display(wizard_data)

    prompt = f"{header}\n{context_display}\n\nUpload a screenshot of the trade chart:\n\nPress *>> Skip* to continue without a screenshot."

    await query.edit_message_text(
        prompt,
        reply_markup=_step_keyboard(include_skip=True),
        parse_mode="Markdown",
    )
    return UPLOAD_SCREENSHOT


async def handle_screenshot(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle screenshot upload (Step 11 -> Step 12: Confirm).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.photo:
        return UPLOAD_SCREENSHOT

    # Get the highest resolution photo
    photo = update.message.photo[-1]

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["photo_file_id"] = photo.file_id
    wizard_data["step_history"].append(UPLOAD_SCREENSHOT)

    return await _proceed_to_confirm(update, context, wizard_data)


async def handle_screenshot_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping screenshot upload.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return UPLOAD_SCREENSHOT

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    wizard_data["photo_file_id"] = None
    wizard_data["step_history"].append(UPLOAD_SCREENSHOT)

    return await _proceed_to_confirm_callback(query, context, wizard_data)


async def _proceed_to_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to show confirmation from message handler."""
    progress = build_wizard_progress(12, "Confirm Trade")
    summary = _build_trade_summary(wizard_data)

    await update.message.reply_text(
        f"{progress}\n\n"
        f"{summary}\n\n"
        "Is this correct?",
        reply_markup=confirmation_keyboard(
            confirm_text="Create Trade",
            cancel_text="Cancel",
            confirm_data="tw_confirm",
            cancel_data="tw_cancel",
        ),
    )
    return CONFIRM


async def _proceed_to_confirm_callback(query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict) -> int:
    """Helper to show confirmation from callback handler."""
    progress = build_wizard_progress(12, "Confirm Trade")
    summary = _build_trade_summary(wizard_data)

    await query.edit_message_text(
        f"{progress}\n\n"
        f"{summary}\n\n"
        "Is this correct?",
        reply_markup=confirmation_keyboard(
            confirm_text="Create Trade",
            cancel_text="Cancel",
            confirm_data="tw_confirm",
            cancel_data="tw_cancel",
        ),
    )
    return CONFIRM


def _build_trade_summary(wizard_data: dict) -> str:
    """Build a summary string from wizard data."""
    lines = [
        "Trade Summary:",
        f"Instrument: {wizard_data.get('instrument', 'N/A')}",
        f"Direction: {wizard_data.get('direction', 'N/A')}",
        f"Entry Price: {wizard_data.get('entry_price', 'N/A')}",
        f"Stop Loss: {wizard_data.get('sl_price', 'Not set')}",
        f"Take Profit: {wizard_data.get('tp_price', 'Not set')}",
        f"Lot Size: {wizard_data.get('lot_size', 'N/A')}",
        f"Strategy: {'Set' if wizard_data.get('strategy_id') else 'None'}",
        f"Tags: {len(wizard_data.get('selected_tags', set()))} selected",
        f"Notes: {'Yes' if wizard_data.get('notes') else 'None'}",
        f"Screenshot: {'Yes' if wizard_data.get('photo_file_id') else 'None'}",
    ]
    return "\n".join(lines)


async def handle_trade_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle trade creation confirmation.

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

    if query.data != "tw_confirm":
        context.user_data.pop(TRADE_WIZARD_KEY, None)
        await query.edit_message_text(
            "Trade creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    if not wizard_data:
        # Stale state - return silently
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            # Create the trade
            direction = TradeDirection.LONG if wizard_data["direction"] == "LONG" else TradeDirection.SHORT

            trade = Trade(
                account_id=wizard_data["account_id"],
                instrument=wizard_data["instrument"],
                direction=direction,
                entry_price=wizard_data["entry_price"],
                sl_price=wizard_data.get("sl_price"),
                tp_price=wizard_data.get("tp_price"),
                lot_size=wizard_data["lot_size"],
                status=TradeStatus.OPEN,
                strategy_id=wizard_data.get("strategy_id"),
                notes=wizard_data.get("notes"),
            )
            session.add(trade)
            await session.flush()

            # Create TradeTag records
            for tag_id in wizard_data.get("selected_tags", set()):
                trade_tag = TradeTag(trade_id=trade.id, tag_id=tag_id)
                session.add(trade_tag)

            # Save screenshot if provided
            if wizard_data.get("photo_file_id"):
                screenshots_dir = os.path.join(os.getcwd(), "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)

                file = await context.bot.get_file(wizard_data["photo_file_id"])
                screenshot_path = os.path.join(screenshots_dir, f"trade_{trade.id}.jpg")
                await file.download_to_drive(screenshot_path)

                trade.screenshot_path = screenshot_path

            await session.flush()

            logger.info(
                "Trade created",
                trade_id=trade.id,
                instrument=trade.instrument,
                direction=trade.direction.value,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                f"Trade created successfully!\n\n"
                f"Trade ID: {trade.id}\n"
                f"{wizard_data['instrument']} {wizard_data['direction']} @ {wizard_data['entry_price']}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error creating trade", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred while creating the trade. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(TRADE_WIZARD_KEY, None)
    return ConversationHandler.END


async def handle_wizard_back(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle back button in trade wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The previous conversation state.
    """
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()

    wizard_data = context.user_data.get(TRADE_WIZARD_KEY, {})
    step_history = wizard_data.get("step_history", [])

    if not step_history:
        # Return to first step - account selection
        return await start_trade_wizard(update, context)

    # Go back to previous step
    previous_state = step_history.pop()

    # For now, just restart the wizard - a full back implementation
    # would need to store and restore the message for each state
    await query.edit_message_text(
        "Going back... Please start again.",
        reply_markup=back_to_menu_keyboard(),
    )

    context.user_data.pop(TRADE_WIZARD_KEY, None)
    return ConversationHandler.END


async def cancel_trade_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the trade wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(TRADE_WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Trade creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "Trade creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Trade entry ConversationHandler
trade_entry_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_trade_wizard, pattern="^menu_add_trade$"),
        CallbackQueryHandler(start_trade_wizard, pattern="^trade_new$"),
    ],
    states={
        SELECT_ACCOUNT: [
            CallbackQueryHandler(handle_account_select, pattern="^tw_acc_"),
        ],
        SELECT_INSTRUMENT: [
            CallbackQueryHandler(handle_instrument_select, pattern="^instrument_"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_instrument_custom),
        ],
        SELECT_DIRECTION: [
            CallbackQueryHandler(handle_direction_select, pattern="^direction_"),
        ],
        ENTER_ENTRY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_entry_price),
        ],
        ENTER_SL: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sl_price),
            CallbackQueryHandler(handle_sl_skip, pattern="^tw_skip$"),
        ],
        ENTER_TP: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_tp_price),
            CallbackQueryHandler(handle_tp_skip, pattern="^tw_skip$"),
        ],
        ENTER_LOT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_lot_size),
        ],
        SELECT_STRATEGY: [
            CallbackQueryHandler(handle_strategy_select, pattern="^(strategy_select_|strategy_skip)"),
        ],
        SELECT_TAGS: [
            CallbackQueryHandler(handle_tag_toggle, pattern="^(tag_toggle_|tags_done|tags_clear)"),
        ],
        ENTER_NOTES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_notes),
            CallbackQueryHandler(handle_notes_skip, pattern="^tw_skip$"),
        ],
        UPLOAD_SCREENSHOT: [
            MessageHandler(filters.PHOTO, handle_screenshot),
            CallbackQueryHandler(handle_screenshot_skip, pattern="^tw_skip$"),
        ],
        CONFIRM: [
            CallbackQueryHandler(handle_trade_confirm, pattern="^(tw_confirm|tw_cancel)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_trade_wizard),
        CallbackQueryHandler(cancel_trade_wizard, pattern="^tw_cancel$"),
        CallbackQueryHandler(handle_wizard_back, pattern="^tw_back$"),
        CallbackQueryHandler(cancel_trade_wizard, pattern="^back$"),
    ],
    per_message=False,
)


# ============================================================================
# CLOSE TRADE FLOW (F14)
# ============================================================================


async def start_close_trade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the close trade flow.

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

    trade_id_str = query.data.replace("trade_close_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            # Verify ownership
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            if trade.status != TradeStatus.OPEN:
                await query.edit_message_text(
                    "This trade is already closed.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            context.user_data[CLOSE_WIZARD_KEY] = {
                "trade_id": trade_id,
                "entry_price": trade.entry_price,
                "direction": trade.direction.value,
                "lot_size": trade.lot_size,
                "account_id": trade.account_id,
                "currency": trade.account.currency,
                "instrument": trade.instrument,
            }

            await query.edit_message_text(
                f"Closing Trade: {trade.instrument} {trade.direction.value.upper()}\n"
                f"Entry: {trade.entry_price}\n"
                f"Lot Size: {trade.lot_size}\n\n"
                "Enter the exit price:",
                reply_markup=back_cancel_keyboard(
                    back_data=f"trade_detail_{trade_id}",
                    cancel_data="close_cancel",
                ),
            )

            return CLOSE_ENTER_EXIT

    except Exception as e:
        logger.error("Error starting close trade", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_close_exit_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle exit price input for closing trade.

    Uses PnLService for accurate P&L calculation with currency conversion.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return CLOSE_ENTER_EXIT

    price_input = update.message.text.strip()
    validation = validate_price(price_input)

    if not validation.is_valid:
        await update.message.reply_text(
            f"Invalid exit price: {validation.error}\n\n"
            "Please enter a valid positive number:",
            reply_markup=back_cancel_keyboard(cancel_data="close_cancel"),
        )
        return CLOSE_ENTER_EXIT

    close_data = context.user_data.get(CLOSE_WIZARD_KEY, {})
    exit_price = validation.value
    entry_price = close_data.get("entry_price")
    direction = close_data.get("direction", "long")
    lot_size = close_data.get("lot_size", Decimal("1"))
    instrument = close_data.get("instrument", "")
    currency = close_data.get("currency", "USD")

    # Use PnLService for accurate calculation with currency conversion
    pnl_service = get_pnl_service()
    pnl_result = await pnl_service.calculate_pnl(
        instrument=instrument,
        direction=direction,
        entry_price=float(entry_price),
        exit_price=float(exit_price),
        lot_size=float(lot_size),
    )

    # Fall back to simple calculation if PnLService fails
    if pnl_result.success:
        pnl = Decimal(str(pnl_result.pnl_base))
        pnl_native = Decimal(str(pnl_result.pnl_native))
        native_currency = pnl_result.native_currency
        exchange_rate = pnl_result.exchange_rate
    else:
        # Fallback to basic calculation
        pnl = calculate_pnl(entry_price, exit_price, direction, lot_size)
        pnl_native = pnl
        native_currency = "USD"
        exchange_rate = 1.0

    pnl_percent = calculate_pnl_percent(entry_price, exit_price, direction)

    close_data["exit_price"] = exit_price
    close_data["pnl"] = pnl
    close_data["pnl_percent"] = pnl_percent
    close_data["pnl_native"] = pnl_native
    close_data["native_currency"] = native_currency
    close_data["exchange_rate"] = exchange_rate

    pnl_indicator = "PROFIT" if pnl > 0 else "LOSS" if pnl < 0 else "BREAKEVEN"

    # Build P&L display with conversion info if different currencies
    pnl_lines = [f"Exit Price: {exit_price}", ""]

    if native_currency.upper() != "USD" and pnl_result.success:
        # Show conversion breakdown
        native_symbol = "\u20ac" if native_currency == "EUR" else native_currency
        pnl_lines.append(f"P&L: {native_symbol}{pnl_native:,.2f} {native_currency}")
        pnl_lines.append(f"      x {exchange_rate:.4f} = ${pnl:,.2f} USD")
    else:
        pnl_lines.append(f"P&L: {format_currency(pnl, 'USD', include_sign=True)}")

    pnl_lines.append(f"Percent: {pnl_percent:+.2f}%")
    pnl_lines.append(f"Result: {pnl_indicator}")
    pnl_lines.append("")
    pnl_lines.append("Confirm closing this trade?")

    await update.message.reply_text(
        "\n".join(pnl_lines),
        reply_markup=confirmation_keyboard(
            confirm_text="Close Trade",
            cancel_text="Cancel",
            confirm_data="close_confirm",
            cancel_data="close_cancel",
        ),
    )

    return CLOSE_CONFIRM


async def handle_close_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle close trade confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    query = update.callback_query
    if not query or not query.data:
        return ConversationHandler.END

    await query.answer()

    if query.data != "close_confirm":
        context.user_data.pop(CLOSE_WIZARD_KEY, None)
        await query.edit_message_text(
            "Trade close cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    close_data = context.user_data.get(CLOSE_WIZARD_KEY, {})
    if not close_data:
        # Stale state - return silently
        return ConversationHandler.END

    trade_id = close_data.get("trade_id")
    exit_price = close_data.get("exit_price")
    pnl = close_data.get("pnl")
    pnl_percent = close_data.get("pnl_percent")
    currency = close_data.get("currency", "USD")

    try:
        async with get_session() as session:
            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(CLOSE_WIZARD_KEY, None)
                return ConversationHandler.END

            # Update trade
            trade.exit_price = exit_price
            trade.pnl = pnl
            trade.pnl_percent = pnl_percent
            trade.status = TradeStatus.CLOSED
            trade.closed_at = datetime.utcnow()

            # Update account balance
            trade.account.current_balance += pnl

            await session.flush()

            logger.info(
                "Trade closed",
                trade_id=trade_id,
                pnl=str(pnl),
                pnl_percent=str(pnl_percent),
            )

            pnl_formatted = format_currency(pnl, currency, include_sign=True)
            await query.edit_message_text(
                f"Trade closed successfully!\n\n"
                f"P&L: {pnl_formatted} ({pnl_percent:+.2f}%)\n"
                f"New Account Balance: {format_currency(trade.account.current_balance, currency)}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error closing trade", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred while closing the trade. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(CLOSE_WIZARD_KEY, None)
    return ConversationHandler.END


async def cancel_close_trade(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the close trade flow.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(CLOSE_WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Trade close cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "Trade close cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Close trade ConversationHandler
close_trade_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_close_trade, pattern="^trade_close_"),
    ],
    states={
        CLOSE_ENTER_EXIT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_close_exit_price),
        ],
        CLOSE_CONFIRM: [
            CallbackQueryHandler(handle_close_confirm, pattern="^(close_confirm|close_cancel)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_close_trade),
        CallbackQueryHandler(cancel_close_trade, pattern="^close_cancel$"),
    ],
    per_message=False,
)


# ============================================================================
# TRADE LISTING AND HISTORY (F15)
# ============================================================================


async def handle_open_trades(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle open trades list callback with unrealized P&L.

    Uses PnLService to calculate unrealized P&L for each open trade
    based on current market prices.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    telegram_id = update.effective_user.id
    filter_account_id = context.user_data.get("open_trades_filter_account")

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get user's accounts
            account_ids_result = await session.execute(
                select(Account.id)
                .where(Account.user_id == user.id)
                .where(Account.is_active == True)
            )
            account_ids = [row[0] for row in account_ids_result.fetchall()]

            if not account_ids:
                await query.edit_message_text(
                    "You don't have any trading accounts yet.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Build query for open trades
            trades_query = (
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.OPEN)
            )

            if filter_account_id:
                trades_query = trades_query.where(Trade.account_id == filter_account_id)

            trades_query = trades_query.order_by(Trade.opened_at.desc())

            result = await session.execute(trades_query)
            trades = result.scalars().all()

            if not trades:
                message = "You don't have any open trades."
                if filter_account_id:
                    message += "\n\nTry clearing the filter to see all trades."
                await query.edit_message_text(
                    message,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("Clear Filter", callback_data="open_trades_filter_clear")]
                        if filter_account_id else
                        [InlineKeyboardButton("Add New Trade", callback_data="menu_add_trade")],
                        [InlineKeyboardButton("Back to Menu", callback_data="menu_home")],
                    ]),
                )
                return

            # Get services for P&L calculation
            pnl_service = get_pnl_service()
            price_service = get_price_service()

            # Get unique instruments for price fetching
            instruments = set(trade.instrument for trade in trades)
            current_prices: dict[str, float] = {}

            # Fetch current prices for all instruments
            for instrument in instruments:
                try:
                    price_result = await price_service.get_current_price(instrument)
                    if price_result.success and price_result.price is not None:
                        current_prices[instrument] = price_result.price
                except Exception as e:
                    logger.debug(f"Failed to get price for {instrument}: {e}")

            # Build trade list with unrealized P&L
            trade_list = []
            total_unrealized_pnl = Decimal("0")

            for trade in trades:
                pnl_indicator = ""
                current_price = current_prices.get(trade.instrument)

                if current_price is not None:
                    # Calculate unrealized P&L using PnLService
                    try:
                        pnl_result = await pnl_service.calculate_unrealized_pnl(
                            instrument=trade.instrument,
                            direction=trade.direction.value,
                            entry_price=float(trade.entry_price),
                            lot_size=float(trade.lot_size),
                            current_price=current_price,
                        )

                        if pnl_result.success:
                            unrealized_pnl = Decimal(str(pnl_result.pnl_base))
                            total_unrealized_pnl += unrealized_pnl

                            # Create P&L indicator for display
                            if unrealized_pnl > 0:
                                pnl_indicator = f"+${unrealized_pnl:,.0f}"
                            elif unrealized_pnl < 0:
                                pnl_indicator = f"-${abs(unrealized_pnl):,.0f}"
                            else:
                                pnl_indicator = "$0"
                    except Exception as e:
                        logger.debug(f"Failed to calculate unrealized P&L: {e}")

                trade_list.append((
                    trade.id,
                    trade.instrument,
                    trade.direction.value,
                    trade.entry_price,
                    pnl_indicator,
                ))

            # Build header with total unrealized P&L
            header_lines = [f"Open Trades ({len(trades)}):"]

            if total_unrealized_pnl != 0:
                total_display = format_currency(total_unrealized_pnl, "USD", include_sign=True)
                header_lines.append(f"Total Unrealized P&L: {total_display}")

            header_lines.append("")
            header_lines.append("Select a trade to view details:")

            await query.edit_message_text(
                "\n".join(header_lines),
                reply_markup=open_trades_keyboard(trade_list, filter_account_id),
            )

    except Exception as e:
        logger.error("Error loading open trades", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_trade_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle trade history list callback with pagination.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    telegram_id = update.effective_user.id
    page = 1

    # Parse page from callback data if present
    if query.data and query.data.startswith("history_page_"):
        try:
            page = int(query.data.replace("history_page_", "").replace("prev_", "").replace("next_", ""))
        except ValueError:
            page = 1

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get user's accounts
            account_ids_result = await session.execute(
                select(Account.id)
                .where(Account.user_id == user.id)
                .where(Account.is_active == True)
            )
            account_ids = [row[0] for row in account_ids_result.fetchall()]

            if not account_ids:
                await query.edit_message_text(
                    "You don't have any trading accounts yet.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Count total closed trades
            count_result = await session.execute(
                select(func.count(Trade.id))
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
            )
            total_trades = count_result.scalar() or 0

            if total_trades == 0:
                await query.edit_message_text(
                    "You don't have any closed trades yet.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Calculate pagination
            total_pages = (total_trades + TRADES_PER_PAGE - 1) // TRADES_PER_PAGE
            offset = (page - 1) * TRADES_PER_PAGE

            # Get trades for current page
            result = await session.execute(
                select(Trade)
                .where(Trade.account_id.in_(account_ids))
                .where(Trade.status == TradeStatus.CLOSED)
                .order_by(Trade.closed_at.desc())
                .offset(offset)
                .limit(TRADES_PER_PAGE)
            )
            trades = result.scalars().all()

            # Build keyboard with trades
            keyboard = []
            for trade in trades:
                pnl_str = format_currency(trade.pnl or Decimal("0"), include_sign=True)
                label = f"{trade.instrument} {trade.direction.value.upper()} | {pnl_str}"
                keyboard.append([
                    InlineKeyboardButton(label, callback_data=f"trade_detail_{trade.id}"),
                ])

            # Add pagination
            nav_row = []
            if page > 1:
                nav_row.append(InlineKeyboardButton(
                    "< Previous", callback_data=f"history_page_prev_{page - 1}"
                ))
            nav_row.append(InlineKeyboardButton(
                f"{page}/{total_pages}", callback_data="history_noop"
            ))
            if page < total_pages:
                nav_row.append(InlineKeyboardButton(
                    "Next >", callback_data=f"history_page_next_{page + 1}"
                ))
            keyboard.append(nav_row)

            keyboard.append([
                InlineKeyboardButton("Back to Menu", callback_data="menu_home"),
            ])

            await query.edit_message_text(
                f"Trade History ({total_trades} total):\n\n"
                "Select a trade to view details:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    except Exception as e:
        logger.error("Error loading trade history", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_trade_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle trade detail view callback.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("trade_detail_", "")
    try:
        trade_id = int(trade_id_str)
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

            result = await session.execute(
                select(Trade)
                .options(
                    selectinload(Trade.account),
                    selectinload(Trade.strategy),
                    selectinload(Trade.trade_tags).selectinload(TradeTag.tag),
                )
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Verify ownership
            if trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Build detail message
            currency = trade.account.currency
            is_open = trade.status == TradeStatus.OPEN

            lines = [
                f"Trade #{trade.id}",
                "=" * 30,
                "",
                f"Account: {trade.account.name}",
                f"Instrument: {trade.instrument}",
                f"Direction: {trade.direction.value.upper()}",
                f"Status: {trade.status.value.upper()}",
                "",
                f"Entry Price: {trade.entry_price}",
            ]

            if trade.exit_price:
                lines.append(f"Exit Price: {trade.exit_price}")

            if trade.sl_price:
                lines.append(f"Stop Loss: {trade.sl_price}")
            if trade.tp_price:
                lines.append(f"Take Profit: {trade.tp_price}")

            lines.append(f"Lot Size: {trade.lot_size}")

            if trade.pnl is not None:
                lines.append("")
                lines.append(f"P&L: {format_currency(trade.pnl, currency, include_sign=True)}")
                if trade.pnl_percent is not None:
                    lines.append(f"P&L %: {trade.pnl_percent:+.2f}%")

            if trade.strategy:
                lines.append("")
                lines.append(f"Strategy: {trade.strategy.name}")

            if trade.trade_tags:
                tag_names = [tt.tag.name for tt in trade.trade_tags]
                lines.append(f"Tags: {', '.join(tag_names)}")

            lines.append("")
            lines.append(f"Opened: {format_datetime(trade.opened_at)}")
            if trade.closed_at:
                lines.append(f"Closed: {format_datetime(trade.closed_at)}")

            if trade.notes:
                lines.append("")
                lines.append(f"Notes: {trade.notes[:200]}")
                if len(trade.notes) > 200:
                    lines.append("...")

            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=trade_detail_keyboard(trade_id, is_open),
            )

    except Exception as e:
        logger.error("Error loading trade detail", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_trade_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle trade deletion with confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    if query.data.startswith("trade_delete_") and not query.data.startswith("trade_delete_confirm_"):
        trade_id_str = query.data.replace("trade_delete_", "")
        try:
            trade_id = int(trade_id_str)
        except ValueError:
            return

        context.user_data["delete_trade_id"] = trade_id

        await query.edit_message_text(
            "Are you sure you want to delete this trade?\n\n"
            "This action cannot be undone.",
            reply_markup=confirmation_keyboard(
                confirm_text="Yes, Delete",
                cancel_text="No, Keep It",
                confirm_data=f"trade_delete_confirm_{trade_id}",
                cancel_data=f"trade_detail_{trade_id}",
            ),
        )

    elif query.data.startswith("trade_delete_confirm_"):
        trade_id_str = query.data.replace("trade_delete_confirm_", "")
        try:
            trade_id = int(trade_id_str)
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
                    select(Trade)
                    .options(selectinload(Trade.account))
                    .where(Trade.id == trade_id)
                )
                trade = result.scalar_one_or_none()

                if trade and trade.account.user_id == user.id:
                    # Delete associated trade tags first
                    await session.execute(
                        TradeTag.__table__.delete().where(TradeTag.trade_id == trade_id)
                    )

                    # Delete the trade
                    await session.delete(trade)
                    await session.flush()

                    logger.info(
                        "Trade deleted",
                        trade_id=trade_id,
                        telegram_id=telegram_id,
                    )

                    await query.edit_message_text(
                        "Trade deleted successfully.",
                        reply_markup=back_to_menu_keyboard(),
                    )
                else:
                    await query.edit_message_text(
                        "Trade not found.",
                        reply_markup=back_to_menu_keyboard(),
                    )

        except Exception as e:
            logger.error("Error deleting trade", error=str(e), trade_id=trade_id)
            await query.edit_message_text(
                "An error occurred. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )

        context.user_data.pop("delete_trade_id", None)


async def handle_open_trades_filter(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle filter by account for open trades.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return

    await query.answer()

    if query.data == "open_trades_filter_clear":
        context.user_data.pop("open_trades_filter_account", None)
        await handle_open_trades(update, context)
        return

    if query.data == "open_trades_filter":
        telegram_id = update.effective_user.id

        try:
            async with get_session() as session:
                user = await get_user_by_telegram_id(session, telegram_id)
                if not user:
                    return

                accounts = await get_user_accounts(session, user.id)

                keyboard = []
                for account_id, account_name in accounts:
                    keyboard.append([
                        InlineKeyboardButton(
                            account_name,
                            callback_data=f"open_trades_filter_acc_{account_id}",
                        )
                    ])
                keyboard.append([
                    InlineKeyboardButton("Back", callback_data="menu_open_trades"),
                ])

                await query.edit_message_text(
                    "Select an account to filter by:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )

        except Exception as e:
            logger.error("Error showing filter options", error=str(e))

    elif query.data and query.data.startswith("open_trades_filter_acc_"):
        account_id_str = query.data.replace("open_trades_filter_acc_", "")
        try:
            account_id = int(account_id_str)
            context.user_data["open_trades_filter_account"] = account_id
            await handle_open_trades(update, context)
        except ValueError:
            pass


# ============================================================================
# EDIT TRADE HANDLERS
# ============================================================================


async def handle_edit_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle displaying the edit field selection menu.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("trade_edit_", "")
    try:
        trade_id = int(trade_id_str)
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

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            is_open = trade.status == TradeStatus.OPEN

            await query.edit_message_text(
                f"Edit Trade #{trade_id}\n\n"
                f"Instrument: {trade.instrument}\n"
                f"Direction: {trade.direction.value.upper()}\n\n"
                "Select a field to edit:",
                reply_markup=edit_field_keyboard(trade_id, is_open),
            )

    except Exception as e:
        logger.error("Error showing edit menu", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_edit_sl(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing stop-loss price.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("trade_edit_sl_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "sl",
    }

    await query.edit_message_text(
        "Enter the new stop-loss price:\n\n"
        "Send 'clear' to remove the stop-loss.",
        reply_markup=back_cancel_keyboard(
            back_data=f"trade_edit_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_edit_tp(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing take-profit price.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("trade_edit_tp_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "tp",
    }

    await query.edit_message_text(
        "Enter the new take-profit price:\n\n"
        "Send 'clear' to remove the take-profit.",
        reply_markup=back_cancel_keyboard(
            back_data=f"trade_edit_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_edit_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade notes.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("trade_edit_notes_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "notes",
    }

    await query.edit_message_text(
        "Enter the new notes for this trade:\n\n"
        "Send 'clear' to remove notes.",
        reply_markup=back_cancel_keyboard(
            back_data=f"trade_edit_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_edit_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle edit input for SL, TP, notes, entry, lotsize, exit, or custom instrument.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data:
        return

    trade_id = edit_data.get("trade_id")
    field = edit_data.get("field")
    awaiting_custom = edit_data.get("awaiting_custom", False)
    input_text = update.message.text.strip()

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await update.message.reply_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            success_message = "Trade updated successfully!"

            if field == "sl":
                if input_text.lower() == "clear":
                    trade.sl_price = None
                else:
                    validation = validate_price(input_text)
                    if not validation.is_valid:
                        await update.message.reply_text(
                            f"Invalid price: {validation.error}",
                        )
                        return

                    sl_validation = validate_sl_tp(
                        trade.entry_price, validation.value, None, trade.direction.value
                    )
                    if not sl_validation.is_valid:
                        await update.message.reply_text(
                            f"Invalid stop-loss: {sl_validation.error}",
                        )
                        return

                    trade.sl_price = validation.value

            elif field == "tp":
                if input_text.lower() == "clear":
                    trade.tp_price = None
                else:
                    validation = validate_price(input_text)
                    if not validation.is_valid:
                        await update.message.reply_text(
                            f"Invalid price: {validation.error}",
                        )
                        return

                    tp_validation = validate_sl_tp(
                        trade.entry_price, None, validation.value, trade.direction.value
                    )
                    if not tp_validation.is_valid:
                        await update.message.reply_text(
                            f"Invalid take-profit: {tp_validation.error}",
                        )
                        return

                    trade.tp_price = validation.value

            elif field == "notes":
                if input_text.lower() == "clear":
                    trade.notes = None
                else:
                    trade.notes = input_text

            elif field == "instrument" and awaiting_custom:
                # Custom instrument input
                validation = validate_instrument(input_text)
                if not validation.is_valid:
                    await update.message.reply_text(
                        f"Invalid instrument: {validation.error}",
                    )
                    return

                old_instrument = trade.instrument
                trade.instrument = validation.value
                success_message = f"Instrument updated from {old_instrument} to {validation.value}!"

            elif field == "entry":
                # Entry price edit
                validation = validate_price(input_text)
                if not validation.is_valid:
                    await update.message.reply_text(
                        f"Invalid price: {validation.error}",
                    )
                    return

                old_entry = trade.entry_price
                trade.entry_price = validation.value

                # Recalculate P&L if trade is closed
                if trade.status == TradeStatus.CLOSED and trade.exit_price is not None:
                    _recalculate_pnl(trade)
                    success_message = (
                        f"Entry price updated from {old_entry} to {validation.value}!\n\n"
                        f"P&L recalculated: {format_currency(trade.pnl, include_sign=True)}"
                    )
                else:
                    success_message = f"Entry price updated from {old_entry} to {validation.value}!"

            elif field == "lotsize":
                # Lot size edit
                validation = validate_lot_size(input_text)
                if not validation.is_valid:
                    await update.message.reply_text(
                        f"Invalid lot size: {validation.error}",
                    )
                    return

                old_lotsize = trade.lot_size
                trade.lot_size = validation.value

                # Recalculate P&L if trade is closed
                if trade.status == TradeStatus.CLOSED and trade.exit_price is not None:
                    _recalculate_pnl(trade)
                    success_message = (
                        f"Lot size updated from {old_lotsize} to {validation.value}!\n\n"
                        f"P&L recalculated: {format_currency(trade.pnl, include_sign=True)}"
                    )
                else:
                    success_message = f"Lot size updated from {old_lotsize} to {validation.value}!"

            elif field == "exit":
                # Exit price edit (only for closed trades)
                if trade.status != TradeStatus.CLOSED:
                    await update.message.reply_text(
                        "Exit price can only be edited for closed trades.",
                        reply_markup=back_to_menu_keyboard(),
                    )
                    context.user_data.pop(EDIT_WIZARD_KEY, None)
                    return

                validation = validate_price(input_text)
                if not validation.is_valid:
                    await update.message.reply_text(
                        f"Invalid price: {validation.error}",
                    )
                    return

                old_exit = trade.exit_price
                trade.exit_price = validation.value

                # Recalculate P&L
                _recalculate_pnl(trade)
                success_message = (
                    f"Exit price updated from {old_exit} to {validation.value}!\n\n"
                    f"P&L recalculated: {format_currency(trade.pnl, include_sign=True)}"
                )

            else:
                # Unknown field
                await update.message.reply_text(
                    "Unknown field. Please try again.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            await session.flush()

            logger.info(
                "Trade updated",
                trade_id=trade_id,
                field=field,
                telegram_id=telegram_id,
            )

            await update.message.reply_text(
                success_message,
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating trade", error=str(e), trade_id=trade_id)
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)
    raise ApplicationHandlerStop  # Prevent other handler groups from firing


async def handle_edit_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle cancelling edit operation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if query:
        await query.answer()

    edit_data = context.user_data.pop(EDIT_WIZARD_KEY, None)

    if query:
        await query.edit_message_text(
            "Edit cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# CORE FIELD EDITING HANDLERS (F2, F3, F4)
# ============================================================================


async def handle_edit_instrument(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade instrument.

    Shows the instrument keyboard for selection.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_instrument_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "instrument",
    }

    await query.edit_message_text(
        "Select the new instrument for this trade:",
        reply_markup=instrument_keyboard(),
    )


async def handle_edit_instrument_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle instrument selection from keyboard during edit.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "instrument":
        return

    trade_id = edit_data.get("trade_id")

    # Check if it's a custom instrument request
    if query.data == "instrument_custom":
        context.user_data[EDIT_WIZARD_KEY]["awaiting_custom"] = True
        await query.edit_message_text(
            "Enter the custom instrument name (e.g., GOLD, BTC, AAPL):",
            reply_markup=back_cancel_keyboard(
                back_data=f"trade_edit_{trade_id}",
                cancel_data="edit_cancel",
            ),
        )
        return

    # Handle back/cancel
    if query.data == "back":
        context.user_data.pop(EDIT_WIZARD_KEY, None)
        # Return to edit menu - trigger handle_edit_menu
        await query.edit_message_text(
            "Returning to edit menu...",
            reply_markup=back_to_menu_keyboard(),
        )
        return
    if query.data == "cancel":
        context.user_data.pop(EDIT_WIZARD_KEY, None)
        await query.edit_message_text(
            "Edit cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    # Extract instrument from callback data (e.g., "instrument_DAX" -> "DAX")
    if not query.data.startswith("instrument_"):
        return

    new_instrument = query.data.replace("instrument_", "")

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            old_instrument = trade.instrument
            trade.instrument = new_instrument

            await session.flush()

            logger.info(
                "Trade instrument updated",
                trade_id=trade_id,
                old_instrument=old_instrument,
                new_instrument=new_instrument,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                f"Instrument updated from {old_instrument} to {new_instrument}!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating instrument", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)


async def handle_edit_direction(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade direction.

    Shows the direction keyboard for selection.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_direction_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "direction",
    }

    await query.edit_message_text(
        "Select the new direction for this trade:",
        reply_markup=direction_keyboard(),
    )


async def handle_edit_direction_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle direction selection from keyboard during edit.

    Updates direction and recalculates P&L for closed trades.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "direction":
        return

    trade_id = edit_data.get("trade_id")

    # Handle back/cancel
    if query.data == "back":
        context.user_data.pop(EDIT_WIZARD_KEY, None)
        await query.edit_message_text(
            "Returning to edit menu...",
            reply_markup=back_to_menu_keyboard(),
        )
        return
    if query.data == "cancel":
        context.user_data.pop(EDIT_WIZARD_KEY, None)
        await query.edit_message_text(
            "Edit cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    # Extract direction from callback data
    if not query.data.startswith("direction_"):
        return

    new_direction_str = query.data.replace("direction_", "").lower()

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            old_direction = trade.direction.value
            new_direction = TradeDirection(new_direction_str)
            trade.direction = new_direction

            # Recalculate P&L if trade is closed
            if trade.status == TradeStatus.CLOSED and trade.exit_price is not None:
                _recalculate_pnl(trade)

            await session.flush()

            logger.info(
                "Trade direction updated",
                trade_id=trade_id,
                old_direction=old_direction,
                new_direction=new_direction_str,
                telegram_id=telegram_id,
            )

            message = f"Direction updated from {old_direction.upper()} to {new_direction_str.upper()}!"
            if trade.status == TradeStatus.CLOSED:
                message += f"\n\nP&L recalculated: {format_currency(trade.pnl, include_sign=True)}"

            await query.edit_message_text(
                message,
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating direction", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)


async def handle_edit_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing entry price.

    Prompts user for text input.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_entry_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "entry",
    }

    await query.edit_message_text(
        "Enter the new entry price:",
        reply_markup=back_cancel_keyboard(
            back_data=f"trade_detail_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_edit_lotsize(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing lot size.

    Prompts user for text input.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_lotsize_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "lotsize",
    }

    await query.edit_message_text(
        "Enter the new lot size (e.g., 0.1, 1, 2.5):",
        reply_markup=back_cancel_keyboard(
            back_data=f"trade_detail_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_edit_exit(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing exit price (closed trades only).

    Prompts user for text input.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_exit_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id

    # Verify trade is closed before allowing exit price edit
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
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            if trade.status != TradeStatus.CLOSED:
                await query.edit_message_text(
                    "Exit price can only be edited for closed trades.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            context.user_data[EDIT_WIZARD_KEY] = {
                "trade_id": trade_id,
                "field": "exit",
            }

            await query.edit_message_text(
                f"Current exit price: {trade.exit_price}\n\n"
                "Enter the new exit price:",
                reply_markup=back_cancel_keyboard(
                    back_data=f"trade_detail_{trade_id}",
                    cancel_data="edit_cancel",
                ),
            )

    except Exception as e:
        logger.error("Error handling edit exit", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# SL/TP ALERT HANDLER (F21)
# ============================================================================

# Track which trade/alert combinations have been sent to prevent duplicates
_alert_sent_cache: dict[tuple[int, str], bool] = {}


def _build_alert_keyboard(trade_id: int) -> InlineKeyboardMarkup:
    """
    Build keyboard for SL/TP alert message.

    Args:
        trade_id: The trade ID.

    Returns:
        InlineKeyboardMarkup: Alert action keyboard.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "Close Trade Now",
                callback_data=f"trade_close_{trade_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "View Trade Details",
                callback_data=f"trade_detail_{trade_id}",
            ),
        ],
    ])


async def _send_price_alert(alert, bot) -> None:
    """
    Send a price alert message to the user.

    Args:
        alert: The PriceAlert object from price_monitor.
        bot: The Telegram bot instance.
    """
    from services.price_monitor import AlertType

    # Check cooldown - prevent duplicate alerts
    cache_key = (alert.trade_id, alert.alert_type.value)
    if cache_key in _alert_sent_cache:
        logger.debug(
            "Alert already sent, skipping",
            trade_id=alert.trade_id,
            alert_type=alert.alert_type.value,
        )
        return

    # Mark as sent
    _alert_sent_cache[cache_key] = True

    # Build alert message
    if alert.alert_type == AlertType.SL_HIT:
        emoji = "\u26a0\ufe0f"  # Warning emoji
        title = "STOP LOSS HIT"
        level_price = alert.sl_price
    else:  # TP_HIT
        emoji = "\U0001f389"  # Celebration emoji
        title = "TAKE PROFIT HIT"
        level_price = alert.tp_price

    direction_display = alert.direction.upper()

    message_lines = [
        f"{emoji} {title} {emoji}",
        "",
        f"Trade: {alert.instrument} {direction_display}",
        f"Entry Price: {alert.entry_price}",
        f"Current Price: {alert.current_price:.4f}",
        f"Alert Level: {level_price}",
        "",
    ]

    if alert.alert_type == AlertType.SL_HIT:
        message_lines.append("Your stop-loss level has been reached!")
        message_lines.append("Consider closing this trade to limit losses.")
    else:
        message_lines.append("Your take-profit target has been reached!")
        message_lines.append("Consider closing this trade to secure profits.")

    message = "\n".join(message_lines)

    try:
        await bot.send_message(
            chat_id=alert.telegram_id,
            text=message,
            reply_markup=_build_alert_keyboard(alert.trade_id),
        )
        logger.info(
            "Price alert sent",
            trade_id=alert.trade_id,
            alert_type=alert.alert_type.value,
            telegram_id=alert.telegram_id,
        )
    except Exception as e:
        logger.error(
            "Failed to send price alert",
            error=str(e),
            trade_id=alert.trade_id,
            telegram_id=alert.telegram_id,
        )
        # Remove from cache so we can retry
        _alert_sent_cache.pop(cache_key, None)


def register_price_alert_callback(bot) -> None:
    """
    Register the price alert callback with the PriceMonitor.

    This should be called during bot startup to enable SL/TP alerts.

    Args:
        bot: The Telegram bot instance.
    """
    from services.price_monitor import get_price_monitor

    async def alert_callback(alert) -> None:
        await _send_price_alert(alert, bot)

    monitor = get_price_monitor()
    monitor.register_callback(alert_callback)

    logger.info("Price alert callback registered")


def clear_trade_alert_cache(trade_id: int) -> None:
    """
    Clear the alert cache for a trade.

    Call this when a trade is closed to allow alerts if it's reopened.

    Args:
        trade_id: The trade ID to clear.
    """
    from services.price_monitor import AlertType

    for alert_type in AlertType:
        cache_key = (trade_id, alert_type.value)
        _alert_sent_cache.pop(cache_key, None)


# ============================================================================
# ADVANCED FIELD EDITING HANDLERS (F5, F6, F7)
# ============================================================================


def edit_screenshot_keyboard(trade_id: int, has_screenshot: bool) -> InlineKeyboardMarkup:
    """
    Create keyboard for screenshot editing options.

    Args:
        trade_id: The trade ID.
        has_screenshot: Whether the trade has a screenshot.

    Returns:
        InlineKeyboardMarkup: Screenshot action keyboard.
    """
    keyboard = []

    if has_screenshot:
        keyboard.append([
            InlineKeyboardButton("Replace Screenshot", callback_data=f"screenshot_replace_{trade_id}"),
        ])
        keyboard.append([
            InlineKeyboardButton("Remove Screenshot", callback_data=f"screenshot_remove_{trade_id}"),
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("Add Screenshot", callback_data=f"screenshot_replace_{trade_id}"),
        ])

    keyboard.append([
        InlineKeyboardButton("Back", callback_data=f"trade_edit_{trade_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def edit_tags_keyboard(
    tags: list[tuple[int, str]],
    selected_ids: set[int],
    trade_id: int,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for tag multi-select editing.

    Args:
        tags: List of (tag_id, tag_name) tuples.
        selected_ids: Set of selected tag IDs.
        trade_id: The trade ID.

    Returns:
        InlineKeyboardMarkup: Tag selection keyboard.
    """
    keyboard = []

    # Add tag buttons in pairs (2 per row)
    row = []
    for tag_id, tag_name in tags:
        # Add checkmark for selected tags
        display_name = f"[x] {tag_name}" if tag_id in selected_ids else tag_name
        row.append(
            InlineKeyboardButton(
                display_name,
                callback_data=f"edit_tag_toggle_{tag_id}",
            )
        )

        # Two buttons per row
        if len(row) == 2:
            keyboard.append(row)
            row = []

    # Add remaining button if odd number
    if row:
        keyboard.append(row)

    # Add save and cancel buttons
    keyboard.append([
        InlineKeyboardButton("Save Tags", callback_data=f"edit_tags_save_{trade_id}"),
        InlineKeyboardButton("Clear All", callback_data=f"edit_tags_clear_{trade_id}"),
    ])
    keyboard.append([
        InlineKeyboardButton("Back", callback_data=f"trade_edit_{trade_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


def edit_strategy_keyboard(
    strategies: list[tuple[int, str]],
    current_strategy_id: Optional[int],
    trade_id: int,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for strategy selection.

    Args:
        strategies: List of (strategy_id, strategy_name) tuples.
        current_strategy_id: Currently selected strategy ID (or None).
        trade_id: The trade ID.

    Returns:
        InlineKeyboardMarkup: Strategy selection keyboard.
    """
    keyboard = []

    # Add strategy buttons (one per row)
    for strategy_id, strategy_name in strategies:
        # Mark current strategy
        display_name = f"[x] {strategy_name}" if strategy_id == current_strategy_id else strategy_name
        keyboard.append([
            InlineKeyboardButton(
                display_name,
                callback_data=f"edit_strategy_select_{strategy_id}",
            )
        ])

    # Add clear option if strategy is set
    if current_strategy_id:
        keyboard.append([
            InlineKeyboardButton("Clear Strategy", callback_data=f"edit_strategy_clear_{trade_id}"),
        ])

    # Add back button
    keyboard.append([
        InlineKeyboardButton("Back", callback_data=f"trade_edit_{trade_id}"),
    ])

    return InlineKeyboardMarkup(keyboard)


async def handle_edit_screenshot(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade screenshot.

    Shows options to replace or remove the screenshot.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_screenshot_", "")
    try:
        trade_id = int(trade_id_str)
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
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            has_screenshot = bool(trade.screenshot_path)

            status_text = "Current: Screenshot attached" if has_screenshot else "Current: No screenshot"

            await query.edit_message_text(
                f"Edit Screenshot\n\n{status_text}\n\nSelect an option:",
                reply_markup=edit_screenshot_keyboard(trade_id, has_screenshot),
            )

    except Exception as e:
        logger.error("Error loading screenshot edit", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_screenshot_replace(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle screenshot replace request.

    Prompts user to upload a new photo.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    trade_id_str = query.data.replace("screenshot_replace_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    context.user_data[EDIT_WIZARD_KEY] = {
        "trade_id": trade_id,
        "field": "screenshot_upload",
    }

    await query.edit_message_text(
        "Send a photo to use as the trade screenshot.\n\n"
        "Upload your chart screenshot now:",
        reply_markup=back_cancel_keyboard(
            back_data=f"edit_field_screenshot_{trade_id}",
            cancel_data="edit_cancel",
        ),
    )


async def handle_screenshot_remove(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle screenshot removal.

    Removes the screenshot from the trade.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("screenshot_remove_", "")
    try:
        trade_id = int(trade_id_str)
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
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Remove screenshot file if exists
            if trade.screenshot_path and os.path.exists(trade.screenshot_path):
                try:
                    os.remove(trade.screenshot_path)
                except OSError:
                    pass  # File may already be gone

            trade.screenshot_path = None
            await session.flush()

            logger.info(
                "Trade screenshot removed",
                trade_id=trade_id,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                "Screenshot removed successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error removing screenshot", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_screenshot_upload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle screenshot photo upload during edit.

    This is called by the photo message handler when editing screenshots.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.photo or not update.effective_user:
        return

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "screenshot_upload":
        return

    trade_id = edit_data.get("trade_id")
    telegram_id = update.effective_user.id

    # Get the highest resolution photo
    photo = update.message.photo[-1]

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await update.message.reply_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            # Remove old screenshot if exists
            if trade.screenshot_path and os.path.exists(trade.screenshot_path):
                try:
                    os.remove(trade.screenshot_path)
                except OSError:
                    pass

            # Save new screenshot
            screenshots_dir = os.path.join(os.getcwd(), "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            file = await context.bot.get_file(photo.file_id)
            screenshot_path = os.path.join(screenshots_dir, f"trade_{trade.id}.jpg")
            await file.download_to_drive(screenshot_path)

            trade.screenshot_path = screenshot_path
            await session.flush()

            logger.info(
                "Trade screenshot updated",
                trade_id=trade_id,
                telegram_id=telegram_id,
            )

            await update.message.reply_text(
                "Screenshot updated successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating screenshot", error=str(e), trade_id=trade_id)
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)


async def handle_edit_tags(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade tags.

    Shows multi-select keyboard for tag toggling.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_tags_", "")
    try:
        trade_id = int(trade_id_str)
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
                select(Trade)
                .options(
                    selectinload(Trade.account),
                    selectinload(Trade.trade_tags).selectinload(TradeTag.tag),
                )
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get all available tags
            tags = await get_all_tags(session)

            # Get currently selected tag IDs
            current_tag_ids = {tt.tag_id for tt in trade.trade_tags}

            # Store in user_data for toggle handling
            context.user_data[EDIT_WIZARD_KEY] = {
                "trade_id": trade_id,
                "field": "tags",
                "selected_tags": current_tag_ids.copy(),
            }

            await query.edit_message_text(
                "Edit Tags\n\nTap a tag to toggle selection:",
                reply_markup=edit_tags_keyboard(tags, current_tag_ids, trade_id),
            )

    except Exception as e:
        logger.error("Error loading tags edit", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_edit_tag_toggle(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle tag toggle during edit.

    Toggles tag selection state in user_data.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "tags":
        return

    tag_id_str = query.data.replace("edit_tag_toggle_", "")
    try:
        tag_id = int(tag_id_str)
    except ValueError:
        return

    trade_id = edit_data.get("trade_id")
    selected_tags = edit_data.get("selected_tags", set())

    # Toggle tag
    if tag_id in selected_tags:
        selected_tags.discard(tag_id)
    else:
        selected_tags.add(tag_id)

    edit_data["selected_tags"] = selected_tags

    try:
        async with get_session() as session:
            tags = await get_all_tags(session)

            await query.edit_message_text(
                "Edit Tags\n\nTap a tag to toggle selection:",
                reply_markup=edit_tags_keyboard(tags, selected_tags, trade_id),
            )

    except Exception as e:
        logger.error("Error toggling tag", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_edit_tags_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle clearing all selected tags.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "tags":
        return

    trade_id_str = query.data.replace("edit_tags_clear_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    # Clear all selected tags
    edit_data["selected_tags"] = set()

    try:
        async with get_session() as session:
            tags = await get_all_tags(session)

            await query.edit_message_text(
                "Edit Tags\n\nTap a tag to toggle selection:",
                reply_markup=edit_tags_keyboard(tags, set(), trade_id),
            )

    except Exception as e:
        logger.error("Error clearing tags", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_edit_tags_save(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle saving tag changes.

    Updates the trade's tags in the database.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "tags":
        # Stale state - return silently
        return

    trade_id_str = query.data.replace("edit_tags_save_", "")
    try:
        trade_id = int(trade_id_str)
    except ValueError:
        return

    telegram_id = update.effective_user.id
    selected_tags = edit_data.get("selected_tags", set())

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(
                    selectinload(Trade.account),
                    selectinload(Trade.trade_tags),
                )
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            # Remove existing trade_tags
            for tt in trade.trade_tags[:]:
                await session.delete(tt)

            # Add new trade_tags
            for tag_id in selected_tags:
                trade_tag = TradeTag(trade_id=trade_id, tag_id=tag_id)
                session.add(trade_tag)

            await session.flush()

            logger.info(
                "Trade tags updated",
                trade_id=trade_id,
                tag_count=len(selected_tags),
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                f"Tags updated successfully! ({len(selected_tags)} tags selected)",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error saving tags", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)


async def handle_edit_strategy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle editing trade strategy.

    Shows strategy selection keyboard.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_field_strategy_", "")
    try:
        trade_id = int(trade_id_str)
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
                select(Trade)
                .options(
                    selectinload(Trade.account),
                    selectinload(Trade.strategy),
                )
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get user's strategies
            strategies = await get_user_strategies(session, user.id)

            if not strategies:
                await query.edit_message_text(
                    "You haven't created any strategies yet.\n\n"
                    "Go to Strategies from the main menu to create one.",
                    reply_markup=back_cancel_keyboard(
                        back_data=f"trade_edit_{trade_id}",
                        cancel_data="edit_cancel",
                    ),
                )
                return

            context.user_data[EDIT_WIZARD_KEY] = {
                "trade_id": trade_id,
                "field": "strategy",
            }

            current_strategy_name = trade.strategy.name if trade.strategy else "None"

            await query.edit_message_text(
                f"Edit Strategy\n\nCurrent: {current_strategy_name}\n\nSelect a strategy:",
                reply_markup=edit_strategy_keyboard(strategies, trade.strategy_id, trade_id),
            )

    except Exception as e:
        logger.error("Error loading strategy edit", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_edit_strategy_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle strategy selection during edit.

    Updates the trade's strategy.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if not edit_data or edit_data.get("field") != "strategy":
        return

    strategy_id_str = query.data.replace("edit_strategy_select_", "")
    try:
        new_strategy_id = int(strategy_id_str)
    except ValueError:
        return

    trade_id = edit_data.get("trade_id")
    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            result = await session.execute(
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            # Verify strategy belongs to user
            strategy_result = await session.execute(
                select(Strategy)
                .where(Strategy.id == new_strategy_id)
                .where(Strategy.user_id == user.id)
            )
            strategy = strategy_result.scalar_one_or_none()

            if not strategy:
                await query.edit_message_text(
                    "Strategy not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_WIZARD_KEY, None)
                return

            trade.strategy_id = new_strategy_id
            await session.flush()

            logger.info(
                "Trade strategy updated",
                trade_id=trade_id,
                strategy_id=new_strategy_id,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                f"Strategy updated to: {strategy.name}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating strategy", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)


async def handle_edit_strategy_clear(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle clearing trade strategy.

    Removes the strategy from the trade.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    trade_id_str = query.data.replace("edit_strategy_clear_", "")
    try:
        trade_id = int(trade_id_str)
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
                select(Trade)
                .options(selectinload(Trade.account))
                .where(Trade.id == trade_id)
            )
            trade = result.scalar_one_or_none()

            if not trade or trade.account.user_id != user.id:
                await query.edit_message_text(
                    "Trade not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            trade.strategy_id = None
            await session.flush()

            logger.info(
                "Trade strategy cleared",
                trade_id=trade_id,
                telegram_id=telegram_id,
            )

            await query.edit_message_text(
                "Strategy cleared successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error clearing strategy", error=str(e), trade_id=trade_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_WIZARD_KEY, None)
