"""
Main entry point for the Telegram Trade Journal Bot.

This module initializes and runs the bot application with:
- Configuration loading and validation
- Database initialization
- Handler registration
- Error handling middleware
- Graceful shutdown handling

IMPORTANT: Handler Consolidation
================================
This bot uses a SINGLE text message handler that routes based on context.user_data state.
This prevents the multiple-response bug where python-telegram-bot dispatches to ONE handler
PER GROUP, causing multiple handlers to fire on a single message.

All text input flows (transactions, trade editing, strategy editing, natural input)
are routed through handle_unified_text_message which checks state keys in priority order.
"""

import asyncio
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import configure_logging, get_config, get_logger
from database.db import close_db, init_db
from utils.constants import (
    STATE_STRATEGY_SECTION_A, STATE_STRATEGY_SECTION_B,
    STATE_STRATEGY_SECTION_C, STATE_STRATEGY_SECTION_D,
    STATE_STRATEGY_NAME
)
from handlers import (
    # Start handlers
    start_command,
    help_command,
    handle_menu_home,
    handle_help_callback,
    # Account handlers
    account_create_conversation,
    handle_accounts_menu,
    handle_account_detail,
    handle_account_edit,
    handle_account_delete_confirm,
    handle_deposit_withdraw,
    handle_transaction_amount,
    # Trade handlers
    trade_entry_conversation,
    close_trade_conversation,
    handle_open_trades,
    handle_trade_history,
    handle_trade_detail,
    handle_trade_delete,
    handle_open_trades_filter,
    handle_edit_menu,
    handle_edit_sl,
    handle_edit_tp,
    handle_edit_notes,
    handle_edit_input,
    handle_edit_cancel,
    handle_edit_instrument,
    handle_edit_instrument_select,
    handle_edit_direction,
    handle_edit_direction_select,
    handle_edit_entry,
    handle_edit_lotsize,
    handle_edit_exit,
    handle_edit_screenshot,
    handle_edit_tags,
    handle_edit_tag_toggle,
    handle_edit_tags_clear,
    handle_edit_tags_save,
    handle_edit_strategy,
    handle_edit_strategy_select,
    handle_edit_strategy_clear,
    handle_screenshot_replace,
    handle_screenshot_remove,
    handle_screenshot_upload,
    register_price_alert_callback,
    # Tag handlers
    tag_create_conversation,
    handle_tags_menu,
    handle_tag_view,
    handle_tag_toggle_default,
    handle_tag_delete,
    # Strategy handlers
    strategy_create_conversation,
    ai_strategy_conversation,
    handle_strategies_menu,
    handle_strategy_view,
    handle_strategy_edit_name,
    handle_strategy_edit_desc,
    handle_strategy_edit_rules,
    handle_strategy_edit_input,
    handle_strategy_edit_cancel,
    handle_strategy_delete,
    # New AI Strategy Builder handlers
    create_strategy_callback,
    handle_strategy_section_response,
    skip_section_callback,
    handle_strategy_name_input,
    get_strategy_builder_handlers,
    # AI Chat handlers
    ai_chat_conversation,
    # Analytics handlers
    handle_analytics_menu,
    handle_analytics_overview,
    handle_analytics_performance,
    handle_analytics_risk,
    handle_analytics_patterns,
    handle_analytics_instruments,
    handle_analytics_filter,
    handle_analytics_range,
    handle_analytics_account,
    handle_analytics_charts,
    handle_chart_equity,
    handle_chart_pie,
    handle_chart_instruments,
    handle_chart_drawdown,
    handle_chart_dow,
    handle_chart_hour,
    handle_chart_download_all,
    # Export handlers
    export_conversation,
    # Reminder handlers
    handle_reminders_menu,
    handle_reminder_view,
    handle_reminder_toggle,
    handle_reminder_delete,
    handle_reminder_confirm_delete,
    reminder_add_conversation,
    # Natural input handlers
    handle_natural_trade_input,
    handle_missing_field_response,
    handle_natural_direction_callback,
    handle_natural_account_callback,
    handle_natural_close_select_callback,
    handle_natural_confirm_callback,
    handle_natural_cancel_callback,
    NATURAL_TRADE_KEY,
    NATURAL_TRADE_STATE_KEY,
)

# Import state keys from handler modules for unified routing
from handlers.accounts import TRANSACTION_KEY
from handlers.trades import EDIT_WIZARD_KEY
from handlers.strategies import EDIT_STRATEGY_KEY

# Initialize logger after config is loaded
logger: Optional[object] = None


def ensure_directories() -> None:
    """
    Create required directories if they don't exist.

    Creates:
    - screenshots/ - for trade screenshots
    - exports/ - for CSV/data exports
    """
    directories = ["screenshots", "exports"]

    for directory in directories:
        dir_path = Path(directory)
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            if logger:
                logger.info(f"Created directory: {directory}")


