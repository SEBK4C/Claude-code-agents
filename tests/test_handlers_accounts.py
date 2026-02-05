"""
Tests for account management handlers.

This module tests:
- Account creation wizard
- Account list display
- Account detail view
- Account editing and deletion
- Deposit/withdrawal handling
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import ConversationHandler

from database.models import Account, Transaction, TransactionType, User
from handlers.accounts import (
    ACCOUNT_BALANCE,
    ACCOUNT_BROKER,
    ACCOUNT_CONFIRM,
    ACCOUNT_CURRENCY,
    ACCOUNT_NAME,
    WIZARD_KEY,
    account_create_conversation,
    account_detail_keyboard,
    account_edit_keyboard,
    cancel_wizard,
    currency_keyboard,
    get_user_accounts,
    get_user_by_telegram_id,
    handle_account_balance,
    handle_account_broker,
    handle_account_confirm,
    handle_account_currency,
    handle_account_delete_confirm,
    handle_account_detail,
    handle_account_edit,
    handle_account_name,
    handle_accounts_menu,
    handle_deposit_withdraw,
    handle_transaction_amount,
    start_create_account,
)


class TestCurrencyKeyboard:
    """Tests for currency_keyboard function."""

    def test_returns_inline_keyboard(self):
        """Test that currency_keyboard returns valid keyboard."""
        keyboard = currency_keyboard()

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 3
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_contains_supported_currencies(self):
        """Test that keyboard contains expected currencies."""
        keyboard = currency_keyboard()
        buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                buttons.append(button.callback_data)

        assert "currency_USD" in buttons
        assert "currency_EUR" in buttons
        assert "currency_GBP" in buttons
        assert "currency_JPY" in buttons


class TestAccountDetailKeyboard:
    """Tests for account_detail_keyboard function."""

    def test_returns_keyboard_with_edit_delete(self):
        """Test that keyboard has edit and delete buttons."""
        keyboard = account_detail_keyboard(123)

        assert keyboard is not None
        callbacks = []
        for row in keyboard.inline_keyboard:
            for button in row:
                callbacks.append(button.callback_data)

        assert "account_edit_123" in callbacks
        assert "account_delete_123" in callbacks
        assert "account_deposit_123" in callbacks
        assert "account_withdraw_123" in callbacks

    def test_includes_back_button(self):
        """Test that keyboard includes back to accounts button."""
        keyboard = account_detail_keyboard(456)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "menu_accounts" in callbacks


class TestAccountEditKeyboard:
    """Tests for account_edit_keyboard function."""

    def test_returns_keyboard_with_edit_options(self):
        """Test that keyboard has name and broker edit options."""
        keyboard = account_edit_keyboard(789)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "account_editname_789" in callbacks
        assert "account_editbroker_789" in callbacks


class TestGetUserByTelegramId:
    """Tests for get_user_by_telegram_id function."""

    @pytest.mark.asyncio
    async def test_returns_user_when_found(
        self, session: AsyncSession, sample_user: User
    ):
        """Test that user is returned when found."""
        user = await get_user_by_telegram_id(session, sample_user.telegram_id)

        assert user is not None
        assert user.id == sample_user.id

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, session: AsyncSession):
        """Test that None is returned when user not found."""
        user = await get_user_by_telegram_id(session, 999999999)

        assert user is None


class TestGetUserAccounts:
    """Tests for get_user_accounts function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_for_user_without_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test returns empty list when user has no accounts."""
        accounts = await get_user_accounts(session, sample_user.id)

        assert accounts == []

    @pytest.mark.asyncio
    async def test_returns_active_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test returns list of active accounts."""
        account = Account(
            user_id=sample_user.id,
            name="Test Account",
            broker="Test Broker",
            starting_balance=Decimal("10000.00"),
            current_balance=Decimal("10500.00"),
            currency="USD",
            is_active=True,
        )
        session.add(account)
        await session.flush()

        accounts = await get_user_accounts(session, sample_user.id)

        assert len(accounts) == 1
        assert accounts[0][1] == "Test Account"
        assert accounts[0][2] == Decimal("10500.00")

    @pytest.mark.asyncio
    async def test_excludes_inactive_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test that inactive accounts are excluded."""
        active_account = Account(
            user_id=sample_user.id,
            name="Active",
            broker="Broker",
            starting_balance=Decimal("1000.00"),
            current_balance=Decimal("1000.00"),
            currency="USD",
            is_active=True,
        )
        inactive_account = Account(
            user_id=sample_user.id,
            name="Inactive",
            broker="Broker",
            starting_balance=Decimal("5000.00"),
            current_balance=Decimal("5000.00"),
            currency="USD",
            is_active=False,
        )
        session.add(active_account)
        session.add(inactive_account)
        await session.flush()

        accounts = await get_user_accounts(session, sample_user.id)

        assert len(accounts) == 1
        assert accounts[0][1] == "Active"


class TestAccountCreationWizard:
    """Tests for account creation wizard handlers."""

    @pytest.mark.asyncio
    async def test_start_create_account_initializes_wizard(self):
        """Test that start_create_account initializes wizard state."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}

        result = await start_create_account(update, context)

        assert result == ACCOUNT_NAME
        assert WIZARD_KEY in context.user_data
        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_account_name_valid_input(self):
        """Test handling valid account name input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "My Trading Account"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {}}

        result = await handle_account_name(update, context)

        assert result == ACCOUNT_BROKER
        assert context.user_data[WIZARD_KEY]["name"] == "My Trading Account"

    @pytest.mark.asyncio
    async def test_handle_account_name_invalid_input(self):
        """Test handling invalid account name (too short)."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "AB"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {}}

        result = await handle_account_name(update, context)

        assert result == ACCOUNT_NAME
        update.message.reply_text.assert_called_once()
        assert "Invalid account name" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_handle_account_broker_stores_value(self):
        """Test that broker name is stored correctly."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "Interactive Brokers"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {"name": "Test"}}

        result = await handle_account_broker(update, context)

        assert result == ACCOUNT_BALANCE
        assert context.user_data[WIZARD_KEY]["broker"] == "Interactive Brokers"

    @pytest.mark.asyncio
    async def test_handle_account_balance_valid_input(self):
        """Test handling valid balance input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "10000.50"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {"name": "Test", "broker": "Broker"}}

        result = await handle_account_balance(update, context)

        assert result == ACCOUNT_CURRENCY
        assert context.user_data[WIZARD_KEY]["balance"] == Decimal("10000.50")

    @pytest.mark.asyncio
    async def test_handle_account_balance_invalid_input(self):
        """Test handling invalid balance input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "not a number"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {"name": "Test", "broker": "Broker"}}

        result = await handle_account_balance(update, context)

        assert result == ACCOUNT_BALANCE
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_account_currency_selection(self):
        """Test currency selection callback."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "currency_EUR"

        context = MagicMock()
        context.user_data = {
            WIZARD_KEY: {
                "name": "Test Account",
                "broker": "Test Broker",
                "balance": Decimal("5000.00"),
            }
        }

        result = await handle_account_currency(update, context)

        assert result == ACCOUNT_CONFIRM
        assert context.user_data[WIZARD_KEY]["currency"] == "EUR"

    @pytest.mark.asyncio
    async def test_cancel_wizard_clears_state(self):
        """Test that cancel_wizard clears wizard state."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.message = None

        context = MagicMock()
        context.user_data = {WIZARD_KEY: {"name": "Test"}}

        result = await cancel_wizard(update, context)

        assert result == ConversationHandler.END
        assert WIZARD_KEY not in context.user_data


class TestAccountManagement:
    """Tests for account management handlers."""

    @pytest.mark.asyncio
    async def test_handle_accounts_menu_no_accounts(self):
        """Test accounts menu with no accounts."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456

        context = MagicMock()

        with patch("handlers.accounts.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_user = MagicMock()
            mock_user.id = 1
            mock_session.execute = AsyncMock()
            mock_session.execute.return_value.scalar_one_or_none = MagicMock(
                return_value=mock_user
            )
            mock_session.execute.return_value.fetchall = MagicMock(return_value=[])

            await handle_accounts_menu(update, context)

            update.callback_query.answer.assert_called_once()
            call_kwargs = update.callback_query.edit_message_text.call_args.kwargs
            assert "don't have any trading accounts" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_handle_account_edit_shows_options(self):
        """Test that account edit callback shows edit options."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "account_edit_123"

        context = MagicMock()

        await handle_account_edit(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        # Check either positional args or kwargs
        text = call_args.kwargs.get("text") or call_args[0][0]
        assert "What would you like to edit?" in text


class TestDepositWithdraw:
    """Tests for deposit/withdrawal handlers."""

    @pytest.mark.asyncio
    async def test_handle_deposit_starts_flow(self):
        """Test that deposit callback starts transaction flow."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "account_deposit_123"
        update.effective_user = MagicMock()

        context = MagicMock()
        context.user_data = {}

        await handle_deposit_withdraw(update, context)

        update.callback_query.answer.assert_called_once()
        assert "transaction_wizard" in context.user_data
        assert context.user_data["transaction_wizard"]["type"] == "deposit"
        assert context.user_data["transaction_wizard"]["account_id"] == 123

    @pytest.mark.asyncio
    async def test_handle_withdraw_starts_flow(self):
        """Test that withdrawal callback starts transaction flow."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "account_withdraw_456"
        update.effective_user = MagicMock()

        context = MagicMock()
        context.user_data = {}

        await handle_deposit_withdraw(update, context)

        assert context.user_data["transaction_wizard"]["type"] == "withdrawal"
        assert context.user_data["transaction_wizard"]["account_id"] == 456

    @pytest.mark.asyncio
    async def test_handle_transaction_amount_no_session(self):
        """Test transaction amount handler with expired session returns silently."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "1000"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()

        context = MagicMock()
        context.user_data = {}

        await handle_transaction_amount(update, context)

        # Stale state results in silent return - no message to user
        update.message.reply_text.assert_not_called()


class TestAccountDeletion:
    """Tests for account deletion handler."""

    @pytest.mark.asyncio
    async def test_delete_confirmation_shows_warning(self):
        """Test that delete shows confirmation warning."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "account_delete_123"
        update.effective_user = MagicMock()

        context = MagicMock()
        context.user_data = {}

        await handle_account_delete_confirm(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        # Check either positional args or kwargs
        text = call_args.kwargs.get("text") or call_args[0][0]
        assert "Are you sure" in text
        assert context.user_data["delete_account_id"] == 123


class TestConversationHandler:
    """Tests for the conversation handler configuration."""

    def test_conversation_handler_has_entry_points(self):
        """Test that conversation handler has entry points configured."""
        assert len(account_create_conversation.entry_points) > 0

    def test_conversation_handler_has_all_states(self):
        """Test that all required states are configured."""
        states = account_create_conversation.states

        assert ACCOUNT_NAME in states
        assert ACCOUNT_BROKER in states
        assert ACCOUNT_BALANCE in states
        assert ACCOUNT_CURRENCY in states
        assert ACCOUNT_CONFIRM in states

    def test_conversation_handler_has_fallbacks(self):
        """Test that conversation handler has fallback handlers."""
        assert len(account_create_conversation.fallbacks) > 0
