"""
AI Chat handlers for the Telegram Trade Journal Bot.

This module provides:
- AI conversation mode with persistent history
- Trade data context for AI responses
- Rate limiting and conversation management
- AI action detection and execution (add trades, add accounts)
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
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
from database.models import Account, Trade, TradeDirection, TradeStatus
from handlers.accounts import get_user_by_telegram_id
from services.ai_action_service import AIActionType, get_ai_action_service
from services.ai_service import get_ai_service
from services.analytics_service import get_analytics_service
from utils.keyboards import back_to_menu_keyboard

logger = get_logger(__name__)

# Conversation states
AI_CHATTING = 0
AI_ACTION_CONFIRM = 1

# Context keys
AI_CHAT_KEY = "ai_chat_active"
PENDING_AI_ACTION_KEY = "pending_ai_action"

# Maximum message length for Telegram
MAX_MESSAGE_LENGTH = 4096


def ai_chat_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for AI chat mode with clear history and back options.

    Users can clear conversation history or exit AI chat via menu navigation.

    Returns:
        InlineKeyboardMarkup: AI chat control keyboard with Clear History and Back to Menu.
    """
    keyboard = [
        [InlineKeyboardButton("Clear History", callback_data="ai_clear_history")],
        [InlineKeyboardButton("Back to Menu", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def ai_chat_exit_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard shown when exiting AI chat.

    Returns:
        InlineKeyboardMarkup: Exit confirmation keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Back to Menu", callback_data="menu_main"),
            InlineKeyboardButton("New Chat", callback_data="menu_ask_ai"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def ai_action_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for confirming or canceling AI-requested actions.

    Returns:
        InlineKeyboardMarkup: Confirmation keyboard with Confirm and Cancel buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton("Confirm", callback_data="ai_action_confirm"),
            InlineKeyboardButton("Cancel", callback_data="ai_action_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def split_long_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """
    Split a long message into chunks that fit Telegram's limits.

    Args:
        text: The text to split.
        max_length: Maximum length per chunk.

    Returns:
        list[str]: List of message chunks.
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    current_chunk = ""

    # Try to split on paragraph breaks first
    paragraphs = text.split("\n\n")

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_length:
            if current_chunk:
                current_chunk += "\n\n" + para
            else:
                current_chunk = para
        else:
            # If current chunk is not empty, save it
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            # If single paragraph is too long, split by sentences
            if len(para) > max_length:
                sentences = para.replace(". ", ".\n").split("\n")
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) + 1 <= max_length:
                        if current_chunk:
                            current_chunk += " " + sentence
                        else:
                            current_chunk = sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        # If single sentence is still too long, hard split
                        if len(sentence) > max_length:
                            for i in range(0, len(sentence), max_length - 10):
                                chunks.append(sentence[i:i + max_length - 10])
                            current_chunk = ""
                        else:
                            current_chunk = sentence
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def get_trade_context(telegram_id: int) -> Optional[str]:
    """
    Get the trade context for a user to include in AI prompts.

    Args:
        telegram_id: The Telegram user ID.

    Returns:
        Optional[str]: Trade context string or None if no data.
    """
    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return None

            analytics_service = get_analytics_service()
            context = await analytics_service.get_trade_context_for_ai(user.id)
            return context

    except Exception as e:
        logger.error("Error getting trade context", error=str(e), telegram_id=telegram_id)
        return None


async def start_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Start the AI chat conversation mode.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING).
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    telegram_id = update.effective_user.id

    ai_service = get_ai_service()
    if not ai_service.is_configured:
        await query.edit_message_text(
            "AI service is not configured. Please contact support.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    # Get conversation history length
    history_len = ai_service.get_conversation_length(telegram_id)

    # Build welcome message
    if history_len > 0:
        welcome_msg = (
            "Welcome back to AI Chat!\n\n"
            f"I have {history_len} messages in our conversation history.\n\n"
            "Feel free to continue our discussion, or use the buttons below "
            "to clear history and start fresh.\n\n"
            "Send me a message to get started!"
        )
    else:
        welcome_msg = (
            "Welcome to AI Chat!\n\n"
            "I'm your trading journal assistant. I have access to your trading data "
            "and can provide data-driven, honest feedback about your performance.\n\n"
            "Ask me anything about:\n"
            "- Your trading performance\n"
            "- Strategy improvements\n"
            "- Trade analysis\n"
            "- Trading concepts\n\n"
            "Send me a message to get started!"
        )

    context.user_data[AI_CHAT_KEY] = True

    await query.edit_message_text(
        text=welcome_msg,
        reply_markup=ai_chat_keyboard(),
    )

    return AI_CHATTING


async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle a user message in AI chat mode.

    Processes user messages, gets AI responses, and detects any action requests
    (like adding trades or accounts) that require user confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING or AI_ACTION_CONFIRM).
    """
    if not update.message or not update.message.text or not update.effective_user:
        return AI_CHATTING

    telegram_id = update.effective_user.id
    user_message = update.message.text.strip()

    if not user_message:
        return AI_CHATTING

    ai_service = get_ai_service()

    # Check rate limit
    is_limited, wait_time = ai_service.check_rate_limit(telegram_id)
    if is_limited:
        await update.message.reply_text(
            f"You're sending messages too quickly. Please wait {wait_time} seconds.",
            reply_markup=ai_chat_keyboard(),
        )
        return AI_CHATTING

    # Show typing indicator
    await update.message.chat.send_action(ChatAction.TYPING)

    # Get trade context for this user
    trade_context = await get_trade_context(telegram_id)

    # Get AI response
    response, error = await ai_service.chat_with_context(
        user_id=telegram_id,
        user_message=user_message,
        trade_context=trade_context,
    )

    if error:
        await update.message.reply_text(
            f"Sorry, I encountered an error: {error}",
            reply_markup=ai_chat_keyboard(),
        )
        return AI_CHATTING

    if not response:
        await update.message.reply_text(
            "I didn't receive a response. Please try again.",
            reply_markup=ai_chat_keyboard(),
        )
        return AI_CHATTING

    # Parse response for AI actions
    ai_action_service = get_ai_action_service()
    action = ai_action_service.parse_ai_response(response)

    # Check if action was detected and requires confirmation
    if action and action.action_type != AIActionType.NONE and action.requires_confirmation:
        # Validate the action data before showing confirmation
        is_valid, errors = _validate_action_data(action)

        if is_valid:
            # Store pending action in context
            context.user_data[PENDING_AI_ACTION_KEY] = {
                "action": action.to_dict(),
                "telegram_id": telegram_id,
            }

            # Build confirmation message
            confirmation_text = _build_action_confirmation_message(action, response)

            # Send the AI response text first (without the JSON block)
            clean_response = _strip_json_from_response(response)
            if clean_response.strip():
                chunks = split_long_message(clean_response)
                for chunk in chunks:
                    try:
                        await update.message.reply_text(
                            text=chunk,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                    except Exception:
                        await update.message.reply_text(text=chunk)

            # Send the confirmation prompt
            await update.message.reply_text(
                text=confirmation_text,
                reply_markup=ai_action_confirm_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )

            logger.info(
                "AI action detected, awaiting confirmation",
                telegram_id=telegram_id,
                action_type=action.action_type.value,
            )

            return AI_ACTION_CONFIRM
        else:
            # Action data is invalid, show response with validation errors
            logger.warning(
                "AI action validation failed",
                telegram_id=telegram_id,
                action_type=action.action_type.value,
                errors=errors,
            )
            # Fall through to show normal response

    # No action detected or action doesn't require confirmation - show normal response
    chunks = split_long_message(response)

    for i, chunk in enumerate(chunks):
        # Only add keyboard to last message
        reply_markup = ai_chat_keyboard() if i == len(chunks) - 1 else None

        try:
            await update.message.reply_text(
                text=chunk,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            # Fall back to plain text if markdown fails
            await update.message.reply_text(
                text=chunk,
                reply_markup=reply_markup,
            )

    logger.info(
        "AI chat message processed",
        telegram_id=telegram_id,
        input_length=len(user_message),
        output_length=len(response),
        chunks=len(chunks),
    )

    return AI_CHATTING


def _validate_action_data(action) -> tuple[bool, list[str]]:
    """
    Validate the data in an AI action.

    Args:
        action: The AIAction to validate.

    Returns:
        tuple[bool, list[str]]: (is_valid, list of error messages)
    """
    ai_action_service = get_ai_action_service()

    if action.action_type == AIActionType.ADD_TRADE:
        return ai_action_service.validate_trade_data(action.data)
    elif action.action_type == AIActionType.ADD_ACCOUNT:
        return ai_action_service.validate_account_data(action.data)
    elif action.action_type == AIActionType.EDIT_TRADE:
        return _validate_edit_trade_data(action.data)
    elif action.action_type == AIActionType.EDIT_ACCOUNT:
        return _validate_edit_account_data(action.data)

    return True, []


def _validate_edit_trade_data(data: dict) -> tuple[bool, list[str]]:
    """
    Validate edit trade action data.

    Required structure:
    {
        "target": {"instrument": "DAX"} or {"trade_id": 123},
        "changes": {"sl_price": 18350.00, ...}
    }

    Args:
        data: Dictionary containing edit trade data.

    Returns:
        tuple[bool, list[str]]: (is_valid, list of error messages)
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["Edit trade data must be a dictionary"]

    # Check for target
    target = data.get("target")
    if not target:
        errors.append("Missing 'target' field - need instrument or trade_id to identify trade")
    elif not isinstance(target, dict):
        errors.append("'target' must be a dictionary with 'instrument' or 'trade_id'")
    elif not target.get("instrument") and not target.get("trade_id"):
        errors.append("'target' must contain either 'instrument' or 'trade_id'")

    # Check for changes
    changes = data.get("changes")
    if not changes:
        errors.append("Missing 'changes' field - need at least one field to update")
    elif not isinstance(changes, dict):
        errors.append("'changes' must be a dictionary of fields to update")
    elif len(changes) == 0:
        errors.append("'changes' must contain at least one field to update")
    else:
        # Validate editable fields
        editable_fields = {"sl_price", "tp_price", "entry_price", "exit_price", "lot_size", "notes", "status"}
        for field_name in changes.keys():
            if field_name not in editable_fields:
                errors.append(f"Field '{field_name}' is not editable. Editable: {', '.join(editable_fields)}")

        # Validate price fields if present
        for price_field in ["sl_price", "tp_price", "entry_price", "exit_price"]:
            if price_field in changes and changes[price_field] is not None:
                try:
                    price = float(changes[price_field])
                    if price <= 0:
                        errors.append(f"{price_field} must be positive")
                except (ValueError, TypeError):
                    errors.append(f"Invalid {price_field}: must be a number")

        # Validate lot_size if present
        if "lot_size" in changes and changes["lot_size"] is not None:
            try:
                lot_size = float(changes["lot_size"])
                if lot_size <= 0:
                    errors.append("lot_size must be positive")
            except (ValueError, TypeError):
                errors.append("Invalid lot_size: must be a number")

        # Validate status if present
        if "status" in changes and changes["status"] is not None:
            valid_statuses = {"open", "closed", "cancelled"}
            if str(changes["status"]).lower() not in valid_statuses:
                errors.append(f"Invalid status: must be one of {', '.join(valid_statuses)}")

    return len(errors) == 0, errors


def _validate_edit_account_data(data: dict) -> tuple[bool, list[str]]:
    """
    Validate edit account action data.

    Required structure:
    {
        "target": {"name": "Main Account"} or {"account_id": 1},
        "changes": {"broker": "Interactive Brokers", ...}
    }

    Args:
        data: Dictionary containing edit account data.

    Returns:
        tuple[bool, list[str]]: (is_valid, list of error messages)
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["Edit account data must be a dictionary"]

    # Check for target
    target = data.get("target")
    if not target:
        errors.append("Missing 'target' field - need name or account_id to identify account")
    elif not isinstance(target, dict):
        errors.append("'target' must be a dictionary with 'name' or 'account_id'")
    elif not target.get("name") and not target.get("account_id"):
        errors.append("'target' must contain either 'name' or 'account_id'")

    # Check for changes
    changes = data.get("changes")
    if not changes:
        errors.append("Missing 'changes' field - need at least one field to update")
    elif not isinstance(changes, dict):
        errors.append("'changes' must be a dictionary of fields to update")
    elif len(changes) == 0:
        errors.append("'changes' must contain at least one field to update")
    else:
        # Validate editable fields
        editable_fields = {"name", "broker", "currency", "is_active"}
        for field_name in changes.keys():
            if field_name not in editable_fields:
                errors.append(f"Field '{field_name}' is not editable. Editable: {', '.join(editable_fields)}")

        # Validate name if present
        if "name" in changes and changes["name"] is not None:
            if not isinstance(changes["name"], str) or len(changes["name"].strip()) == 0:
                errors.append("Account name must be a non-empty string")

        # Validate currency if present
        if "currency" in changes and changes["currency"] is not None:
            if not isinstance(changes["currency"], str) or len(changes["currency"].strip()) == 0:
                errors.append("Currency must be a non-empty string")

        # Validate is_active if present
        if "is_active" in changes and changes["is_active"] is not None:
            if not isinstance(changes["is_active"], bool):
                errors.append("is_active must be a boolean")

    return len(errors) == 0, errors


def _strip_json_from_response(response: str) -> str:
    """
    Remove JSON code blocks from the AI response text.

    Args:
        response: The original AI response with potential JSON blocks.

    Returns:
        str: The response with JSON code blocks removed.
    """
    import re

    # Remove markdown JSON code blocks
    cleaned = re.sub(r"```json\s*[\s\S]*?\s*```", "", response, flags=re.IGNORECASE)

    # Also remove any bare JSON objects that look like actions
    # Be careful to only remove action-related JSON
    cleaned = re.sub(r'\{[^{}]*"action"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', "", cleaned)

    return cleaned.strip()


def _build_action_confirmation_message(action, response: str) -> str:
    """
    Build a user-friendly confirmation message for an AI action.

    Args:
        action: The AIAction requiring confirmation.
        response: The original AI response.

    Returns:
        str: Formatted confirmation message.
    """
    if action.confirmation_message:
        base_message = action.confirmation_message
    else:
        # Build a default confirmation message based on action type
        if action.action_type == AIActionType.ADD_TRADE:
            data = action.data
            instrument = data.get("instrument", "Unknown")
            direction = data.get("direction", "Unknown").upper()
            entry_price = data.get("entry_price", "Unknown")
            lot_size = data.get("lot_size", 1.0)

            base_message = (
                f"Add a new trade:\n"
                f"  Instrument: {instrument}\n"
                f"  Direction: {direction}\n"
                f"  Entry Price: {entry_price}\n"
                f"  Lot Size: {lot_size}"
            )

            # Add optional fields if present
            if data.get("sl_price"):
                base_message += f"\n  Stop Loss: {data['sl_price']}"
            if data.get("tp_price"):
                base_message += f"\n  Take Profit: {data['tp_price']}"

        elif action.action_type == AIActionType.ADD_ACCOUNT:
            data = action.data
            name = data.get("name", "Unknown")
            balance = data.get("starting_balance", 0)
            currency = data.get("currency", "USD")

            base_message = (
                f"Create a new account:\n"
                f"  Name: {name}\n"
                f"  Starting Balance: {balance} {currency}"
            )

            if data.get("broker"):
                base_message += f"\n  Broker: {data['broker']}"

        elif action.action_type == AIActionType.EDIT_TRADE:
            base_message = _build_edit_trade_confirmation(action.data)

        elif action.action_type == AIActionType.EDIT_ACCOUNT:
            base_message = _build_edit_account_confirmation(action.data)

        else:
            base_message = "Perform an action"

    return f"*Action Required*\n\n{base_message}\n\nDo you want to proceed?"


def _build_edit_trade_confirmation(data: dict) -> str:
    """
    Build a confirmation message for editing a trade.

    Args:
        data: Dictionary containing target and changes.

    Returns:
        str: Formatted confirmation message.
    """
    target = data.get("target", {})
    changes = data.get("changes", {})

    # Build target description
    if target.get("trade_id"):
        target_desc = f"trade #{target['trade_id']}"
    elif target.get("instrument"):
        target_desc = f"most recent open {target['instrument']} trade"
    else:
        target_desc = "trade (unknown target)"

    # Build changes description
    changes_lines = []
    field_labels = {
        "sl_price": "Stop Loss",
        "tp_price": "Take Profit",
        "entry_price": "Entry Price",
        "exit_price": "Exit Price",
        "lot_size": "Lot Size",
        "notes": "Notes",
        "status": "Status",
    }

    for field, value in changes.items():
        label = field_labels.get(field, field)
        if value is None:
            changes_lines.append(f"  {label}: (clear)")
        else:
            changes_lines.append(f"  {label}: {value}")

    changes_text = "\n".join(changes_lines) if changes_lines else "  (no changes specified)"

    return f"Edit {target_desc}:\n{changes_text}"


def _build_edit_account_confirmation(data: dict) -> str:
    """
    Build a confirmation message for editing an account.

    Args:
        data: Dictionary containing target and changes.

    Returns:
        str: Formatted confirmation message.
    """
    target = data.get("target", {})
    changes = data.get("changes", {})

    # Build target description
    if target.get("account_id"):
        target_desc = f"account #{target['account_id']}"
    elif target.get("name"):
        target_desc = f"account '{target['name']}'"
    else:
        target_desc = "account (unknown target)"

    # Build changes description
    changes_lines = []
    field_labels = {
        "name": "Name",
        "broker": "Broker",
        "currency": "Currency",
        "is_active": "Active",
    }

    for field, value in changes.items():
        label = field_labels.get(field, field)
        if value is None:
            changes_lines.append(f"  {label}: (clear)")
        elif isinstance(value, bool):
            changes_lines.append(f"  {label}: {'Yes' if value else 'No'}")
        else:
            changes_lines.append(f"  {label}: {value}")

    changes_text = "\n".join(changes_lines) if changes_lines else "  (no changes specified)"

    return f"Edit {target_desc}:\n{changes_text}"


async def handle_ai_action_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle confirmation of an AI-requested action.

    Executes the pending action (add trade, add account, etc.) and shows
    the result to the user.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING).
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return AI_CHATTING

    await query.answer("Processing...")

    telegram_id = update.effective_user.id

    # Get the pending action
    pending_action = context.user_data.get(PENDING_AI_ACTION_KEY)
    if not pending_action:
        await query.edit_message_text(
            "No pending action found. Please try again.",
            reply_markup=ai_chat_keyboard(),
        )
        return AI_CHATTING

    action_dict = pending_action.get("action", {})
    action_type = action_dict.get("action_type")
    action_data = action_dict.get("data", {})

    try:
        if action_type == AIActionType.ADD_TRADE.value:
            result = await _execute_add_trade(telegram_id, action_data)
        elif action_type == AIActionType.ADD_ACCOUNT.value:
            result = await _execute_add_account(telegram_id, action_data)
        elif action_type == AIActionType.EDIT_TRADE.value:
            result = await _execute_edit_trade(telegram_id, action_data)
        elif action_type == AIActionType.EDIT_ACCOUNT.value:
            result = await _execute_edit_account(telegram_id, action_data)
        else:
            result = (False, f"Unknown action type: {action_type}")

        success, message = result

        if success:
            logger.info(
                "AI action executed successfully",
                telegram_id=telegram_id,
                action_type=action_type,
            )
            await query.edit_message_text(
                f"Action completed successfully!\n\n{message}",
                reply_markup=ai_chat_keyboard(),
            )
        else:
            logger.warning(
                "AI action execution failed",
                telegram_id=telegram_id,
                action_type=action_type,
                error=message,
            )
            await query.edit_message_text(
                f"Action failed: {message}",
                reply_markup=ai_chat_keyboard(),
            )

    except Exception as e:
        logger.error(
            "Error executing AI action",
            telegram_id=telegram_id,
            action_type=action_type,
            error=str(e),
        )
        await query.edit_message_text(
            f"An error occurred: {str(e)}",
            reply_markup=ai_chat_keyboard(),
        )

    # Clear the pending action
    context.user_data.pop(PENDING_AI_ACTION_KEY, None)

    return AI_CHATTING


async def handle_ai_action_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle cancellation of an AI-requested action.

    Clears the pending action and returns to normal chat mode.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING).
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return AI_CHATTING

    await query.answer("Action cancelled.")

    telegram_id = update.effective_user.id

    # Clear the pending action
    context.user_data.pop(PENDING_AI_ACTION_KEY, None)

    await query.edit_message_text(
        "Action cancelled. You can continue chatting or ask me something else.",
        reply_markup=ai_chat_keyboard(),
    )

    logger.info("AI action cancelled by user", telegram_id=telegram_id)

    return AI_CHATTING


async def _execute_add_trade(
    telegram_id: int, data: dict
) -> tuple[bool, str]:
    """
    Execute the add trade action.

    Args:
        telegram_id: The user's Telegram ID.
        data: Dictionary containing trade data.

    Returns:
        tuple[bool, str]: (success, message)
    """
    try:
        async with get_session() as session:
            # Get user
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return False, "User not found. Please start the bot first."

            # Get user's default (first active) account
            result = await session.execute(
                select(Account).where(
                    Account.user_id == user.id,
                    Account.is_active == True
                ).order_by(Account.id).limit(1)
            )
            account = result.scalar_one_or_none()

            if not account:
                return False, "No active account found. Please create an account first."

            # Parse direction
            direction_str = data.get("direction", "long").upper()
            direction = TradeDirection.LONG if direction_str == "LONG" else TradeDirection.SHORT

            # Create the trade
            trade = Trade(
                account_id=account.id,
                instrument=data["instrument"].upper(),
                direction=direction,
                entry_price=Decimal(str(data["entry_price"])),
                lot_size=Decimal(str(data.get("lot_size", 1.0))),
                status=TradeStatus.OPEN,
                sl_price=Decimal(str(data["sl_price"])) if data.get("sl_price") else None,
                tp_price=Decimal(str(data["tp_price"])) if data.get("tp_price") else None,
                notes=data.get("notes"),
            )
            session.add(trade)
            await session.flush()

            logger.info(
                "Trade created via AI action",
                trade_id=trade.id,
                instrument=trade.instrument,
                direction=trade.direction.value,
                telegram_id=telegram_id,
            )

            return True, (
                f"Trade #{trade.id} created:\n"
                f"  {trade.instrument} {direction_str}\n"
                f"  Entry: {trade.entry_price}\n"
                f"  Size: {trade.lot_size}\n"
                f"  Account: {account.name}"
            )

    except Exception as e:
        logger.error(
            "Error creating trade via AI action",
            error=str(e),
            telegram_id=telegram_id,
        )
        return False, f"Database error: {str(e)}"


async def _execute_add_account(
    telegram_id: int, data: dict
) -> tuple[bool, str]:
    """
    Execute the add account action.

    Args:
        telegram_id: The user's Telegram ID.
        data: Dictionary containing account data.

    Returns:
        tuple[bool, str]: (success, message)
    """
    try:
        async with get_session() as session:
            # Get user
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return False, "User not found. Please start the bot first."

            # Parse balance
            starting_balance = Decimal(str(data["starting_balance"]))
            currency = data.get("currency", "USD").upper()

            # Create the account
            account = Account(
                user_id=user.id,
                name=data["name"].strip(),
                broker=data.get("broker", "").strip() if data.get("broker") else None,
                starting_balance=starting_balance,
                current_balance=starting_balance,
                currency=currency,
                is_active=True,
            )
            session.add(account)
            await session.flush()

            logger.info(
                "Account created via AI action",
                account_id=account.id,
                name=account.name,
                telegram_id=telegram_id,
            )

            return True, (
                f"Account '{account.name}' created:\n"
                f"  Balance: {account.starting_balance} {account.currency}\n"
                f"  Broker: {account.broker or 'Not specified'}"
            )

    except Exception as e:
        logger.error(
            "Error creating account via AI action",
            error=str(e),
            telegram_id=telegram_id,
        )
        return False, f"Database error: {str(e)}"


async def _execute_edit_trade(
    telegram_id: int, data: dict
) -> tuple[bool, str]:
    """
    Execute the edit trade action.

    Finds a trade by target criteria (instrument or trade_id) and applies
    the specified changes.

    Args:
        telegram_id: The user's Telegram ID.
        data: Dictionary containing target and changes.
            Expected format:
            {
                "target": {"instrument": "DAX"} or {"trade_id": 123},
                "changes": {"sl_price": 18350.00, "tp_price": 18750.00, ...}
            }

    Returns:
        tuple[bool, str]: (success, message)
    """
    target = data.get("target", {})
    changes = data.get("changes", {})

    if not target or not changes:
        return False, "Invalid edit data: missing target or changes"

    try:
        async with get_session() as session:
            # Get user
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return False, "User not found. Please start the bot first."

            # Find the trade
            trade = await _find_trade_by_target(session, user.id, target)

            if not trade:
                if target.get("trade_id"):
                    return False, f"Trade #{target['trade_id']} not found or doesn't belong to you."
                elif target.get("instrument"):
                    return False, f"No open trade found for instrument '{target['instrument']}'."
                else:
                    return False, "Could not find the specified trade."

            # Store original values for logging
            original_values = {}
            updated_fields = []

            # Editable fields and their types
            price_fields = {"sl_price", "tp_price", "entry_price", "exit_price", "lot_size"}

            for field, value in changes.items():
                if not hasattr(trade, field):
                    logger.warning(
                        "Attempted to edit non-existent trade field",
                        field=field,
                        trade_id=trade.id,
                    )
                    continue

                original_values[field] = getattr(trade, field)

                # Handle different field types
                if field in price_fields:
                    if value is not None:
                        setattr(trade, field, Decimal(str(value)))
                    else:
                        setattr(trade, field, None)
                elif field == "status":
                    if value is not None:
                        setattr(trade, field, TradeStatus[str(value).upper()])
                else:
                    setattr(trade, field, value)

                updated_fields.append(field)

            if not updated_fields:
                return False, "No valid fields to update."

            await session.commit()

            logger.info(
                "Trade edited via AI action",
                trade_id=trade.id,
                instrument=trade.instrument,
                updated_fields=updated_fields,
                telegram_id=telegram_id,
            )

            # Build success message
            changes_summary = []
            field_labels = {
                "sl_price": "Stop Loss",
                "tp_price": "Take Profit",
                "entry_price": "Entry Price",
                "exit_price": "Exit Price",
                "lot_size": "Lot Size",
                "notes": "Notes",
                "status": "Status",
            }

            for field in updated_fields:
                label = field_labels.get(field, field)
                old_val = original_values.get(field)
                new_val = getattr(trade, field)

                if hasattr(old_val, "value"):
                    old_val = old_val.value
                if hasattr(new_val, "value"):
                    new_val = new_val.value

                changes_summary.append(f"  {label}: {old_val} -> {new_val}")

            return True, (
                f"Trade #{trade.id} ({trade.instrument}) updated:\n"
                + "\n".join(changes_summary)
            )

    except KeyError as e:
        logger.error(
            "Invalid status value in trade edit",
            error=str(e),
            telegram_id=telegram_id,
        )
        return False, f"Invalid status value: {e}"
    except Exception as e:
        logger.error(
            "Error editing trade via AI action",
            error=str(e),
            telegram_id=telegram_id,
        )
        return False, f"Database error: {str(e)}"


async def _find_trade_by_target(session, user_id: int, target: dict) -> Optional[Trade]:
    """
    Find a trade by target criteria.

    Args:
        session: Database session.
        user_id: The internal user ID.
        target: Dictionary with either 'trade_id' or 'instrument'.

    Returns:
        Optional[Trade]: The found trade or None.
    """
    if target.get("trade_id"):
        # Find by trade ID
        result = await session.execute(
            select(Trade)
            .join(Account)
            .where(
                Account.user_id == user_id,
                Trade.id == target["trade_id"],
            )
        )
        return result.scalar_one_or_none()

    elif target.get("instrument"):
        # Find most recent open trade for this instrument
        instrument = target["instrument"]
        result = await session.execute(
            select(Trade)
            .join(Account)
            .where(
                Account.user_id == user_id,
                Trade.instrument.ilike(f"%{instrument}%"),
                Trade.status == TradeStatus.OPEN,
            )
            .order_by(Trade.opened_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    return None


async def _execute_edit_account(
    telegram_id: int, data: dict
) -> tuple[bool, str]:
    """
    Execute the edit account action.

    Finds an account by target criteria (name or account_id) and applies
    the specified changes.

    Args:
        telegram_id: The user's Telegram ID.
        data: Dictionary containing target and changes.
            Expected format:
            {
                "target": {"name": "Main Account"} or {"account_id": 1},
                "changes": {"broker": "Interactive Brokers", "name": "New Name", ...}
            }

    Returns:
        tuple[bool, str]: (success, message)
    """
    target = data.get("target", {})
    changes = data.get("changes", {})

    if not target or not changes:
        return False, "Invalid edit data: missing target or changes"

    try:
        async with get_session() as session:
            # Get user
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                return False, "User not found. Please start the bot first."

            # Find the account
            account = await _find_account_by_target(session, user.id, target)

            if not account:
                if target.get("account_id"):
                    return False, f"Account #{target['account_id']} not found or doesn't belong to you."
                elif target.get("name"):
                    return False, f"Account '{target['name']}' not found."
                else:
                    return False, "Could not find the specified account."

            # Store original values for logging
            original_values = {}
            updated_fields = []

            # Editable fields for accounts
            editable_fields = {"name", "broker", "currency", "is_active"}

            for field, value in changes.items():
                if field not in editable_fields:
                    logger.warning(
                        "Attempted to edit non-editable account field",
                        field=field,
                        account_id=account.id,
                    )
                    continue

                if not hasattr(account, field):
                    continue

                original_values[field] = getattr(account, field)

                # Handle different field types
                if field == "currency" and value is not None:
                    setattr(account, field, str(value).upper())
                elif field == "name" and value is not None:
                    setattr(account, field, str(value).strip())
                elif field == "broker":
                    setattr(account, field, str(value).strip() if value else None)
                elif field == "is_active":
                    setattr(account, field, bool(value))
                else:
                    setattr(account, field, value)

                updated_fields.append(field)

            if not updated_fields:
                return False, "No valid fields to update."

            await session.commit()

            logger.info(
                "Account edited via AI action",
                account_id=account.id,
                account_name=account.name,
                updated_fields=updated_fields,
                telegram_id=telegram_id,
            )

            # Build success message
            changes_summary = []
            field_labels = {
                "name": "Name",
                "broker": "Broker",
                "currency": "Currency",
                "is_active": "Active",
            }

            for field in updated_fields:
                label = field_labels.get(field, field)
                old_val = original_values.get(field)
                new_val = getattr(account, field)

                if field == "is_active":
                    old_val = "Yes" if old_val else "No"
                    new_val = "Yes" if new_val else "No"

                changes_summary.append(f"  {label}: {old_val} -> {new_val}")

            return True, (
                f"Account #{account.id} ('{account.name}') updated:\n"
                + "\n".join(changes_summary)
            )

    except Exception as e:
        logger.error(
            "Error editing account via AI action",
            error=str(e),
            telegram_id=telegram_id,
        )
        return False, f"Database error: {str(e)}"


async def _find_account_by_target(session, user_id: int, target: dict) -> Optional[Account]:
    """
    Find an account by target criteria.

    Args:
        session: Database session.
        user_id: The internal user ID.
        target: Dictionary with either 'account_id' or 'name'.

    Returns:
        Optional[Account]: The found account or None.
    """
    if target.get("account_id"):
        # Find by account ID
        result = await session.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.id == target["account_id"],
            )
        )
        return result.scalar_one_or_none()

    elif target.get("name"):
        # Find by name (case-insensitive partial match)
        name = target["name"]
        result = await session.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.name.ilike(f"%{name}%"),
            ).limit(1)
        )
        return result.scalar_one_or_none()

    return None


async def handle_clear_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle the clear history button in AI chat.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING).
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return AI_CHATTING

    await query.answer("Conversation history cleared!")

    telegram_id = update.effective_user.id

    ai_service = get_ai_service()
    ai_service.clear_conversation(telegram_id)

    await query.edit_message_text(
        "Conversation history cleared!\n\n"
        "I've forgotten our previous conversation. "
        "Send a new message to start fresh.",
        reply_markup=ai_chat_keyboard(),
    )

    logger.info("AI chat history cleared", telegram_id=telegram_id)

    return AI_CHATTING


async def handle_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Handle the end chat button to exit AI conversation mode.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish the conversation.
    """
    query = update.callback_query
    if not query or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    context.user_data.pop(AI_CHAT_KEY, None)

    telegram_id = update.effective_user.id
    ai_service = get_ai_service()
    history_len = ai_service.get_conversation_length(telegram_id)

    await query.edit_message_text(
        f"AI Chat ended.\n\n"
        f"Your conversation history ({history_len} messages) has been preserved. "
        f"You can continue later or start a new chat.\n\n"
        f"See you next time!",
        reply_markup=ai_chat_exit_keyboard(),
    )

    logger.info("AI chat ended", telegram_id=telegram_id, history_preserved=history_len)

    return ConversationHandler.END


async def cancel_ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Cancel the AI chat conversation (via /cancel command).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish the conversation.
    """
    context.user_data.pop(AI_CHAT_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "AI Chat cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "AI Chat cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# AI Chat ConversationHandler
ai_chat_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_ai_chat, pattern="^menu_ask_ai$"),
    ],
    states={
        AI_CHATTING: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message),
            CallbackQueryHandler(handle_clear_history, pattern="^ai_clear_history$"),
            CallbackQueryHandler(handle_end_chat, pattern="^ai_end_chat$"),
        ],
        AI_ACTION_CONFIRM: [
            CallbackQueryHandler(handle_ai_action_confirm, pattern="^ai_action_confirm$"),
            CallbackQueryHandler(handle_ai_action_cancel, pattern="^ai_action_cancel$"),
            # Also handle if user sends a message while waiting for confirmation
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_ai_chat),
        CallbackQueryHandler(cancel_ai_chat, pattern="^cancel$"),
        CallbackQueryHandler(cancel_ai_chat, pattern="^menu_main$"),
    ],
    per_message=False,
)