def return_to_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Create a keyboard with just a "Return to Menu" button.

    Used for error messages to help users navigate back.

    Returns:
        InlineKeyboardMarkup: Single button keyboard.
    """
    keyboard = [
        [InlineKeyboardButton("Return to Menu", callback_data="menu_home")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global error handler for the bot application.

    SILENT ERROR HANDLER: Logs the full exception with traceback for debugging
    but does NOT send any message to the user. This prevents error messages
    from interfering with normal bot operation and avoids confusing users.

    Args:
        update: The update that caused the error (may be None).
        context: The callback context containing the error.
    """
    global logger

    error = context.error
    error_traceback = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )

    if logger:
        logger.error(
            "Unhandled exception in bot",
            error_type=type(error).__name__,
            error_message=str(error),
            traceback=error_traceback,
        )
    else:
        print(f"ERROR: {type(error).__name__}: {error}")
        print(error_traceback)

    # SILENT: Do not send any message to the user
    # This prevents error messages from interfering with normal operation
    # Users can use /start or /help if they need assistance


async def handle_unknown_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle unknown callback queries gracefully.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if query:
        await query.answer("This feature is not yet implemented.")


async def handle_unified_text_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Unified text message handler that routes based on context.user_data state.

    This is the SINGLE text message handler for the entire bot. It checks
    state keys in priority order and routes to the appropriate handler function.

    Priority order (checked first to last):
    1. Strategy builder states (STATE_STRATEGY_SECTION_*, STATE_STRATEGY_NAME)
    2. Natural trade state (NATURAL_TRADE_STATE_KEY) - for missing field responses
    3. Transaction wizard (TRANSACTION_KEY) - for deposit/withdraw amounts
    4. Trade edit wizard (EDIT_WIZARD_KEY) - for SL/TP/Notes/Entry/Exit editing
    5. Strategy edit (EDIT_STRATEGY_KEY) - for strategy name/desc/rules editing
    6. Natural trade parsing - try to parse as a trade
    7. Silent fallback - do nothing (no "I didn't understand" message)

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.text:
        return

    # Priority 1: Strategy builder states
    state = context.user_data.get("state")
    if state in (STATE_STRATEGY_SECTION_A, STATE_STRATEGY_SECTION_B,
                 STATE_STRATEGY_SECTION_C, STATE_STRATEGY_SECTION_D):
        await handle_strategy_section_response(update, context)
        return
    elif state == STATE_STRATEGY_NAME:
        await handle_strategy_name_input(update, context)
        return

    # Priority 2: Natural trade state (missing field responses)
    if NATURAL_TRADE_STATE_KEY in context.user_data:
        handled = await handle_missing_field_response(update, context)
        if handled:
            return

    # Priority 3: Transaction wizard (deposit/withdraw)
    if TRANSACTION_KEY in context.user_data:
        await handle_transaction_amount(update, context)
        return

    # Priority 4: Trade edit wizard (SL/TP/Notes/Entry/Lotsize/Exit/Instrument)
    if EDIT_WIZARD_KEY in context.user_data:
        await handle_edit_input(update, context)
        return

    # Priority 5: Strategy edit (name/description/rules)
    if EDIT_STRATEGY_KEY in context.user_data:
        await handle_strategy_edit_input(update, context)
        return

    # Priority 6: Try natural trade parsing
    handled = await handle_natural_trade_input(update, context)
    if handled:
        return

    # Priority 7: Silent fallback - do nothing
    # The user can use /start or /help if they need assistance


async def handle_unified_photo_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Unified photo message handler that routes based on context.user_data state.

    Currently only handles screenshot uploads during trade editing.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.photo:
        return

    # Check if in screenshot upload state
    edit_data = context.user_data.get(EDIT_WIZARD_KEY)
    if edit_data and edit_data.get("field") == "screenshot_upload":
        await handle_screenshot_upload(update, context)
        return

    # Silent fallback - ignore photos outside of screenshot upload flow


