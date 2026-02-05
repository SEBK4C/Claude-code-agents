"""
Tests for the natural language trade input handlers.

This module tests:
- Natural trade message detection and parsing
- Missing field prompts
- Account selection flow
- Trade confirmation flow
- Open and close trade saving
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Account,
    Trade,
    TradeDirection,
    TradeStatus,
    User,
)
from handlers.natural_input import (
    NATURAL_TRADE_KEY,
    NATURAL_TRADE_STATE_KEY,
    STATE_AWAITING_ACCOUNT,
    STATE_AWAITING_DIRECTION,
    STATE_AWAITING_ENTRY_PRICE,
    STATE_AWAITING_EXIT_PRICE,
    STATE_AWAITING_INSTRUMENT,
    STATE_AWAITING_LOT_SIZE,
    STATE_CONFIRM_CLOSE,
    STATE_CONFIRM_OPEN,
    _build_open_trade_summary,
    _clear_natural_trade_state,
    account_select_keyboard,
    get_or_create_tags,
    get_user_accounts_list,
    get_user_open_trades,
    handle_missing_field_response,
    handle_natural_trade_input,
    natural_trade_confirm_keyboard,
    open_trade_select_keyboard,
)
from services.trade_parser import reset_trade_parser


@pytest.fixture(autouse=True)
def reset_parser():
    """Reset the trade parser singleton before each test."""
    reset_trade_parser()
    yield
    reset_trade_parser()


class TestKeyboards:
    """Tests for keyboard generation functions."""

    def test_natural_trade_confirm_keyboard_open(self):
        """Test confirmation keyboard for open action."""
        keyboard = natural_trade_confirm_keyboard("open")
        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 1
        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "natural_open_confirm" in callbacks
        assert "natural_cancel" in callbacks

    def test_natural_trade_confirm_keyboard_close(self):
        """Test confirmation keyboard for close action."""
        keyboard = natural_trade_confirm_keyboard("close")
        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "natural_close_confirm" in callbacks
        assert "natural_cancel" in callbacks

    def test_account_select_keyboard(self):
        """Test account selection keyboard generation."""
        accounts = [(1, "Account 1"), (2, "Account 2")]
        keyboard = account_select_keyboard(accounts)

        assert len(keyboard.inline_keyboard) == 3  # 2 accounts + cancel
        assert keyboard.inline_keyboard[0][0].text == "Account 1"
        assert keyboard.inline_keyboard[0][0].callback_data == "natural_acc_1"
        assert keyboard.inline_keyboard[1][0].text == "Account 2"
        assert keyboard.inline_keyboard[-1][0].callback_data == "natural_cancel"

    def test_open_trade_select_keyboard(self):
        """Test open trade selection keyboard."""
        trades = [
            (1, "DAX", "long", Decimal("18500")),
            (2, "NASDAQ", "short", Decimal("19000")),
        ]
        keyboard = open_trade_select_keyboard(trades)

        assert len(keyboard.inline_keyboard) == 3  # 2 trades + cancel
        assert "DAX LONG @ 18500" in keyboard.inline_keyboard[0][0].text
        assert keyboard.inline_keyboard[0][0].callback_data == "natural_close_1"


class TestBuildOpenTradeSummary:
    """Tests for trade summary building."""

    def test_build_full_summary(self):
        """Test building summary with all fields."""
        trade_data = {
            "instrument": "DAX",
            "direction": "long",
            "entry_price": "18500",
            "sl_price": "18450",
            "tp_price": "18600",
            "lot_size": "0.5",
            "tags": ["Breakout", "Trend"],
        }
        summary = _build_open_trade_summary(trade_data)

        assert "DAX" in summary
        assert "LONG" in summary
        assert "18500" in summary
        assert "18450" in summary
        assert "18600" in summary
        assert "0.5" in summary
        assert "Breakout" in summary

    def test_build_minimal_summary(self):
        """Test building summary with minimal fields."""
        trade_data = {
            "instrument": "DAX",
            "direction": "long",
            "entry_price": "18500",
        }
        summary = _build_open_trade_summary(trade_data)

        assert "DAX" in summary
        assert "LONG" in summary
        assert "18500" in summary
        assert "Not set" in summary  # For missing SL/TP


class TestClearNaturalTradeState:
    """Tests for state clearing function."""

    def test_clear_all_state(self):
        """Test that all natural trade state is cleared."""
        context = MagicMock()
        context.user_data = {
            NATURAL_TRADE_KEY: {"instrument": "DAX"},
            NATURAL_TRADE_STATE_KEY: STATE_AWAITING_DIRECTION,
            "other_key": "should_remain",
        }

        _clear_natural_trade_state(context)

        assert NATURAL_TRADE_KEY not in context.user_data
        assert NATURAL_TRADE_STATE_KEY not in context.user_data
        assert context.user_data["other_key"] == "should_remain"

    def test_clear_empty_state(self):
        """Test clearing when state is already empty."""
        context = MagicMock()
        context.user_data = {}

        # Should not raise
        _clear_natural_trade_state(context)

        assert NATURAL_TRADE_KEY not in context.user_data


class TestDatabaseHelpers:
    """Tests for database helper functions."""

    @pytest_asyncio.fixture
    async def sample_user(self, session: AsyncSession) -> User:
        """Create a sample user for testing."""
        user = User(telegram_id=123456789, username="testuser")
        session.add(user)
        await session.flush()
        return user

    @pytest_asyncio.fixture
    async def sample_account(
        self, session: AsyncSession, sample_user: User
    ) -> Account:
        """Create a sample account for testing."""
        account = Account(
            user_id=sample_user.id,
            name="Test Account",
            broker="Test Broker",
            starting_balance=Decimal("10000.00"),
            current_balance=Decimal("10000.00"),
            currency="USD",
            is_active=True,
        )
        session.add(account)
        await session.flush()
        return account

    @pytest_asyncio.fixture
    async def sample_open_trade(
        self, session: AsyncSession, sample_account: Account
    ) -> Trade:
        """Create a sample open trade for testing."""
        trade = Trade(
            account_id=sample_account.id,
            instrument="DAX",
            direction=TradeDirection.LONG,
            entry_price=Decimal("18500"),
            lot_size=Decimal("0.5"),
            status=TradeStatus.OPEN,
        )
        session.add(trade)
        await session.flush()
        return trade

    @pytest.mark.asyncio
    async def test_get_user_accounts_list(
        self, session: AsyncSession, sample_user: User, sample_account: Account
    ):
        """Test fetching user accounts."""
        accounts = await get_user_accounts_list(session, sample_user.id)

        assert len(accounts) == 1
        assert accounts[0][0] == sample_account.id
        assert accounts[0][1] == "Test Account"

    @pytest.mark.asyncio
    async def test_get_user_accounts_list_empty(
        self, session: AsyncSession, sample_user: User
    ):
        """Test fetching accounts for user with none."""
        accounts = await get_user_accounts_list(session, sample_user.id)
        assert accounts == []

    @pytest.mark.asyncio
    async def test_get_user_open_trades(
        self,
        session: AsyncSession,
        sample_user: User,
        sample_account: Account,
        sample_open_trade: Trade,
    ):
        """Test fetching open trades."""
        trades = await get_user_open_trades(session, sample_user.id)

        assert len(trades) == 1
        assert trades[0].instrument == "DAX"
        assert trades[0].direction == TradeDirection.LONG

    @pytest.mark.asyncio
    async def test_get_user_open_trades_with_filter(
        self,
        session: AsyncSession,
        sample_user: User,
        sample_account: Account,
        sample_open_trade: Trade,
    ):
        """Test fetching open trades with instrument filter."""
        # Add another trade with different instrument
        trade2 = Trade(
            account_id=sample_account.id,
            instrument="NASDAQ",
            direction=TradeDirection.SHORT,
            entry_price=Decimal("19000"),
            lot_size=Decimal("1"),
            status=TradeStatus.OPEN,
        )
        session.add(trade2)
        await session.flush()

        # Filter by DAX
        trades = await get_user_open_trades(
            session, sample_user.id, instrument="DAX"
        )
        assert len(trades) == 1
        assert trades[0].instrument == "DAX"

        # Filter by direction
        trades = await get_user_open_trades(
            session, sample_user.id, direction="short"
        )
        assert len(trades) == 1
        assert trades[0].direction == TradeDirection.SHORT

    @pytest.mark.asyncio
    async def test_get_or_create_tags_creates_new(self, session: AsyncSession):
        """Test that get_or_create_tags creates new tags."""
        tag_names = ["NewTag1", "NewTag2"]
        tags = await get_or_create_tags(session, tag_names)

        assert len(tags) == 2
        assert tags[0].name == "NewTag1"
        assert tags[1].name == "NewTag2"

    @pytest.mark.asyncio
    async def test_get_or_create_tags_returns_existing(
        self, session: AsyncSession
    ):
        """Test that get_or_create_tags returns existing tags."""
        # First call creates tags
        tags1 = await get_or_create_tags(session, ["ExistingTag"])
        tag_id = tags1[0].id

        # Second call should return same tag
        tags2 = await get_or_create_tags(session, ["ExistingTag"])
        assert tags2[0].id == tag_id


class TestHandleNaturalTradeInput:
    """Tests for the main natural trade input handler."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock Update object."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "Bought DAX at 18500 sl 18450 tp 18600 0.5 lots"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456789
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock Context object."""
        context = MagicMock()
        context.user_data = {}
        return context

    @pytest.mark.asyncio
    async def test_returns_false_for_no_message(self, mock_context):
        """Test that handler returns False when no message."""
        update = MagicMock()
        update.message = None

        result = await handle_natural_trade_input(update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_low_confidence(
        self, mock_update, mock_context
    ):
        """Test that handler returns False for low confidence messages."""
        mock_update.message.text = "Hello there"

        result = await handle_natural_trade_input(mock_update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    @patch("handlers.natural_input.get_session")
    @patch("handlers.natural_input.get_user_by_telegram_id")
    async def test_handles_unregistered_user(
        self, mock_get_user, mock_get_session, mock_update, mock_context
    ):
        """Test handling of unregistered user."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session
        mock_get_user.return_value = None

        result = await handle_natural_trade_input(mock_update, mock_context)

        assert result is True
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Please use /start" in call_args


