"""
Start command and main dashboard handlers for the Telegram Trade Journal Bot.

This module provides:
- /start command handler
- /help command handler
- Main dashboard display and navigation
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import ContextTypes

from config import get_logger
from database.db import get_session
from database.models import Account, Trade, TradeStatus, User
from utils.helpers import format_currency
from utils.keyboards import main_menu_keyboard

logger = get_logger(__name__)


WELCOME_MESSAGE = """
Welcome to the Trade Journal Bot!

I'll help you track your trades, analyze your performance, and become a better trader.

Here's what you can do:
- Add and manage trading accounts
- Log your trades with entry/exit prices
- Add screenshots and notes
- Track your P&L and performance
- Get AI-powered trade analysis
- Set reminders for journaling

Use the menu below to get started!
"""

HELP_MESSAGE = """
Trade Journal Bot Help

Commands:
/start - Start the bot and show main menu
/help - Show this help message

Main Features:

**Add Trade** - Log a new trade with entry price, lot size, and optional SL/TP

**Open Trades** - View and manage your currently open trades

**Accounts** - Create and manage your trading accounts

**Trade History** - Browse your closed trades

**Analytics** - View performance statistics and charts

**Ask AI** - Get AI-powered analysis of your trades

**Strategies** - Create and manage trading strategies

**Tags** - Organize trades with custom tags

**Deposit/Withdraw** - Add or remove funds from accounts

**Export** - Export your trade data to CSV

**Reminders** - Set daily journaling reminders

Need help? Contact @support
"""


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
) -> User:
    """
    Get an existing user or create a new one.

    Args:
        session: The database session.
        telegram_id: The Telegram user ID.
        username: The Telegram username (optional).

    Returns:
        User: The existing or newly created user.
    """
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
        await session.flush()
        logger.info("Created new user", telegram_id=telegram_id, username=username)
    elif username and user.username != username:
        user.username = username
        await session.flush()

    return user


async def get_account_summary(session: AsyncSession, user_id: int) -> tuple[Decimal, int]:
    """
    Get the total balance and open trade count for a user.

    Args:
        session: The database session.
        user_id: The internal user ID.

    Returns:
        tuple: (total_balance, open_trade_count)
    """
    balance_result = await session.execute(
        select(func.sum(Account.current_balance))
        .where(Account.user_id == user_id)
        .where(Account.is_active == True)
    )
    total_balance = balance_result.scalar() or Decimal("0.00")

    account_ids_result = await session.execute(
        select(Account.id)
        .where(Account.user_id == user_id)
        .where(Account.is_active == True)
    )
    account_ids = [row[0] for row in account_ids_result.fetchall()]

    if account_ids:
        trade_count_result = await session.execute(
            select(func.count(Trade.id))
            .where(Trade.account_id.in_(account_ids))
            .where(Trade.status == TradeStatus.OPEN)
        )
        open_trade_count = trade_count_result.scalar() or 0
    else:
        open_trade_count = 0

    return total_balance, open_trade_count


def build_dashboard_message(
    total_balance: Decimal,
    open_trade_count: int,
    is_new_user: bool = False,
) -> str:
    """
    Build the main dashboard message text.

    Args:
        total_balance: The user's total account balance.
        open_trade_count: Number of open trades.
        is_new_user: Whether this is a first-time user.

    Returns:
        str: The formatted dashboard message.
    """
    if is_new_user:
        return WELCOME_MESSAGE

    lines = [
        "Trade Journal Dashboard",
        "",
        f"Total Balance: {format_currency(total_balance)}",
        f"Open Trades: {open_trade_count}",
        "",
        "Select an option below to continue:",
    ]

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /start command.

    Creates a new user if necessary and shows the main dashboard with account
    summary information.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.effective_user or not update.message:
        return

    telegram_id = update.effective_user.id
    username = update.effective_user.username

    logger.info("Start command received", telegram_id=telegram_id)

    try:
        async with get_session() as session:
            user_before = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            is_new_user = user_before.scalar_one_or_none() is None

            user = await get_or_create_user(session, telegram_id, username)

            total_balance, open_trade_count = await get_account_summary(
                session, user.id
            )

            message_text = build_dashboard_message(
                total_balance, open_trade_count, is_new_user
            )

            await update.message.reply_text(
                text=message_text,
                reply_markup=main_menu_keyboard(),
            )

            logger.info(
                "Dashboard displayed",
                telegram_id=telegram_id,
                total_balance=str(total_balance),
                open_trades=open_trade_count,
            )

    except Exception as e:
        logger.error("Error in start command", error=str(e), telegram_id=telegram_id)
        await update.message.reply_text(
            "An error occurred. Please try again later.",
            reply_markup=main_menu_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle the /help command.

    Shows detailed help information about the bot's features.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message:
        return

    logger.info("Help command received")

    await update.message.reply_text(
        text=HELP_MESSAGE,
        reply_markup=main_menu_keyboard(),
    )


async def handle_menu_home(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the "menu_home" callback to return to the main dashboard.

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
            user = await get_or_create_user(
                session, telegram_id, update.effective_user.username
            )

            total_balance, open_trade_count = await get_account_summary(
                session, user.id
            )

            message_text = build_dashboard_message(total_balance, open_trade_count)

            await query.edit_message_text(
                text=message_text,
                reply_markup=main_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error in menu home", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=main_menu_keyboard(),
        )


async def handle_help_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the "menu_help" callback to show help information.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query:
        return

    await query.answer()

    await query.edit_message_text(
        text=HELP_MESSAGE,
        reply_markup=main_menu_keyboard(),
    )
