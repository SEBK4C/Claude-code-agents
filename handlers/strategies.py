"""
Strategy management handlers for the Telegram Trade Journal Bot.

This module provides:
- Strategy list view with trade counts and win rates
- Strategy creation wizard
- AI-assisted strategy builder
- Strategy editing and deletion
- View trades by strategy
"""

import json
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
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
from database.models import Account, Strategy, Trade, TradeStatus
from handlers.accounts import get_user_by_telegram_id
from services.ai_service import get_ai_service
from utils.constants import (
    CB_STRATEGIES, CB_STRATEGY_DETAIL, CB_CREATE_STRATEGY,
    CB_DELETE_STRATEGY, CB_MAIN_MENU, CB_BACK,
    STATE_STRATEGY_SECTION_A, STATE_STRATEGY_SECTION_B,
    STATE_STRATEGY_SECTION_C, STATE_STRATEGY_SECTION_D,
    STATE_STRATEGY_FOLLOWUP, STATE_STRATEGY_CONFIRM,
    STATE_STRATEGY_NAME
)
from utils.helpers import format_percentage
from utils.keyboards import back_cancel_keyboard, back_to_menu_keyboard, confirmation_keyboard

logger = get_logger(__name__)

# Strategy questions for the new AI-assisted strategy builder (ABCD flow with 16 questions)
STRATEGY_QUESTIONS = {
    "A": {
        "title": "A. MARKET CONDITIONS",
        "questions": [
            "1. What market structure do you trade? (Trending, Ranging, Breakout, or All)",
            "2. What is your primary timeframe for analysis? (e.g., 1M, 5M, 15M, 1H, 4H, Daily)",
            "3. Do you trade specific sessions? (London, New York, Asia, or Any)",
            "4. Any specific market conditions you avoid? (e.g., news events, low volume)"
        ]
    },
    "B": {
        "title": "B. ENTRY RULES",
        "questions": [
            "5. What confirms your entry? (Price action, Indicators, or Both - specify which)",
            "6. Do you need multiple confirmations or just one trigger?",
            "7. Where do you enter relative to structure? (Break, Retest, Anticipation)",
            "8. Minimum R:R ratio before you take a trade?"
        ]
    },
    "C": {
        "title": "C. EXIT RULES",
        "questions": [
            "9. How do you set your Stop Loss? (ATR-based, Structure-based, Fixed pips, or other)",
            "10. How do you set your Take Profit? (R:R multiple, Structure target, Trail, or other)",
            "11. Do you use partial exits? If yes, at what levels?",
            "12. When do you move SL to breakeven?"
        ]
    },
    "D": {
        "title": "D. RISK MANAGEMENT",
        "questions": [
            "13. Maximum risk per trade? (% of account)",
            "14. Maximum trades per day?",
            "15. Maximum drawdown before you stop trading for the day/week?",
            "16. Any other rules? (e.g., no trading on Fridays, only 2 losses then stop)"
        ]
    }
}

# Conversation states for manual strategy creation
STRATEGY_NAME = 0
STRATEGY_DESCRIPTION = 1
STRATEGY_RULES = 2
STRATEGY_CONFIRM = 3

# Conversation states for AI strategy builder (ABCD flow)
AI_MARKET_CONDITIONS = 10  # A
AI_ENTRY_TRIGGERS = 11  # B
AI_RISK_MANAGEMENT = 12  # C
AI_EXIT_STRATEGY = 13  # D
AI_REVIEW = 14

# Conversation states for editing
EDIT_STRATEGY_NAME = 20
EDIT_STRATEGY_DESCRIPTION = 21
EDIT_STRATEGY_RULES = 22

# Wizard data keys
STRATEGY_WIZARD_KEY = "strategy_wizard"
AI_STRATEGY_WIZARD_KEY = "ai_strategy_wizard"
EDIT_STRATEGY_KEY = "edit_strategy"

# Validation constants
MIN_STRATEGY_NAME_LENGTH = 3
MAX_STRATEGY_NAME_LENGTH = 100
MAX_STRATEGIES_PER_USER = 10


def strategy_list_keyboard(
    strategies: list[tuple[int, str, int, Optional[Decimal]]],
    include_create: bool = True,
) -> InlineKeyboardMarkup:
    """
    Create keyboard for strategy list view.

    Args:
        strategies: List of (strategy_id, name, trade_count, win_rate) tuples.
        include_create: Whether to include create buttons.

    Returns:
        InlineKeyboardMarkup: Strategy list keyboard.
    """
    keyboard = []

    for strategy_id, name, count, win_rate in strategies:
        win_rate_str = f"{win_rate:.1f}%" if win_rate is not None else "N/A"
        label = f"{name} ({count} trades, {win_rate_str} WR)"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"strategy_view_{strategy_id}"),
        ])

    if include_create:
        keyboard.append([
            InlineKeyboardButton("+ Create Strategy", callback_data="strategy_create"),
        ])
        keyboard.append([
            InlineKeyboardButton(
                "AI Strategy Builder", callback_data="strategy_ai_builder"
            ),
        ])
        keyboard.append([
            InlineKeyboardButton(
                "AI Strategy Builder (New)", callback_data="strategy_ai_create"
            ),
        ])

    keyboard.append([
        InlineKeyboardButton("Back to Menu", callback_data="menu_home"),
    ])

    return InlineKeyboardMarkup(keyboard)