class TestHandleMissingFieldResponse:
    """Tests for missing field response handler."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock Update object."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "DAX"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456789
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock Context object."""
        context = MagicMock()
        context.user_data = {}
        return context

    @pytest.mark.asyncio
    async def test_returns_false_when_no_state(
        self, mock_update, mock_context
    ):
        """Test returns False when not in a natural trade state."""
        result = await handle_missing_field_response(mock_update, mock_context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handles_instrument_response(
        self, mock_update, mock_context
    ):
        """Test handling instrument response - validates instrument is stored."""
        mock_context.user_data = {
            NATURAL_TRADE_STATE_KEY: STATE_AWAITING_INSTRUMENT,
            NATURAL_TRADE_KEY: {
                "action": "open",
                "direction": "long",
                "entry_price": "18500",
                "missing_fields": ["instrument", "lot_size"],
                "user_id": 1,
                "account_id": 1,
            },
        }
        mock_update.message.text = "DAX"

        with patch("handlers.natural_input.get_session") as mock_get_session:
            # Create a proper async context manager mock
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session

            # Mock the account query result
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(1, "Test Account")]
            mock_session.execute.return_value = mock_result

            result = await handle_missing_field_response(
                mock_update, mock_context
            )

        assert result is True
        assert mock_context.user_data[NATURAL_TRADE_KEY]["instrument"] == "DAX"

    @pytest.mark.asyncio
    async def test_handles_invalid_price(self, mock_update, mock_context):
        """Test handling invalid price input."""
        mock_context.user_data = {
            NATURAL_TRADE_STATE_KEY: STATE_AWAITING_ENTRY_PRICE,
            NATURAL_TRADE_KEY: {
                "action": "open",
                "instrument": "DAX",
                "direction": "long",
                "missing_fields": ["entry_price"],
                "user_id": 1,
            },
        }
        mock_update.message.text = "not a price"

        result = await handle_missing_field_response(mock_update, mock_context)

        assert result is True
        mock_update.message.reply_text.assert_called()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "valid price" in call_args

    @pytest.mark.asyncio
    async def test_handles_valid_entry_price(self, mock_update, mock_context):
        """Test handling valid entry price input."""
        mock_context.user_data = {
            NATURAL_TRADE_STATE_KEY: STATE_AWAITING_ENTRY_PRICE,
            NATURAL_TRADE_KEY: {
                "action": "open",
                "instrument": "DAX",
                "direction": "long",
                "missing_fields": ["entry_price", "lot_size"],
                "user_id": 1,
                "account_id": 1,
            },
        }
        mock_update.message.text = "18500"

        with patch("handlers.natural_input.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session

            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(1, "Test Account")]
            mock_session.execute.return_value = mock_result

            result = await handle_missing_field_response(
                mock_update, mock_context
            )

        assert result is True
        assert (
            mock_context.user_data[NATURAL_TRADE_KEY]["entry_price"] == "18500"
        )

    @pytest.mark.asyncio
    async def test_handles_lot_size_response(self, mock_update, mock_context):
        """Test handling lot size response."""
        mock_context.user_data = {
            NATURAL_TRADE_STATE_KEY: STATE_AWAITING_LOT_SIZE,
            NATURAL_TRADE_KEY: {
                "action": "open",
                "instrument": "DAX",
                "direction": "long",
                "entry_price": "18500",
                "missing_fields": ["lot_size"],
                "user_id": 1,
                "account_id": 1,
            },
        }
        mock_update.message.text = "0.5"

        with patch("handlers.natural_input.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session

            mock_result = MagicMock()
            mock_result.fetchall.return_value = [(1, "Test Account")]
            mock_session.execute.return_value = mock_result

            result = await handle_missing_field_response(
                mock_update, mock_context
            )

        assert result is True
        assert mock_context.user_data[NATURAL_TRADE_KEY]["lot_size"] == "0.5"


class TestContextStates:
    """Tests for context state constants."""

    def test_state_constants_are_unique(self):
        """Test that all state constants have unique values."""
        states = [
            STATE_AWAITING_INSTRUMENT,
            STATE_AWAITING_DIRECTION,
            STATE_AWAITING_ENTRY_PRICE,
            STATE_AWAITING_EXIT_PRICE,
            STATE_AWAITING_LOT_SIZE,
            STATE_AWAITING_ACCOUNT,
            STATE_CONFIRM_OPEN,
            STATE_CONFIRM_CLOSE,
        ]
        assert len(states) == len(set(states))

    def test_context_key_constants(self):
        """Test context key constants exist and are strings."""
        assert isinstance(NATURAL_TRADE_KEY, str)
        assert isinstance(NATURAL_TRADE_STATE_KEY, str)
        assert NATURAL_TRADE_KEY != NATURAL_TRADE_STATE_KEY
