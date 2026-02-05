"""
AI Chat handlers for the Telegram Trade Journal Bot.

This module provides:
- AI conversation mode with persistent history
- Trade data context for AI responses
- Rate limiting and conversation management
"""

from typing import Optional

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
from handlers.accounts import get_user_by_telegram_id
from services.ai_service import get_ai_service
from services.analytics_service import get_analytics_service
from utils.keyboards import back_to_menu_keyboard

logger = get_logger(__name__)

# Conversation states
AI_CHATTING = 0

# Context keys
AI_CHAT_KEY = "ai_chat_active"

# Maximum message length for Telegram
MAX_MESSAGE_LENGTH = 4096


def ai_chat_keyboard() -> InlineKeyboardMarkup:
    """
    Create keyboard for AI chat mode with minimal control options.

    Users can exit AI chat via /start or menu navigation.

    Returns:
        InlineKeyboardMarkup: AI chat control keyboard with Back to Menu only.
    """
    keyboard = [
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

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (AI_CHATTING).
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

    # Split long responses
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
    },
    fallbacks=[
        CommandHandler("cancel", cancel_ai_chat),
        CallbackQueryHandler(cancel_ai_chat, pattern="^cancel$"),
        CallbackQueryHandler(cancel_ai_chat, pattern="^menu_main$"),
    ],
    per_message=False,
)