def strategy_detail_keyboard(strategy_id: int) -> InlineKeyboardMarkup:
    """
    Create keyboard for strategy detail view.

    Args:
        strategy_id: The strategy ID.

    Returns:
        InlineKeyboardMarkup: Strategy detail keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Edit Name", callback_data=f"strategy_edit_name_{strategy_id}"),
            InlineKeyboardButton("Edit Description", callback_data=f"strategy_edit_desc_{strategy_id}"),
        ],
        [
            InlineKeyboardButton("Edit Rules", callback_data=f"strategy_edit_rules_{strategy_id}"),
        ],
        [
            InlineKeyboardButton("Delete Strategy", callback_data=f"strategy_delete_{strategy_id}"),
        ],
        [
            InlineKeyboardButton("Back to Strategies", callback_data="menu_strategies"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def strategy_wizard_keyboard(include_skip: bool = False) -> InlineKeyboardMarkup:
    """
    Create navigation keyboard for strategy wizard.

    Args:
        include_skip: Whether to include a Skip button.

    Returns:
        InlineKeyboardMarkup: Navigation keyboard.
    """
    buttons = []
    if include_skip:
        buttons.append(InlineKeyboardButton("Skip", callback_data="sw_skip"))

    keyboard = [[*buttons]] if buttons else []
    keyboard.append([
        InlineKeyboardButton("Back", callback_data="sw_back"),
        InlineKeyboardButton("Cancel", callback_data="sw_cancel"),
    ])

    return InlineKeyboardMarkup(keyboard)


async def get_strategies_with_stats(
    user_id: int,
) -> list[tuple[int, str, int, Optional[Decimal]]]:
    """
    Get all strategies for a user with trade counts and win rates.

    Args:
        user_id: The internal user ID.

    Returns:
        list: List of (strategy_id, name, trade_count, win_rate) tuples.
    """
    async with get_session() as session:
        # Get strategies with trade counts
        result = await session.execute(
            select(
                Strategy.id,
                Strategy.name,
                func.count(Trade.id).label("trade_count"),
            )
            .outerjoin(Trade, Strategy.id == Trade.strategy_id)
            .where(Strategy.user_id == user_id)
            .group_by(Strategy.id, Strategy.name)
            .order_by(Strategy.name)
        )

        strategies = []
        for row in result.fetchall():
            strategy_id = row[0]
            name = row[1]
            trade_count = row[2] or 0

            # Calculate win rate for this strategy
            win_rate = None
            if trade_count > 0:
                closed_result = await session.execute(
                    select(func.count(Trade.id))
                    .where(Trade.strategy_id == strategy_id)
                    .where(Trade.status == TradeStatus.CLOSED)
                )
                closed_count = closed_result.scalar() or 0

                if closed_count > 0:
                    wins_result = await session.execute(
                        select(func.count(Trade.id))
                        .where(Trade.strategy_id == strategy_id)
                        .where(Trade.status == TradeStatus.CLOSED)
                        .where(Trade.pnl > 0)
                    )
                    wins = wins_result.scalar() or 0
                    win_rate = Decimal(str((wins / closed_count) * 100))

            strategies.append((strategy_id, name, trade_count, win_rate))

        return strategies


async def get_user_strategy_count(user_id: int) -> int:
    """
    Get the number of strategies for a user.

    Args:
        user_id: The internal user ID.

    Returns:
        int: Strategy count.
    """
    async with get_session() as session:
        result = await session.execute(
            select(func.count(Strategy.id)).where(Strategy.user_id == user_id)
        )
        return result.scalar() or 0


def format_rules_display(rules: Optional[dict[str, Any]]) -> str:
    """
    Format strategy rules for display.

    Args:
        rules: The rules dictionary.

    Returns:
        str: Formatted rules string.
    """
    if not rules:
        return "No rules defined"

    lines = []

    # Market conditions
    if "market_conditions" in rules:
        conditions = rules["market_conditions"]
        if isinstance(conditions, list):
            lines.append("Market Conditions:")
            for cond in conditions[:5]:
                lines.append(f"  - {cond}")
        elif isinstance(conditions, str):
            lines.append(f"Market Conditions: {conditions}")

    # Entry triggers
    if "entry_triggers" in rules:
        triggers = rules["entry_triggers"]
        if isinstance(triggers, list):
            lines.append("Entry Triggers:")
            for trig in triggers[:5]:
                lines.append(f"  - {trig}")
        elif isinstance(triggers, str):
            lines.append(f"Entry Triggers: {triggers}")

    # Risk management
    if "risk_management" in rules:
        rm = rules["risk_management"]
        if isinstance(rm, dict):
            lines.append("Risk Management:")
            for key, value in list(rm.items())[:5]:
                lines.append(f"  - {key}: {value}")
        elif isinstance(rm, str):
            lines.append(f"Risk Management: {rm}")

    # Exit strategy
    if "exit_strategy" in rules:
        exit_s = rules["exit_strategy"]
        if isinstance(exit_s, dict):
            lines.append("Exit Strategy:")
            for key, value in list(exit_s.items())[:5]:
                lines.append(f"  - {key}: {value}")
        elif isinstance(exit_s, str):
            lines.append(f"Exit Strategy: {exit_s}")

    # Raw output (from AI)
    if "raw_output" in rules and not lines:
        raw = rules["raw_output"]
        lines.append(raw[:500])
        if len(raw) > 500:
            lines.append("...")

    if not lines:
        # Generic formatting for unknown structure
        for key, value in list(rules.items())[:10]:
            if isinstance(value, (dict, list)):
                lines.append(f"{key}: {json.dumps(value, indent=2)[:200]}")
            else:
                lines.append(f"{key}: {value}")

    return "\n".join(lines) if lines else "No rules defined"


# ============================================================================
# STRATEGY LIST AND DETAIL
# ============================================================================


async def handle_strategies_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the strategies menu callback - show list of all strategies.

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

            user_id = user.id

        strategies = await get_strategies_with_stats(user_id)
        strategy_count = len(strategies)

        if not strategies:
            message = (
                "You haven't created any trading strategies yet.\n\n"
                "Strategies help you track which approach works best.\n\n"
                "You can create strategies manually or use the AI Strategy Builder "
                "to help you define a structured strategy."
            )
        else:
            message = f"Your Strategies ({strategy_count}/{MAX_STRATEGIES_PER_USER}):\n\n"
            message += "WR = Win Rate\n\n"
            message += "Select a strategy to view details:"

        can_create = strategy_count < MAX_STRATEGIES_PER_USER
        await query.edit_message_text(
            text=message,
            reply_markup=strategy_list_keyboard(strategies, include_create=can_create),
        )

    except Exception as e:
        logger.error("Error loading strategies", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_strategy_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle viewing a strategy's details.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    strategy_id_str = query.data.replace("strategy_view_", "")
    try:
        strategy_id = int(strategy_id_str)
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

            # Get strategy
            strategy_result = await session.execute(
                select(Strategy)
                .where(Strategy.id == strategy_id)
                .where(Strategy.user_id == user.id)
            )
            strategy = strategy_result.scalar_one_or_none()

            if not strategy:
                await query.edit_message_text(
                    "Strategy not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            # Get trade stats
            trade_count_result = await session.execute(
                select(func.count(Trade.id)).where(Trade.strategy_id == strategy_id)
            )
            total_trades = trade_count_result.scalar() or 0

            closed_count_result = await session.execute(
                select(func.count(Trade.id))
                .where(Trade.strategy_id == strategy_id)
                .where(Trade.status == TradeStatus.CLOSED)
            )
            closed_trades = closed_count_result.scalar() or 0

            wins_result = await session.execute(
                select(func.count(Trade.id))
                .where(Trade.strategy_id == strategy_id)
                .where(Trade.status == TradeStatus.CLOSED)
                .where(Trade.pnl > 0)
            )
            wins = wins_result.scalar() or 0

            total_pnl_result = await session.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.strategy_id == strategy_id)
                .where(Trade.status == TradeStatus.CLOSED)
            )
            total_pnl = total_pnl_result.scalar() or Decimal("0")

            # Build message
            lines = [
                f"Strategy: {strategy.name}",
                "=" * 30,
                "",
            ]

            if strategy.description:
                lines.append(f"Description: {strategy.description}")
                lines.append("")

            lines.append("Performance:")
            lines.append(f"  Total Trades: {total_trades}")
            lines.append(f"  Closed Trades: {closed_trades}")

            if closed_trades > 0:
                win_rate = (wins / closed_trades) * 100
                lines.append(f"  Win Rate: {win_rate:.1f}%")
                lines.append(f"  Total P&L: {total_pnl:+.2f}")
            else:
                lines.append("  Win Rate: N/A")
                lines.append("  Total P&L: N/A")

            lines.append("")
            lines.append("Rules:")
            lines.append(format_rules_display(strategy.rules))

            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=strategy_detail_keyboard(strategy_id),
            )

    except Exception as e:
        logger.error("Error viewing strategy", error=str(e), strategy_id=strategy_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# MANUAL STRATEGY CREATION
# ============================================================================


async def start_create_strategy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the manual strategy creation wizard.

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
                    "Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            user_id = user.id

        # Check strategy limit
        strategy_count = await get_user_strategy_count(user_id)
        if strategy_count >= MAX_STRATEGIES_PER_USER:
            await query.edit_message_text(
                f"You've reached the maximum of {MAX_STRATEGIES_PER_USER} strategies.\n\n"
                "Please delete an existing strategy before creating a new one.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

        context.user_data[STRATEGY_WIZARD_KEY] = {"user_id": user_id}

        await query.edit_message_text(
            "Create a new trading strategy\n\n"
            f"Step 1/3: Enter the strategy name ({MIN_STRATEGY_NAME_LENGTH}-{MAX_STRATEGY_NAME_LENGTH} characters):",
            reply_markup=strategy_wizard_keyboard(),
        )

        return STRATEGY_NAME

    except Exception as e:
        logger.error("Error starting strategy creation", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_strategy_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle strategy name input.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return STRATEGY_NAME

    name_input = update.message.text.strip()

    if len(name_input) < MIN_STRATEGY_NAME_LENGTH:
        await update.message.reply_text(
            f"Strategy name must be at least {MIN_STRATEGY_NAME_LENGTH} characters.\n\n"
            "Please enter a valid name:",
            reply_markup=strategy_wizard_keyboard(),
        )
        return STRATEGY_NAME

    if len(name_input) > MAX_STRATEGY_NAME_LENGTH:
        await update.message.reply_text(
            f"Strategy name must be at most {MAX_STRATEGY_NAME_LENGTH} characters.\n\n"
            "Please enter a shorter name:",
            reply_markup=strategy_wizard_keyboard(),
        )
        return STRATEGY_NAME

    wizard_data = context.user_data.get(STRATEGY_WIZARD_KEY, {})
    wizard_data["name"] = name_input

    await update.message.reply_text(
        "Step 2/3: Enter a description for your strategy:\n\n"
        "This should explain when and how to use this strategy.\n\n"
        "Press Skip to continue without a description.",
        reply_markup=strategy_wizard_keyboard(include_skip=True),
    )

    return STRATEGY_DESCRIPTION


async def handle_strategy_description(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle strategy description input.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return STRATEGY_DESCRIPTION

    description = update.message.text.strip()

    wizard_data = context.user_data.get(STRATEGY_WIZARD_KEY, {})
    wizard_data["description"] = description

    await update.message.reply_text(
        "Step 3/3: Enter the strategy rules as JSON:\n\n"
        "Example:\n"
        '{"entry": "RSI < 30", "exit": "RSI > 70", "stop_loss": "2%"}\n\n'
        "Press Skip to create without rules.",
        reply_markup=strategy_wizard_keyboard(include_skip=True),
    )

    return STRATEGY_RULES


async def handle_strategy_description_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping strategy description.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return STRATEGY_DESCRIPTION

    await query.answer()

    wizard_data = context.user_data.get(STRATEGY_WIZARD_KEY, {})
    wizard_data["description"] = None

    await query.edit_message_text(
        "Step 3/3: Enter the strategy rules as JSON:\n\n"
        "Example:\n"
        '{"entry": "RSI < 30", "exit": "RSI > 70", "stop_loss": "2%"}\n\n'
        "Press Skip to create without rules.",
        reply_markup=strategy_wizard_keyboard(include_skip=True),
    )

    return STRATEGY_RULES


async def handle_strategy_rules(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle strategy rules input.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return STRATEGY_RULES

    rules_input = update.message.text.strip()

    try:
        rules = json.loads(rules_input)
    except json.JSONDecodeError:
        await update.message.reply_text(
            "Invalid JSON format. Please enter valid JSON or press Skip.",
            reply_markup=strategy_wizard_keyboard(include_skip=True),
        )
        return STRATEGY_RULES

    wizard_data = context.user_data.get(STRATEGY_WIZARD_KEY, {})
    wizard_data["rules"] = rules

    return await _create_strategy(update, context, wizard_data)


async def handle_strategy_rules_skip(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle skipping strategy rules.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query:
        return STRATEGY_RULES

    await query.answer()

    wizard_data = context.user_data.get(STRATEGY_WIZARD_KEY, {})
    wizard_data["rules"] = None

    return await _create_strategy_callback(query, context, wizard_data)


async def _create_strategy(
    update: Update, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict
) -> int:
    """Create strategy from message handler."""
    try:
        async with get_session() as session:
            strategy = Strategy(
                user_id=wizard_data["user_id"],
                name=wizard_data["name"],
                description=wizard_data.get("description"),
                rules=wizard_data.get("rules"),
            )
            session.add(strategy)
            await session.flush()

            logger.info(
                "Strategy created",
                strategy_id=strategy.id,
                name=strategy.name,
                user_id=wizard_data["user_id"],
            )

            await update.message.reply_text(
                f"Strategy '{strategy.name}' created successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error creating strategy", error=str(e))
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(STRATEGY_WIZARD_KEY, None)
    return ConversationHandler.END


async def _create_strategy_callback(
    query, context: ContextTypes.DEFAULT_TYPE, wizard_data: dict
) -> int:
    """Create strategy from callback handler."""
    try:
        async with get_session() as session:
            strategy = Strategy(
                user_id=wizard_data["user_id"],
                name=wizard_data["name"],
                description=wizard_data.get("description"),
                rules=wizard_data.get("rules"),
            )
            session.add(strategy)
            await session.flush()

            logger.info(
                "Strategy created",
                strategy_id=strategy.id,
                name=strategy.name,
                user_id=wizard_data["user_id"],
            )

            await query.edit_message_text(
                f"Strategy '{strategy.name}' created successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error creating strategy", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(STRATEGY_WIZARD_KEY, None)
    return ConversationHandler.END


async def cancel_strategy_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the strategy creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(STRATEGY_WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Strategy creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "Strategy creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Manual strategy creation ConversationHandler
strategy_create_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_create_strategy, pattern="^strategy_create$"),
    ],
    states={
        STRATEGY_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_strategy_name),
        ],
        STRATEGY_DESCRIPTION: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_strategy_description),
            CallbackQueryHandler(handle_strategy_description_skip, pattern="^sw_skip$"),
        ],
        STRATEGY_RULES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_strategy_rules),
            CallbackQueryHandler(handle_strategy_rules_skip, pattern="^sw_skip$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_strategy_wizard),
        CallbackQueryHandler(cancel_strategy_wizard, pattern="^sw_cancel$"),
        CallbackQueryHandler(cancel_strategy_wizard, pattern="^sw_back$"),
        CallbackQueryHandler(cancel_strategy_wizard, pattern="^menu_strategies$"),
    ],
    per_message=False,
)


# ============================================================================
# AI-ASSISTED STRATEGY BUILDER (F18)
# ============================================================================


async def start_ai_strategy_builder(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the AI-assisted strategy builder (ABCD flow).

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

    # Check if AI service is configured
    ai_service = get_ai_service()
    if not ai_service.is_configured:
        await query.edit_message_text(
            "AI Strategy Builder is not available.\n\n"
            "The AI service is not configured. Please contact the administrator.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            user_id = user.id

        # Check strategy limit
        strategy_count = await get_user_strategy_count(user_id)
        if strategy_count >= MAX_STRATEGIES_PER_USER:
            await query.edit_message_text(
                f"You've reached the maximum of {MAX_STRATEGIES_PER_USER} strategies.\n\n"
                "Please delete an existing strategy before creating a new one.",
                reply_markup=back_to_menu_keyboard(),
            )
            return ConversationHandler.END

        context.user_data[AI_STRATEGY_WIZARD_KEY] = {"user_id": user_id}

        await query.edit_message_text(
            "AI Strategy Builder\n"
            "=" * 30 + "\n\n"
            "I'll help you build a structured trading strategy by asking about "
            "4 key components:\n\n"
            "A. Market Conditions\n"
            "B. Entry Triggers\n"
            "C. Risk Management\n"
            "D. Exit Strategy\n\n"
            "Let's start!\n\n"
            "A. Market Conditions\n"
            "Describe the market conditions when you want to use this strategy:\n"
            "(e.g., trending market, high volatility, specific time of day)",
            reply_markup=strategy_wizard_keyboard(),
        )

        return AI_MARKET_CONDITIONS

    except Exception as e:
        logger.error("Error starting AI strategy builder", error=str(e))
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END


async def handle_ai_market_conditions(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle market conditions input (Step A).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return AI_MARKET_CONDITIONS

    market_conditions = update.message.text.strip()

    wizard_data = context.user_data.get(AI_STRATEGY_WIZARD_KEY, {})
    wizard_data["market_conditions"] = market_conditions

    await update.message.reply_text(
        "B. Entry Triggers\n\n"
        "What signals or conditions trigger your entry?\n"
        "(e.g., RSI oversold, price breaks resistance, candlestick pattern)",
        reply_markup=strategy_wizard_keyboard(),
    )

    return AI_ENTRY_TRIGGERS


async def handle_ai_entry_triggers(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle entry triggers input (Step B).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return AI_ENTRY_TRIGGERS

    entry_triggers = update.message.text.strip()

    wizard_data = context.user_data.get(AI_STRATEGY_WIZARD_KEY, {})
    wizard_data["entry_triggers"] = entry_triggers

    await update.message.reply_text(
        "C. Risk Management\n\n"
        "How do you manage risk?\n"
        "(e.g., % risk per trade, stop-loss placement, position sizing method)",
        reply_markup=strategy_wizard_keyboard(),
    )

    return AI_RISK_MANAGEMENT


async def handle_ai_risk_management(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle risk management input (Step C).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return AI_RISK_MANAGEMENT

    risk_management = update.message.text.strip()

    wizard_data = context.user_data.get(AI_STRATEGY_WIZARD_KEY, {})
    wizard_data["risk_management"] = risk_management

    await update.message.reply_text(
        "D. Exit Strategy\n\n"
        "How do you exit trades?\n"
        "(e.g., take profit targets, trailing stop, time-based exit)",
        reply_markup=strategy_wizard_keyboard(),
    )

    return AI_EXIT_STRATEGY


async def handle_ai_exit_strategy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle exit strategy input (Step D) and generate strategy.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    if not update.message or not update.message.text:
        return AI_EXIT_STRATEGY

    exit_strategy = update.message.text.strip()

    wizard_data = context.user_data.get(AI_STRATEGY_WIZARD_KEY, {})
    wizard_data["exit_strategy"] = exit_strategy

    # Show processing message
    processing_msg = await update.message.reply_text(
        "Generating your strategy with AI... Please wait.",
    )

    try:
        # Generate strategy using AI
        ai_service = get_ai_service()
        strategy_dict, error = await ai_service.generate_strategy(
            market_conditions=wizard_data["market_conditions"],
            entry_triggers=wizard_data["entry_triggers"],
            risk_management=wizard_data["risk_management"],
            exit_strategy=wizard_data["exit_strategy"],
        )

        if error:
            await processing_msg.edit_text(
                f"AI generation failed: {error}\n\n"
                "Would you like to try again or cancel?",
                reply_markup=strategy_wizard_keyboard(),
            )
            return AI_EXIT_STRATEGY

        if not strategy_dict:
            await processing_msg.edit_text(
                "AI returned an empty response. Please try again.",
                reply_markup=strategy_wizard_keyboard(),
            )
            return AI_EXIT_STRATEGY

        # Store generated strategy
        wizard_data["generated_strategy"] = strategy_dict

        # Show preview
        name = strategy_dict.get("name", "AI Generated Strategy")
        description = strategy_dict.get("description", "")
        rules = strategy_dict.get("rules", {})

        preview_lines = [
            "AI Generated Strategy",
            "=" * 30,
            "",
            f"Name: {name}",
            "",
        ]

        if description:
            preview_lines.append(f"Description: {description[:200]}")
            if len(description) > 200:
                preview_lines.append("...")
            preview_lines.append("")

        preview_lines.append("Rules:")
        preview_lines.append(format_rules_display(rules))
        preview_lines.append("")
        preview_lines.append("Would you like to save this strategy?")

        await processing_msg.edit_text(
            "\n".join(preview_lines),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Save Strategy", callback_data="ai_save"),
                    InlineKeyboardButton("Regenerate", callback_data="ai_regenerate"),
                ],
                [
                    InlineKeyboardButton("Cancel", callback_data="ai_cancel"),
                ],
            ]),
        )

        return AI_REVIEW

    except Exception as e:
        logger.error("Error generating AI strategy", error=str(e))
        await processing_msg.edit_text(
            "An error occurred while generating the strategy. Please try again.",
            reply_markup=strategy_wizard_keyboard(),
        )
        return AI_EXIT_STRATEGY


async def handle_ai_review(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle AI strategy review (save, regenerate, or cancel).

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state.
    """
    query = update.callback_query
    if not query or not query.data:
        return AI_REVIEW

    await query.answer()

    wizard_data = context.user_data.get(AI_STRATEGY_WIZARD_KEY, {})

    if query.data == "ai_save":
        # Save the strategy
        generated = wizard_data.get("generated_strategy", {})

        try:
            async with get_session() as session:
                strategy = Strategy(
                    user_id=wizard_data["user_id"],
                    name=generated.get("name", "AI Generated Strategy"),
                    description=generated.get("description"),
                    rules=generated.get("rules"),
                )
                session.add(strategy)
                await session.flush()

                logger.info(
                    "AI Strategy saved",
                    strategy_id=strategy.id,
                    name=strategy.name,
                    user_id=wizard_data["user_id"],
                )

                await query.edit_message_text(
                    f"Strategy '{strategy.name}' saved successfully!",
                    reply_markup=back_to_menu_keyboard(),
                )

        except Exception as e:
            logger.error("Error saving AI strategy", error=str(e))
            await query.edit_message_text(
                "An error occurred while saving. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )

        context.user_data.pop(AI_STRATEGY_WIZARD_KEY, None)
        return ConversationHandler.END

    elif query.data == "ai_regenerate":
        # Go back to exit strategy to regenerate
        await query.edit_message_text(
            "D. Exit Strategy (Regenerate)\n\n"
            "How do you exit trades?\n"
            "(Modify your answer or keep it the same)",
            reply_markup=strategy_wizard_keyboard(),
        )
        return AI_EXIT_STRATEGY

    elif query.data == "ai_cancel":
        context.user_data.pop(AI_STRATEGY_WIZARD_KEY, None)
        await query.edit_message_text(
            "AI Strategy Builder cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    return AI_REVIEW


async def cancel_ai_strategy_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the AI strategy builder.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END.
    """
    context.user_data.pop(AI_STRATEGY_WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "AI Strategy Builder cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "AI Strategy Builder cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# AI Strategy Builder ConversationHandler
ai_strategy_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_ai_strategy_builder, pattern="^strategy_ai_builder$"),
    ],
    states={
        AI_MARKET_CONDITIONS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_market_conditions),
        ],
        AI_ENTRY_TRIGGERS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_entry_triggers),
        ],
        AI_RISK_MANAGEMENT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_risk_management),
        ],
        AI_EXIT_STRATEGY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_exit_strategy),
        ],
        AI_REVIEW: [
            CallbackQueryHandler(handle_ai_review, pattern="^ai_(save|regenerate|cancel)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_ai_strategy_wizard),
        CallbackQueryHandler(cancel_ai_strategy_wizard, pattern="^sw_cancel$"),
        CallbackQueryHandler(cancel_ai_strategy_wizard, pattern="^sw_back$"),
        CallbackQueryHandler(cancel_ai_strategy_wizard, pattern="^ai_cancel$"),
        CallbackQueryHandler(cancel_ai_strategy_wizard, pattern="^menu_strategies$"),
    ],
    per_message=False,
)


# ============================================================================
# STRATEGY EDITING
# ============================================================================


async def handle_strategy_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Start editing strategy name.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    strategy_id_str = query.data.replace("strategy_edit_name_", "")
    try:
        strategy_id = int(strategy_id_str)
    except ValueError:
        return

    context.user_data[EDIT_STRATEGY_KEY] = {
        "strategy_id": strategy_id,
        "field": "name",
    }

    await query.edit_message_text(
        "Enter the new strategy name:",
        reply_markup=back_cancel_keyboard(
            back_data=f"strategy_view_{strategy_id}",
            cancel_data="edit_strategy_cancel",
        ),
    )


async def handle_strategy_edit_desc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Start editing strategy description.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    strategy_id_str = query.data.replace("strategy_edit_desc_", "")
    try:
        strategy_id = int(strategy_id_str)
    except ValueError:
        return

    context.user_data[EDIT_STRATEGY_KEY] = {
        "strategy_id": strategy_id,
        "field": "description",
    }

    await query.edit_message_text(
        "Enter the new strategy description:\n\n"
        "Send 'clear' to remove the description.",
        reply_markup=back_cancel_keyboard(
            back_data=f"strategy_view_{strategy_id}",
            cancel_data="edit_strategy_cancel",
        ),
    )


async def handle_strategy_edit_rules(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Start editing strategy rules.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    strategy_id_str = query.data.replace("strategy_edit_rules_", "")
    try:
        strategy_id = int(strategy_id_str)
    except ValueError:
        return

    context.user_data[EDIT_STRATEGY_KEY] = {
        "strategy_id": strategy_id,
        "field": "rules",
    }

    await query.edit_message_text(
        "Enter the new strategy rules as JSON:\n\n"
        "Example:\n"
        '{"entry": "RSI < 30", "exit": "RSI > 70"}\n\n'
        "Send 'clear' to remove the rules.",
        reply_markup=back_cancel_keyboard(
            back_data=f"strategy_view_{strategy_id}",
            cancel_data="edit_strategy_cancel",
        ),
    )


async def handle_strategy_edit_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle strategy edit input.

    Raises ApplicationHandlerStop after handling to prevent other
    handler groups from processing the same message.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return

    edit_data = context.user_data.get(EDIT_STRATEGY_KEY)
    if not edit_data:
        # Not in strategy edit flow - let other handlers process this message
        return

    strategy_id = edit_data.get("strategy_id")
    field = edit_data.get("field")
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
                context.user_data.pop(EDIT_STRATEGY_KEY, None)
                return

            result = await session.execute(
                select(Strategy)
                .where(Strategy.id == strategy_id)
                .where(Strategy.user_id == user.id)
            )
            strategy = result.scalar_one_or_none()

            if not strategy:
                await update.message.reply_text(
                    "Strategy not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(EDIT_STRATEGY_KEY, None)
                return

            if field == "name":
                if len(input_text) < MIN_STRATEGY_NAME_LENGTH:
                    await update.message.reply_text(
                        f"Name must be at least {MIN_STRATEGY_NAME_LENGTH} characters.",
                    )
                    return
                if len(input_text) > MAX_STRATEGY_NAME_LENGTH:
                    await update.message.reply_text(
                        f"Name must be at most {MAX_STRATEGY_NAME_LENGTH} characters.",
                    )
                    return
                strategy.name = input_text

            elif field == "description":
                if input_text.lower() == "clear":
                    strategy.description = None
                else:
                    strategy.description = input_text

            elif field == "rules":
                if input_text.lower() == "clear":
                    strategy.rules = None
                else:
                    try:
                        rules = json.loads(input_text)
                        strategy.rules = rules
                    except json.JSONDecodeError:
                        await update.message.reply_text(
                            "Invalid JSON format. Please enter valid JSON or 'clear'.",
                        )
                        return

            await session.flush()

            logger.info(
                "Strategy updated",
                strategy_id=strategy_id,
                field=field,
                telegram_id=telegram_id,
            )

            await update.message.reply_text(
                "Strategy updated successfully!",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error updating strategy", error=str(e), strategy_id=strategy_id)
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(EDIT_STRATEGY_KEY, None)
    raise ApplicationHandlerStop  # Prevent other handler groups from firing


async def handle_strategy_edit_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Cancel strategy editing.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if query:
        await query.answer()

    context.user_data.pop(EDIT_STRATEGY_KEY, None)

    if query:
        await query.edit_message_text(
            "Edit cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# STRATEGY DELETION
# ============================================================================


async def handle_strategy_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle strategy deletion with confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    if query.data.startswith("strategy_delete_") and not query.data.startswith(
        "strategy_delete_confirm_"
    ):
        strategy_id_str = query.data.replace("strategy_delete_", "")
        try:
            strategy_id = int(strategy_id_str)
        except ValueError:
            return

        context.user_data["delete_strategy_id"] = strategy_id

        await query.edit_message_text(
            "Are you sure you want to delete this strategy?\n\n"
            "Trades using this strategy will show 'Deleted Strategy' instead.",
            reply_markup=confirmation_keyboard(
                confirm_text="Yes, Delete",
                cancel_text="No, Keep It",
                confirm_data=f"strategy_delete_confirm_{strategy_id}",
                cancel_data=f"strategy_view_{strategy_id}",
            ),
        )

    elif query.data.startswith("strategy_delete_confirm_"):
        strategy_id_str = query.data.replace("strategy_delete_confirm_", "")
        try:
            strategy_id = int(strategy_id_str)
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
                    select(Strategy)
                    .where(Strategy.id == strategy_id)
                    .where(Strategy.user_id == user.id)
                )
                strategy = result.scalar_one_or_none()

                if strategy:
                    strategy_name = strategy.name

                    # Note: We don't delete the strategy, just mark trades
                    # The strategy_id in trades will remain but strategy won't exist
                    await session.delete(strategy)
                    await session.flush()

                    logger.info(
                        "Strategy deleted",
                        strategy_id=strategy_id,
                        name=strategy_name,
                        telegram_id=telegram_id,
                    )

                    await query.edit_message_text(
                        f"Strategy '{strategy_name}' has been deleted.\n\n"
                        "Trades that used this strategy will show 'Deleted Strategy'.",
                        reply_markup=back_to_menu_keyboard(),
                    )
                else:
                    await query.edit_message_text(
                        "Strategy not found.",
                        reply_markup=back_to_menu_keyboard(),
                    )

        except Exception as e:
            logger.error("Error deleting strategy", error=str(e), strategy_id=strategy_id)
            await query.edit_message_text(
                "An error occurred. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )

        context.user_data.pop("delete_strategy_id", None)


# ============================================================================
# NEW AI STRATEGY BUILDER (16-question ABCD flow)
# ============================================================================


async def create_strategy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start AI-assisted strategy creation - Section A."""
    query = update.callback_query
    await query.answer()

    # Initialize strategy builder state
    context.user_data["strategy_builder"] = {
        "answers": {},
        "current_section": "A",
        "ai_summary": None,
        "parsed_rules": None
    }
    context.user_data["state"] = STATE_STRATEGY_SECTION_A

    # Get user's trade data for AI context
    from services.analytics_service import AnalyticsService
    from handlers.accounts import get_user_by_telegram_id

    telegram_id = update.effective_user.id
    user_id = None

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if user:
                user_id = user.id
    except Exception as e:
        logger.error("Error getting user for strategy builder", error=str(e))

    trade_data = await AnalyticsService.get_all_data_for_ai(user_id)

    # AI generates personalized intro based on trading history
    ai_service = get_ai_service()
    intro = await ai_service.generate_strategy_intro(trade_data)

    section = STRATEGY_QUESTIONS["A"]
    questions_text = "\n".join(section["questions"])

    text = f"""*Strategy Builder*

{intro}

Let's build your strategy step by step. Answer each section naturally - write as much or as little as you want.

---

*{section['title']}*

{questions_text}

---

Type your answers below. You can answer all at once or refer to question numbers.

Or type "skip" to use defaults for this section."""

    buttons = [
        [InlineKeyboardButton("Skip Section", callback_data="strategy_skip_section")],
        [InlineKeyboardButton("Cancel", callback_data=CB_STRATEGIES)]
    ]

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def handle_strategy_section_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's response to strategy questions."""
    message = update.message.text
    builder = context.user_data.get("strategy_builder", {})
    current_section = builder.get("current_section", "A")

    # Store answer
    builder["answers"][current_section] = message

    # Determine next section
    section_order = ["A", "B", "C", "D"]
    current_index = section_order.index(current_section)

    if current_index < len(section_order) - 1:
        # Move to next section
        next_section = section_order[current_index + 1]
        builder["current_section"] = next_section
        context.user_data["strategy_builder"] = builder

        # Update state
        state_map = {
            "B": STATE_STRATEGY_SECTION_B,
            "C": STATE_STRATEGY_SECTION_C,
            "D": STATE_STRATEGY_SECTION_D
        }
        context.user_data["state"] = state_map[next_section]

        # Send next section questions
        section = STRATEGY_QUESTIONS[next_section]
        questions_text = "\n".join(section["questions"])

        text = f"""Got it!

---

*{section['title']}*

{questions_text}

---

Type your answers, or "skip" for defaults."""

        buttons = [
            [InlineKeyboardButton("Skip Section", callback_data="strategy_skip_section")],
            [InlineKeyboardButton("Cancel", callback_data=CB_STRATEGIES)]
        ]

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    else:
        # All sections complete - process with AI
        context.user_data["state"] = STATE_STRATEGY_CONFIRM

        await update.message.reply_text("Processing your answers...")

        # Get user's trade data for AI context
        from services.analytics_service import AnalyticsService
        from handlers.accounts import get_user_by_telegram_id

        telegram_id = update.effective_user.id
        user_id = None

        try:
            async with get_session() as session:
                user = await get_user_by_telegram_id(session, telegram_id)
                if user:
                    user_id = user.id
        except Exception as e:
            logger.error("Error getting user for strategy processing", error=str(e))

        trade_data = await AnalyticsService.get_all_data_for_ai(user_id)

        # AI processes all answers and generates strategy
        ai_service = get_ai_service()
        result = await ai_service.build_strategy_from_answers(builder["answers"], trade_data)

        if result.get("error"):
            await update.message.reply_text(
                f"Error building strategy: {result['error']}\n\nTry again.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Start Over", callback_data="strategy_ai_create")],
                    [InlineKeyboardButton("Back", callback_data=CB_STRATEGIES)]
                ])
            )
            return

        # Store parsed result
        builder["parsed_rules"] = result["rules"]
        builder["ai_summary"] = result["summary"]
        builder["ai_feedback"] = result.get("feedback", "")
        context.user_data["strategy_builder"] = builder

        # Show strategy summary for confirmation
        text = f"""*Strategy Summary*

{result['summary']}

---

*Generated Rules:*

"""

        if result["rules"].get("market_conditions"):
            text += "*Market Conditions:*\n"
            for item in result["rules"]["market_conditions"]:
                text += f"- {item}\n"
            text += "\n"

        if result["rules"].get("entry_rules"):
            text += "*Entry Rules:*\n"
            for item in result["rules"]["entry_rules"]:
                text += f"- {item}\n"
            text += "\n"

        if result["rules"].get("exit_rules"):
            text += "*Exit Rules:*\n"
            for item in result["rules"]["exit_rules"]:
                text += f"- {item}\n"
            text += "\n"

        if result["rules"].get("risk_management"):
            text += "*Risk Management:*\n"
            for item in result["rules"]["risk_management"]:
                text += f"- {item}\n"

        if result.get("feedback"):
            text += f"\n---\n\n*AI Feedback:*\n{result['feedback']}"

        text += "\n\n---\n\nLooks good? Give your strategy a name to save it."

        context.user_data["state"] = STATE_STRATEGY_NAME

        buttons = [
            [InlineKeyboardButton("Start Over", callback_data="strategy_ai_create")],
            [InlineKeyboardButton("Cancel", callback_data=CB_STRATEGIES)]
        ]

        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def skip_section_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle skip section button."""
    query = update.callback_query
    await query.answer()

    builder = context.user_data.get("strategy_builder", {})
    current_section = builder.get("current_section", "A")

    # Store empty/default for skipped section
    builder["answers"][current_section] = "[SKIPPED - USE DEFAULTS]"

    # Move to next section
    section_order = ["A", "B", "C", "D"]
    current_index = section_order.index(current_section)

    if current_index < len(section_order) - 1:
        next_section = section_order[current_index + 1]
        builder["current_section"] = next_section
        context.user_data["strategy_builder"] = builder

        state_map = {
            "B": STATE_STRATEGY_SECTION_B,
            "C": STATE_STRATEGY_SECTION_C,
            "D": STATE_STRATEGY_SECTION_D
        }
        context.user_data["state"] = state_map[next_section]

        section = STRATEGY_QUESTIONS[next_section]
        questions_text = "\n".join(section["questions"])

        text = f"""Skipped. Using defaults for Section {current_section}.