def register_handlers(application: Application) -> None:
    """
    Register all bot handlers with the application.

    HANDLER CONSOLIDATION:
    =====================
    This bot uses a SINGLE text message handler in the default group (0).
    Previously, multiple MessageHandlers in different groups caused the
    "multiple responses per message" bug because python-telegram-bot
    dispatches to ONE handler PER GROUP.

    Now all text routing is done inside handle_unified_text_message
    which checks context.user_data state keys in priority order.

    Handlers are registered in order of priority:
    1. ConversationHandlers (for wizards)
    2. Command handlers (/start, /help)
    3. Specific callback handlers
    4. SINGLE unified text/photo handlers (no groups)
    5. Fallback handlers

    Args:
        application: The telegram bot Application instance.
    """
    # ========================================================================
    # CONVERSATION HANDLERS (must be registered first for priority)
    # ========================================================================

    # Account creation wizard
    application.add_handler(account_create_conversation)

    # Trade entry wizard (12-step flow)
    application.add_handler(trade_entry_conversation)

    # Close trade wizard
    application.add_handler(close_trade_conversation)

    # Tag creation wizard
    application.add_handler(tag_create_conversation)

    # Strategy creation wizards
    application.add_handler(strategy_create_conversation)
    application.add_handler(ai_strategy_conversation)

    # AI Chat conversation
    application.add_handler(ai_chat_conversation)

    # Export wizard
    application.add_handler(export_conversation)

    # Reminder add wizard
    application.add_handler(reminder_add_conversation)

    # ========================================================================
    # COMMAND HANDLERS
    # ========================================================================

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # ========================================================================
    # MAIN MENU CALLBACK HANDLERS
    # ========================================================================

    # Home and Help
    application.add_handler(
        CallbackQueryHandler(handle_menu_home, pattern="^(menu_home|menu_main)$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_help_callback, pattern="^menu_help$")
    )

    # ========================================================================
    # ACCOUNT HANDLERS
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_accounts_menu, pattern="^menu_accounts$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_account_detail, pattern=r"^account_select_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_account_edit, pattern=r"^account_edit_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_account_delete_confirm,
            pattern=r"^account_delete_(\d+|confirm|cancel)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            handle_deposit_withdraw, pattern=r"^account_(deposit|withdraw)_\d+$"
        )
    )
    # Deposit/Withdraw menu from main menu
    application.add_handler(
        CallbackQueryHandler(handle_accounts_menu, pattern="^menu_transactions$")
    )

    # ========================================================================
    # TRADE HANDLERS
    # ========================================================================

    # Open trades menu
    application.add_handler(
        CallbackQueryHandler(handle_open_trades, pattern="^menu_open_trades$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_open_trades_filter, pattern=r"^open_trades_filter_")
    )

    # Trade history menu
    application.add_handler(
        CallbackQueryHandler(handle_trade_history, pattern="^menu_history$")
    )

    # Trade detail view
    application.add_handler(
        CallbackQueryHandler(handle_trade_detail, pattern=r"^trade_detail_\d+$")
    )

    # Trade deletion
    application.add_handler(
        CallbackQueryHandler(handle_trade_delete, pattern=r"^trade_delete_")
    )

    # Trade editing handlers
    application.add_handler(
        CallbackQueryHandler(handle_edit_menu, pattern=r"^trade_edit_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_sl, pattern=r"^trade_edit_sl_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_tp, pattern=r"^trade_edit_tp_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_notes, pattern=r"^trade_edit_notes_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_cancel, pattern="^edit_cancel$")
    )

    # Core field edit handlers (F2, F3, F4)
    application.add_handler(
        CallbackQueryHandler(handle_edit_instrument, pattern=r"^edit_field_instrument_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_instrument_select, pattern=r"^instrument_")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_direction, pattern=r"^edit_field_direction_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_direction_select, pattern=r"^direction_")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_entry, pattern=r"^edit_field_entry_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_lotsize, pattern=r"^edit_field_lotsize_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_exit, pattern=r"^edit_field_exit_\d+$")
    )

    # Advanced field edit handlers (F5, F6, F7)
    application.add_handler(
        CallbackQueryHandler(handle_edit_screenshot, pattern=r"^edit_field_screenshot_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_screenshot_replace, pattern=r"^screenshot_replace_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_screenshot_remove, pattern=r"^screenshot_remove_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_tags, pattern=r"^edit_field_tags_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_tag_toggle, pattern=r"^edit_tag_toggle_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_tags_clear, pattern=r"^edit_tags_clear_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_tags_save, pattern=r"^edit_tags_save_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_strategy, pattern=r"^edit_field_strategy_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_strategy_select, pattern=r"^edit_strategy_select_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_edit_strategy_clear, pattern=r"^edit_strategy_clear_\d+$")
    )

    # ========================================================================
    # TAG HANDLERS
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_tags_menu, pattern="^menu_tags$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_tag_view, pattern=r"^tag_view_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_tag_toggle_default, pattern=r"^tag_toggle_default_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_tag_delete, pattern=r"^tag_delete_")
    )

    # ========================================================================
    # STRATEGY HANDLERS
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_strategies_menu, pattern="^menu_strategies$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_view, pattern=r"^strategy_view_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_edit_name, pattern=r"^strategy_edit_name_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_edit_desc, pattern=r"^strategy_edit_desc_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_edit_rules, pattern=r"^strategy_edit_rules_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_edit_cancel, pattern="^edit_strategy_cancel$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_strategy_delete, pattern=r"^strategy_delete_")
    )

    # New AI Strategy Builder handlers
    application.add_handler(
        CallbackQueryHandler(create_strategy_callback, pattern=r"^strategy_ai_create$")
    )
    application.add_handler(
        CallbackQueryHandler(skip_section_callback, pattern=r"^strategy_skip_section$")
    )

    # ========================================================================
    # ANALYTICS HANDLERS
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_analytics_menu, pattern="^menu_analytics$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_overview, pattern="^analytics_overview$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_performance, pattern="^analytics_performance$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_risk, pattern="^analytics_risk$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_patterns, pattern="^analytics_patterns$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_instruments, pattern="^analytics_instruments$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_filter, pattern="^analytics_filter$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_range, pattern=r"^analytics_range_")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_account, pattern=r"^analytics_account_")
    )
    application.add_handler(
        CallbackQueryHandler(handle_analytics_charts, pattern="^analytics_charts$")
    )

    # Chart handlers
    application.add_handler(
        CallbackQueryHandler(handle_chart_equity, pattern="^chart_equity$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_pie, pattern="^chart_pie$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_instruments, pattern="^chart_instruments$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_drawdown, pattern="^chart_drawdown$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_dow, pattern="^chart_dow$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_hour, pattern="^chart_hour$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_chart_download_all, pattern="^chart_download_all$")
    )

    # ========================================================================
    # REMINDER HANDLERS
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_reminders_menu, pattern="^menu_reminders$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reminder_view, pattern=r"^reminder_view_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reminder_toggle, pattern=r"^reminder_toggle_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reminder_delete, pattern=r"^reminder_delete_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(handle_reminder_confirm_delete, pattern=r"^reminder_confirm_delete_\d+$")
    )

    # ========================================================================
    # NATURAL INPUT CALLBACK HANDLERS
    # ========================================================================

    # Natural input direction selection
    application.add_handler(
        CallbackQueryHandler(
            handle_natural_direction_callback, pattern=r"^natural_dir_(long|short)$"
        )
    )

    # Natural input account selection
    application.add_handler(
        CallbackQueryHandler(
            handle_natural_account_callback, pattern=r"^natural_acc_\d+$"
        )
    )

    # Natural input trade selection for closing
    application.add_handler(
        CallbackQueryHandler(
            handle_natural_close_select_callback, pattern=r"^natural_close_\d+$"
        )
    )

    # Natural input confirmation
    application.add_handler(
        CallbackQueryHandler(
            handle_natural_confirm_callback,
            pattern=r"^natural_(open|close)_confirm$"
        )
    )

    # Natural input cancel
    application.add_handler(
        CallbackQueryHandler(handle_natural_cancel_callback, pattern="^natural_cancel$")
    )

    # ========================================================================
    # UNIFIED MESSAGE HANDLERS (SINGLE handler per message type - NO groups)
    # ========================================================================
    # IMPORTANT: All text/photo routing is done inside these handlers.
    # They check context.user_data state keys and route accordingly.
    # This prevents multiple handlers from firing on the same message.

    # SINGLE text message handler - routes based on state
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_unified_text_message,
        )
    )

    # SINGLE photo message handler - routes based on state
    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_unified_photo_message,
        )
    )

    # ========================================================================
    # FALLBACK HANDLER (catches unhandled callbacks)
    # ========================================================================

    application.add_handler(
        CallbackQueryHandler(handle_unknown_callback, pattern=".*"),
        group=99,
    )

    # ========================================================================
    # ERROR HANDLER (SILENT - logs only, no user messages)
    # ========================================================================

    application.add_error_handler(error_handler)

    if logger:
        logger.info("All handlers registered (unified text/photo routing)")


async def on_startup(application: Application) -> None:
    """
    Startup hook called when the application starts.

    Initializes the database and ensures required directories exist.

    Args:
        application: The telegram bot Application instance.
    """
    global logger
    logger = get_logger(__name__)

    logger.info("Starting bot application...")

    ensure_directories()

    await init_db()
    logger.info("Database initialized")


async def on_shutdown(application: Application) -> None:
    """
    Shutdown hook called when the application stops.

    Closes database connections cleanly.

    Args:
        application: The telegram bot Application instance.
    """
    global logger

    if logger:
        logger.info("Shutting down bot application...")

    await close_db()

    if logger:
        logger.info("Database connections closed")


def main() -> None:
    """
    Main entry point for the bot application.

    Loads configuration, validates settings, builds the application,
    registers handlers, and starts polling for updates.

    IMPORTANT: drop_pending_updates=True prevents old messages from
    triggering handlers when the bot restarts.
    """
    global logger

    config = get_config()
    configure_logging(config.logging)
    logger = get_logger(__name__)

    errors = config.validate()
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        sys.exit(1)

    logger.info("Configuration loaded and validated")

    application = (
        Application.builder()
        .token(config.telegram.token)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    register_handlers(application)

    logger.info("Starting bot polling...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
