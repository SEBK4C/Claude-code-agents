"""
Account management handlers for the Telegram Trade Journal Bot.

This module provides:
- Account creation wizard (ConversationHandler)
- Account list and detail views
- Account editing and deletion
- Deposit/Withdrawal handling
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
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
from database.models import Account, Trade, TradeStatus, Transaction, TransactionType, User
from utils.helpers import format_currency, format_datetime
from utils.keyboards import (
    account_select_keyboard,
    back_cancel_keyboard,
    back_to_menu_keyboard,
    confirmation_keyboard,
)
from utils.validation import validate_account_name, validate_price

logger = get_logger(__name__)

# Conversation states for account creation
ACCOUNT_NAME = 0
ACCOUNT_BROKER = 1
ACCOUNT_BALANCE = 2
ACCOUNT_CURRENCY = 3
ACCOUNT_CONFIRM = 4

# Conversation states for deposit/withdrawal
TRANSACTION_AMOUNT = 10
TRANSACTION_NOTE = 11

# Wizard data keys
WIZARD_KEY = "account_wizard"
TRANSACTION_KEY = "transaction_wizard"


def currency_keyboard() -> InlineKeyboardMarkup:
    """
    Create a keyboard for selecting account currency.

    Returns:
        InlineKeyboardMarkup: Currency selection keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("USD $", callback_data="currency_USD"),
            InlineKeyboardButton("EUR \u20ac", callback_data="currency_EUR"),
        ],
        [
            InlineKeyboardButton("GBP \u00a3", callback_data="currency_GBP"),
            InlineKeyboardButton("JPY \u00a5", callback_data="currency_JPY"),
        ],
        [
            InlineKeyboardButton("Cancel", callback_data="cancel"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def account_detail_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """
    Create a keyboard for account detail view with action buttons.

    Args:
        account_id: The account ID for callback data.

    Returns:
        InlineKeyboardMarkup: Account detail action keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Edit", callback_data=f"account_edit_{account_id}"),
            InlineKeyboardButton("Delete", callback_data=f"account_delete_{account_id}"),
        ],
        [
            InlineKeyboardButton("Add Deposit", callback_data=f"account_deposit_{account_id}"),
            InlineKeyboardButton("Add Withdrawal", callback_data=f"account_withdraw_{account_id}"),
        ],
        [
            InlineKeyboardButton("Back to Accounts", callback_data="menu_accounts"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def account_edit_keyboard(account_id: int) -> InlineKeyboardMarkup:
    """
    Create a keyboard for editing account properties.

    Args:
        account_id: The account ID for callback data.

    Returns:
        InlineKeyboardMarkup: Account edit options keyboard.
    """
    keyboard = [
        [
            InlineKeyboardButton("Edit Name", callback_data=f"account_editname_{account_id}"),
            InlineKeyboardButton("Edit Broker", callback_data=f"account_editbroker_{account_id}"),
        ],
        [
            InlineKeyboardButton("Back", callback_data=f"account_select_{account_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """
    Get a user by their Telegram ID.

    Args:
        session: The database session.
        telegram_id: The Telegram user ID.

    Returns:
        Optional[User]: The user if found, None otherwise.
    """
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def get_user_accounts(
    session: AsyncSession, user_id: int
) -> list[tuple[int, str, Decimal, str]]:
    """
    Get all active accounts for a user.

    Args:
        session: The database session.
        user_id: The internal user ID.

    Returns:
        list: List of (account_id, name, balance, currency) tuples.
    """
    result = await session.execute(
        select(Account.id, Account.name, Account.current_balance, Account.currency)
        .where(Account.user_id == user_id)
        .where(Account.is_active == True)
        .order_by(Account.name)
    )
    return [(row[0], row[1], row[2], row[3]) for row in result.fetchall()]


# ============================================================================
# ACCOUNT CREATION WIZARD
# ============================================================================


async def start_create_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Start the account creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (ACCOUNT_NAME).
    """
    query = update.callback_query
    if not query:
        return ConversationHandler.END

    await query.answer()

    context.user_data[WIZARD_KEY] = {}

    await query.edit_message_text(
        "Let's create a new trading account!\n\n"
        "Step 1 of 4: Enter a name for this account\n"
        "(e.g., 'Main Trading Account', 'Futures Account'):",
        reply_markup=back_cancel_keyboard(back_data="menu_accounts"),
    )

    return ACCOUNT_NAME


async def handle_account_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle account name input in the creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (ACCOUNT_BROKER) or current state on error.
    """
    if not update.message or not update.message.text:
        return ACCOUNT_NAME

    name_input = update.message.text.strip()
    validation = validate_account_name(name_input)

    if not validation.is_valid:
        await update.message.reply_text(
            f"Invalid account name: {validation.error}\n\n"
            "Please enter a valid account name (3-50 characters):",
        )
        return ACCOUNT_NAME

    context.user_data[WIZARD_KEY]["name"] = validation.value

    await update.message.reply_text(
        "Step 2 of 4: Enter your broker name\n"
        "(e.g., 'Interactive Brokers', 'TD Ameritrade'):",
        reply_markup=back_cancel_keyboard(),
    )

    return ACCOUNT_BROKER


async def handle_account_broker(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle broker name input in the creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (ACCOUNT_BALANCE).
    """
    if not update.message or not update.message.text:
        return ACCOUNT_BROKER

    broker_input = update.message.text.strip()

    if len(broker_input) > 255:
        await update.message.reply_text(
            "Broker name is too long (max 255 characters).\n"
            "Please enter a shorter name:",
        )
        return ACCOUNT_BROKER

    context.user_data[WIZARD_KEY]["broker"] = broker_input

    await update.message.reply_text(
        "Step 3 of 4: Enter your starting balance\n"
        "(e.g., '10000' or '5000.50'):",
        reply_markup=back_cancel_keyboard(),
    )

    return ACCOUNT_BALANCE


async def handle_account_balance(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle starting balance input in the creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (ACCOUNT_CURRENCY) or current state on error.
    """
    if not update.message or not update.message.text:
        return ACCOUNT_BALANCE

    balance_input = update.message.text.strip()
    validation = validate_price(balance_input)

    if not validation.is_valid:
        await update.message.reply_text(
            f"Invalid balance: {validation.error}\n\n"
            "Please enter a valid positive number:",
        )
        return ACCOUNT_BALANCE

    context.user_data[WIZARD_KEY]["balance"] = validation.value

    await update.message.reply_text(
        "Step 4 of 4: Select your account currency:",
        reply_markup=currency_keyboard(),
    )

    return ACCOUNT_CURRENCY


async def handle_account_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle currency selection in the creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: The next conversation state (ACCOUNT_CONFIRM).
    """
    query = update.callback_query
    if not query or not query.data:
        return ACCOUNT_CURRENCY

    await query.answer()

    if not query.data.startswith("currency_"):
        return ACCOUNT_CURRENCY

    currency = query.data.replace("currency_", "")
    context.user_data[WIZARD_KEY]["currency"] = currency

    wizard_data = context.user_data[WIZARD_KEY]

    summary = (
        "Please confirm your new account:\n\n"
        f"Name: {wizard_data['name']}\n"
        f"Broker: {wizard_data['broker']}\n"
        f"Starting Balance: {format_currency(wizard_data['balance'], currency)}\n"
        f"Currency: {currency}\n\n"
        "Is this correct?"
    )

    await query.edit_message_text(
        text=summary,
        reply_markup=confirmation_keyboard(
            confirm_text="Create Account",
            cancel_text="Cancel",
            confirm_data="account_confirm",
            cancel_data="cancel",
        ),
    )

    return ACCOUNT_CONFIRM


async def handle_account_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Handle account creation confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish the conversation.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return ConversationHandler.END

    await query.answer()

    if query.data != "account_confirm":
        context.user_data.pop(WIZARD_KEY, None)
        await query.edit_message_text(
            "Account creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END

    wizard_data = context.user_data.get(WIZARD_KEY, {})
    if not wizard_data:
        # Stale state - return silently
        return ConversationHandler.END

    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await query.edit_message_text(
                    "User not found. Please use /start first.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return ConversationHandler.END

            account = Account(
                user_id=user.id,
                name=wizard_data["name"],
                broker=wizard_data["broker"],
                starting_balance=wizard_data["balance"],
                current_balance=wizard_data["balance"],
                currency=wizard_data["currency"],
                is_active=True,
            )
            session.add(account)
            await session.flush()

            logger.info(
                "Account created",
                account_id=account.id,
                telegram_id=telegram_id,
                name=account.name,
            )

            await query.edit_message_text(
                f"Account '{account.name}' created successfully!\n\n"
                f"Starting Balance: {format_currency(account.current_balance, account.currency)}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error creating account", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred while creating the account. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(WIZARD_KEY, None)
    return ConversationHandler.END


async def cancel_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Cancel the account creation wizard.

    Args:
        update: The Telegram update object.
        context: The callback context.

    Returns:
        int: ConversationHandler.END to finish the conversation.
    """
    context.user_data.pop(WIZARD_KEY, None)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            "Account creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )
    elif update.message:
        await update.message.reply_text(
            "Account creation cancelled.",
            reply_markup=back_to_menu_keyboard(),
        )

    return ConversationHandler.END


# Account creation ConversationHandler
account_create_conversation = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_create_account, pattern="^account_create$"),
    ],
    states={
        ACCOUNT_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_name),
        ],
        ACCOUNT_BROKER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_broker),
        ],
        ACCOUNT_BALANCE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_account_balance),
        ],
        ACCOUNT_CURRENCY: [
            CallbackQueryHandler(handle_account_currency, pattern="^currency_"),
        ],
        ACCOUNT_CONFIRM: [
            CallbackQueryHandler(handle_account_confirm, pattern="^(account_confirm|cancel)$"),
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_wizard),
        CallbackQueryHandler(cancel_wizard, pattern="^cancel$"),
        CallbackQueryHandler(cancel_wizard, pattern="^back$"),
        CallbackQueryHandler(cancel_wizard, pattern="^menu_accounts$"),
    ],
    per_message=False,
)


# ============================================================================
# ACCOUNT LIST AND DETAIL
# ============================================================================


async def handle_accounts_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle the accounts menu callback - show list of all accounts.

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

            accounts = await get_user_accounts(session, user.id)

            if not accounts:
                message = (
                    "You don't have any trading accounts yet.\n\n"
                    "Create your first account to start tracking trades!"
                )
            else:
                message = "Your Trading Accounts:\n\n"
                for acc_id, name, balance, currency in accounts:
                    message += f"- {name}: {format_currency(balance, currency)}\n"
                message += "\nSelect an account to view details:"

            account_tuples = [(acc_id, name) for acc_id, name, _, _ in accounts]
            await query.edit_message_text(
                text=message,
                reply_markup=account_select_keyboard(account_tuples, include_create=True),
            )

    except Exception as e:
        logger.error("Error loading accounts", error=str(e), telegram_id=telegram_id)
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


async def handle_account_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle account detail view - show account information and actions.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    account_id_str = query.data.replace("account_select_", "")
    try:
        account_id = int(account_id_str)
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
                select(Account)
                .where(Account.id == account_id)
                .where(Account.user_id == user.id)
                .where(Account.is_active == True)
            )
            account = result.scalar_one_or_none()

            if not account:
                await query.edit_message_text(
                    "Account not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                return

            trade_count_result = await session.execute(
                select(func.count(Trade.id))
                .where(Trade.account_id == account_id)
            )
            total_trades = trade_count_result.scalar() or 0

            open_trades_result = await session.execute(
                select(func.count(Trade.id))
                .where(Trade.account_id == account_id)
                .where(Trade.status == TradeStatus.OPEN)
            )
            open_trades = open_trades_result.scalar() or 0

            pnl_result = await session.execute(
                select(func.sum(Trade.pnl))
                .where(Trade.account_id == account_id)
                .where(Trade.status == TradeStatus.CLOSED)
            )
            total_pnl = pnl_result.scalar() or Decimal("0.00")

            message = (
                f"Account: {account.name}\n"
                f"{'=' * 30}\n\n"
                f"Broker: {account.broker or 'N/A'}\n"
                f"Currency: {account.currency}\n"
                f"Starting Balance: {format_currency(account.starting_balance, account.currency)}\n"
                f"Current Balance: {format_currency(account.current_balance, account.currency)}\n"
                f"Total P&L: {format_currency(total_pnl, account.currency, include_sign=True)}\n\n"
                f"Total Trades: {total_trades}\n"
                f"Open Trades: {open_trades}\n"
                f"Created: {format_datetime(account.created_at)}"
            )

            await query.edit_message_text(
                text=message,
                reply_markup=account_detail_keyboard(account_id),
            )

    except Exception as e:
        logger.error(
            "Error loading account detail",
            error=str(e),
            account_id=account_id,
            telegram_id=telegram_id,
        )
        await query.edit_message_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )


# ============================================================================
# ACCOUNT EDITING
# ============================================================================


async def handle_account_edit(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle account edit callback - show edit options.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    account_id_str = query.data.replace("account_edit_", "")
    try:
        account_id = int(account_id_str)
    except ValueError:
        return

    await query.edit_message_text(
        "What would you like to edit?",
        reply_markup=account_edit_keyboard(account_id),
    )


# ============================================================================
# ACCOUNT DELETION
# ============================================================================


async def handle_account_delete_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle account deletion with confirmation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    if query.data.startswith("account_delete_"):
        account_id_str = query.data.replace("account_delete_", "")
        try:
            account_id = int(account_id_str)
        except ValueError:
            return

        context.user_data["delete_account_id"] = account_id

        await query.edit_message_text(
            "Are you sure you want to delete this account?\n\n"
            "This will hide the account but preserve trade history.",
            reply_markup=confirmation_keyboard(
                confirm_text="Yes, Delete",
                cancel_text="No, Keep It",
                confirm_data="account_delete_confirm",
                cancel_data="account_delete_cancel",
            ),
        )

    elif query.data == "account_delete_confirm":
        account_id = context.user_data.get("delete_account_id")
        if not account_id:
            # Stale state - return silently
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
                    select(Account)
                    .where(Account.id == account_id)
                    .where(Account.user_id == user.id)
                )
                account = result.scalar_one_or_none()

                if account:
                    account.is_active = False
                    await session.flush()

                    logger.info(
                        "Account deleted",
                        account_id=account_id,
                        telegram_id=telegram_id,
                    )

                    await query.edit_message_text(
                        f"Account '{account.name}' has been deleted.",
                        reply_markup=back_to_menu_keyboard(),
                    )
                else:
                    await query.edit_message_text(
                        "Account not found.",
                        reply_markup=back_to_menu_keyboard(),
                    )

        except Exception as e:
            logger.error("Error deleting account", error=str(e))
            await query.edit_message_text(
                "An error occurred. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )

        context.user_data.pop("delete_account_id", None)

    elif query.data == "account_delete_cancel":
        account_id = context.user_data.pop("delete_account_id", None)
        if account_id:
            from handlers.accounts import handle_account_detail

            query.data = f"account_select_{account_id}"
            await handle_account_detail(update, context)
        else:
            await query.edit_message_text(
                "Operation cancelled.",
                reply_markup=back_to_menu_keyboard(),
            )


# ============================================================================
# DEPOSIT / WITHDRAWAL
# ============================================================================


async def handle_deposit_withdraw(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle deposit or withdrawal initiation.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    await query.answer()

    if query.data.startswith("account_deposit_"):
        transaction_type = "deposit"
        account_id_str = query.data.replace("account_deposit_", "")
    elif query.data.startswith("account_withdraw_"):
        transaction_type = "withdrawal"
        account_id_str = query.data.replace("account_withdraw_", "")
    else:
        return

    try:
        account_id = int(account_id_str)
    except ValueError:
        return

    context.user_data[TRANSACTION_KEY] = {
        "account_id": account_id,
        "type": transaction_type,
    }

    type_display = "deposit" if transaction_type == "deposit" else "withdrawal"

    await query.edit_message_text(
        f"Enter the {type_display} amount:",
        reply_markup=back_cancel_keyboard(back_data=f"account_select_{account_id}"),
    )


async def handle_transaction_amount(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle transaction amount input for deposits/withdrawals.

    Raises ApplicationHandlerStop after handling to prevent other
    handler groups from processing the same message.

    Args:
        update: The Telegram update object.
        context: The callback context.
    """
    if not update.message or not update.message.text or not update.effective_user:
        return

    trans_data = context.user_data.get(TRANSACTION_KEY)
    if not trans_data:
        # Not in transaction flow - let other handlers process this message
        return

    amount_input = update.message.text.strip()
    validation = validate_price(amount_input)

    if not validation.is_valid:
        await update.message.reply_text(
            f"Invalid amount: {validation.error}\n\n"
            "Please enter a valid positive number:",
        )
        return

    amount = validation.value
    account_id = trans_data["account_id"]
    transaction_type = trans_data["type"]
    telegram_id = update.effective_user.id

    try:
        async with get_session() as session:
            user = await get_user_by_telegram_id(session, telegram_id)
            if not user:
                await update.message.reply_text(
                    "User not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(TRANSACTION_KEY, None)
                return

            result = await session.execute(
                select(Account)
                .where(Account.id == account_id)
                .where(Account.user_id == user.id)
                .where(Account.is_active == True)
            )
            account = result.scalar_one_or_none()

            if not account:
                await update.message.reply_text(
                    "Account not found.",
                    reply_markup=back_to_menu_keyboard(),
                )
                context.user_data.pop(TRANSACTION_KEY, None)
                return

            if transaction_type == "deposit":
                account.current_balance += amount
                trans_type_enum = TransactionType.DEPOSIT
            else:
                if account.current_balance < amount:
                    await update.message.reply_text(
                        f"Insufficient balance. Current balance: "
                        f"{format_currency(account.current_balance, account.currency)}",
                    )
                    return
                account.current_balance -= amount
                trans_type_enum = TransactionType.WITHDRAWAL

            transaction = Transaction(
                account_id=account_id,
                type=trans_type_enum,
                amount=amount,
                note=None,
            )
            session.add(transaction)
            await session.flush()

            logger.info(
                "Transaction completed",
                transaction_id=transaction.id,
                account_id=account_id,
                type=transaction_type,
                amount=str(amount),
            )

            type_display = "Deposit" if transaction_type == "deposit" else "Withdrawal"
            await update.message.reply_text(
                f"{type_display} completed!\n\n"
                f"Amount: {format_currency(amount, account.currency)}\n"
                f"New Balance: {format_currency(account.current_balance, account.currency)}",
                reply_markup=back_to_menu_keyboard(),
            )

    except Exception as e:
        logger.error("Error processing transaction", error=str(e))
        await update.message.reply_text(
            "An error occurred. Please try again.",
            reply_markup=back_to_menu_keyboard(),
        )

    context.user_data.pop(TRANSACTION_KEY, None)
    raise ApplicationHandlerStop  # Prevent other handler groups from firing