---

*{section['title']}*

{questions_text}

---

Type your answers, or "skip" for defaults."""

        buttons = [
            [InlineKeyboardButton("Skip Section", callback_data="strategy_skip_section")],
            [InlineKeyboardButton("Cancel", callback_data=CB_STRATEGIES)]
        ]

        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        # All sections done, process with AI
        context.user_data["state"] = STATE_STRATEGY_CONFIRM
        context.user_data["strategy_builder"] = builder

        await query.edit_message_text("Processing your answers...")

        from services.analytics_service import AnalyticsService
        from handlers.accounts import get_user_by_telegram_id

        telegram_id = update.effective_user.id
        user_id = None

        try:
            async with get_session() as session:
                user = await get_user_by_telegram_id(session, telegram_id)
                if user:
                    user_id = user.id
        except Exception as e:
            logger.error("Error getting user for strategy processing", error=str(e))

        trade_data = await AnalyticsService.get_all_data_for_ai(user_id)
        ai_service = get_ai_service()
        result = await ai_service.build_strategy_from_answers(builder["answers"], trade_data)

        if result.get("error"):
            await query.message.reply_text(
                f"Error: {result['error']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Start Over", callback_data="strategy_ai_create")],
                    [InlineKeyboardButton("Back", callback_data=CB_STRATEGIES)]
                ])
            )
            return

        builder["parsed_rules"] = result["rules"]
        builder["ai_summary"] = result["summary"]
        context.user_data["strategy_builder"] = builder
        context.user_data["state"] = STATE_STRATEGY_NAME

        # Format and show summary
        text = f"*Strategy Summary*\n\n{result['summary']}\n\n*Generated Rules:*\n\n"
        for key in ["market_conditions", "entry_rules", "exit_rules", "risk_management"]:
            if result["rules"].get(key):
                text += f"*{key.replace('_', ' ').title()}:*\n"
                for item in result["rules"][key]:
                    text += f"- {item}\n"
                text += "\n"
        text += "\nGive your strategy a name to save it:"

        await query.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Start Over", callback_data="strategy_ai_create")],
                [InlineKeyboardButton("Cancel", callback_data=CB_STRATEGIES)]
            ])
        )


async def handle_strategy_name_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save strategy with provided name."""
    from datetime import datetime

    name = update.message.text.strip()

    if len(name) < 2:
        await update.message.reply_text("Name too short. Enter at least 2 characters.")
        return

    if len(name) > 50:
        await update.message.reply_text("Name too long. Max 50 characters.")
        return

    builder = context.user_data.get("strategy_builder", {})

    if not builder.get("parsed_rules"):
        # Stale state - return silently
        return

    # Save to database
    from sqlalchemy import select

    user_id = None
    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "User not found. Please use /start first.",
                    reply_markup=back_to_menu_keyboard()
                )
                return
            user_id = user.id

            # Check for duplicate name
            existing = await session.execute(
                select(Strategy).where(Strategy.name == name, Strategy.user_id == user_id)
            )
            if existing.scalar_one_or_none():
                await update.message.reply_text(f"Strategy '{name}' already exists. Choose another name.")
                return

            strategy = Strategy(
                user_id=user_id,
                name=name,
                description=builder.get("ai_summary", ""),
                rules=builder["parsed_rules"],
            )
            session.add(strategy)
            await session.flush()
            strategy_id = strategy.id

        # Clear state
        context.user_data.pop("strategy_builder", None)
        context.user_data.pop("state", None)

        await update.message.reply_text(
            f"Strategy *{name}* saved!\n\nIt will appear when adding trades.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Strategy", callback_data=f"{CB_STRATEGY_DETAIL}{strategy_id}")],
                [InlineKeyboardButton("Main Menu", callback_data=CB_MAIN_MENU)]
            ])
        )

    except Exception as e:
        logger.error("Error saving strategy", error=str(e), telegram_id=telegram_id)
        await update.message.reply_text(
            "An error occurred while saving. Please try again.",
            reply_markup=back_to_menu_keyboard()
        )


def get_strategy_builder_handlers():
    """Return handlers for new AI strategy builder."""
    return [
        CallbackQueryHandler(create_strategy_callback, pattern=r"^strategy_ai_create$"),
        CallbackQueryHandler(skip_section_callback, pattern=r"^strategy_skip_section$"),
    ]
