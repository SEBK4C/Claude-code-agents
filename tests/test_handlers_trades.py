"""
Tests for trade management handlers.

This module tests:
- Trade entry wizard (12-step)
- Trade listing (open and closed)
- Trade detail view
- Close trade flow
- Trade editing and deletion
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.ext import ConversationHandler

from database.models import (
    Account,
    Strategy,
    Tag,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
    User,
)
from handlers.trades import (
    CLOSE_CONFIRM,
    CLOSE_ENTER_EXIT,
    CONFIRM,
    ENTER_ENTRY,
    ENTER_LOT,
    ENTER_NOTES,
    ENTER_SL,
    ENTER_TP,
    SELECT_ACCOUNT,
    SELECT_DIRECTION,
    SELECT_INSTRUMENT,
    SELECT_STRATEGY,
    SELECT_TAGS,
    TRADE_WIZARD_KEY,
    UPLOAD_SCREENSHOT,
    _build_trade_summary,
    build_wizard_progress,
    cancel_trade_wizard,
    close_trade_conversation,
    get_all_tags,
    get_user_accounts,
    get_user_strategies,
    handle_account_select,
    handle_close_confirm,
    handle_close_exit_price,
    handle_direction_select,
    handle_entry_price,
    handle_instrument_custom,
    handle_instrument_select,
    handle_lot_size,
    handle_notes,
    handle_notes_skip,
    handle_screenshot_skip,
    handle_sl_price,
    handle_sl_skip,
    handle_strategy_select,
    handle_tag_toggle,
    handle_tp_price,
    handle_tp_skip,
    handle_trade_confirm,
    handle_wizard_back,
    open_trades_keyboard,
    start_close_trade,
    start_trade_wizard,
    trade_detail_keyboard,
    trade_entry_conversation,
    trade_wizard_account_keyboard,
    trade_wizard_keyboard,
    edit_field_keyboard,
)


class TestTradeWizardKeyboards:
    """Tests for trade wizard keyboard functions."""

    def test_trade_wizard_keyboard_basic(self):
        """Test basic wizard keyboard without skip."""
        keyboard = trade_wizard_keyboard(include_skip=False)

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 1
        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "tw_back" in callbacks
        assert "tw_cancel" in callbacks
        assert "tw_skip" not in callbacks

    def test_trade_wizard_keyboard_with_skip(self):
        """Test wizard keyboard with skip button."""
        keyboard = trade_wizard_keyboard(include_skip=True)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "tw_skip" in callbacks
        assert "tw_back" in callbacks
        assert "tw_cancel" in callbacks

    def test_trade_wizard_account_keyboard(self):
        """Test account selection keyboard."""
        accounts = [(1, "Account 1"), (2, "Account 2")]
        keyboard = trade_wizard_account_keyboard(accounts)

        assert len(keyboard.inline_keyboard) == 3  # 2 accounts + cancel
        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "tw_acc_1" in callbacks
        assert "tw_acc_2" in callbacks
        assert "tw_cancel" in callbacks


class TestTradeDetailKeyboard:
    """Tests for trade detail keyboard function."""

    def test_trade_detail_keyboard_open_trade(self):
        """Test keyboard for open trade has all actions."""
        keyboard = trade_detail_keyboard(123, is_open=True)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "trade_close_123" in callbacks
        assert "trade_edit_123" in callbacks  # Links to edit menu
        assert "trade_delete_123" in callbacks
        assert "menu_open_trades" in callbacks

    def test_trade_detail_keyboard_closed_trade(self):
        """Test keyboard for closed trade has limited actions."""
        keyboard = trade_detail_keyboard(456, is_open=False)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "trade_close_456" not in callbacks
        assert "trade_edit_456" in callbacks  # Links to edit menu
        assert "trade_delete_456" in callbacks
        assert "menu_history" in callbacks


class TestEditFieldKeyboard:
    """Tests for edit field keyboard function."""

    def test_edit_field_keyboard_open_trade(self):
        """Test edit keyboard for open trade has all core fields."""
        keyboard = edit_field_keyboard(123, is_open=True)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        # Core trade fields
        assert "edit_field_instrument_123" in callbacks
        assert "edit_field_direction_123" in callbacks
        assert "edit_field_entry_123" in callbacks
        assert "edit_field_lotsize_123" in callbacks
        # SL/TP
        assert "trade_edit_sl_123" in callbacks
        assert "trade_edit_tp_123" in callbacks
        # Notes
        assert "trade_edit_notes_123" in callbacks
        # Exit price should NOT be present for open trades
        assert "edit_field_exit_123" not in callbacks
        # Back button
        assert "trade_detail_123" in callbacks

    def test_edit_field_keyboard_closed_trade(self):
        """Test edit keyboard for closed trade includes exit price."""
        keyboard = edit_field_keyboard(456, is_open=False)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        # Core trade fields
        assert "edit_field_instrument_456" in callbacks
        assert "edit_field_direction_456" in callbacks
        assert "edit_field_entry_456" in callbacks
        assert "edit_field_lotsize_456" in callbacks
        # Exit price should be present for closed trades
        assert "edit_field_exit_456" in callbacks
        # Back button
        assert "trade_detail_456" in callbacks


class TestOpenTradesKeyboard:
    """Tests for open trades keyboard function."""

    def test_open_trades_keyboard_with_trades(self):
        """Test keyboard with trades list."""
        trades = [
            (1, "DAX", "long", Decimal("15000"), "+5%"),
            (2, "NASDAQ", "short", Decimal("14500"), "-2%"),
        ]
        keyboard = open_trades_keyboard(trades)

        assert len(keyboard.inline_keyboard) >= 4  # 2 trades + filter + back
        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "trade_detail_1" in callbacks
        assert "trade_detail_2" in callbacks
        assert "open_trades_filter" in callbacks

    def test_open_trades_keyboard_with_filter(self):
        """Test keyboard shows clear filter when filtered."""
        trades = [(1, "DAX", "long", Decimal("15000"), "")]
        keyboard = open_trades_keyboard(trades, filter_account_id=5)

        callbacks = [
            btn.callback_data for row in keyboard.inline_keyboard for btn in row
        ]
        assert "open_trades_filter_clear" in callbacks


class TestBuildWizardProgress:
    """Tests for wizard progress builder."""

    def test_build_wizard_progress_step_1(self):
        """Test progress string for step 1."""
        result = build_wizard_progress(1, "Select Account")
        assert result == "Step 1/12: Select Account"

    def test_build_wizard_progress_step_12(self):
        """Test progress string for step 12."""
        result = build_wizard_progress(12, "Confirm Trade")
        assert result == "Step 12/12: Confirm Trade"


class TestBuildTradeSummary:
    """Tests for trade summary builder."""

    def test_build_trade_summary_full_data(self):
        """Test summary with all data filled."""
        wizard_data = {
            "instrument": "DAX",
            "direction": "LONG",
            "entry_price": Decimal("15000"),
            "sl_price": Decimal("14950"),
            "tp_price": Decimal("15100"),
            "lot_size": Decimal("1.0"),
            "strategy_id": 1,
            "selected_tags": {1, 2, 3},
            "notes": "Test note",
            "photo_file_id": "abc123",
        }

        summary = _build_trade_summary(wizard_data)

        assert "DAX" in summary
        assert "LONG" in summary
        assert "15000" in summary
        assert "14950" in summary
        assert "15100" in summary
        assert "3 selected" in summary
        assert "Yes" in summary  # notes and screenshot

    def test_build_trade_summary_minimal_data(self):
        """Test summary with minimal data."""
        wizard_data = {
            "instrument": "NASDAQ",
            "direction": "SHORT",
            "entry_price": Decimal("14500"),
            "lot_size": Decimal("0.5"),
        }

        summary = _build_trade_summary(wizard_data)

        assert "NASDAQ" in summary
        assert "SHORT" in summary
        assert "Not set" in summary  # SL and TP


class TestGetUserStrategies:
    """Tests for get_user_strategies function."""

    @pytest.mark.asyncio
    async def test_returns_strategies_for_user(
        self, session: AsyncSession, sample_user: User, sample_strategy: Strategy
    ):
        """Test that strategies are returned for user."""
        strategies = await get_user_strategies(session, sample_user.id)

        assert len(strategies) == 1
        assert strategies[0][1] == "Test Strategy"

    @pytest.mark.asyncio
    async def test_returns_empty_for_user_without_strategies(
        self, session: AsyncSession, sample_user: User
    ):
        """Test returns empty when user has no strategies."""
        # Create user without strategies
        new_user = User(telegram_id=999888777, username="nostrats")
        session.add(new_user)
        await session.flush()

        strategies = await get_user_strategies(session, new_user.id)

        assert strategies == []


class TestGetAllTags:
    """Tests for get_all_tags function."""

    @pytest.mark.asyncio
    async def test_returns_all_tags(self, session: AsyncSession, sample_tag: Tag):
        """Test that all tags are returned."""
        tags = await get_all_tags(session)

        assert len(tags) >= 1
        tag_names = [name for _, name in tags]
        assert "Test Tag" in tag_names


class TestGetUserAccounts:
    """Tests for get_user_accounts in trades module."""

    @pytest.mark.asyncio
    async def test_returns_active_accounts(
        self, session: AsyncSession, sample_user: User, sample_account: Account
    ):
        """Test that active accounts are returned."""
        accounts = await get_user_accounts(session, sample_user.id)

        assert len(accounts) == 1
        assert accounts[0][1] == "Test Account"

    @pytest.mark.asyncio
    async def test_excludes_inactive_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test that inactive accounts are excluded."""
        inactive = Account(
            user_id=sample_user.id,
            name="Inactive",
            broker="Broker",
            starting_balance=Decimal("1000"),
            current_balance=Decimal("1000"),
            currency="USD",
            is_active=False,
        )
        session.add(inactive)
        await session.flush()

        accounts = await get_user_accounts(session, sample_user.id)

        account_names = [name for _, name in accounts]
        assert "Inactive" not in account_names


class TestStartTradeWizard:
    """Tests for starting the trade wizard."""

    @pytest.mark.asyncio
    async def test_start_trade_wizard_no_accounts(self):
        """Test wizard start when user has no accounts."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456

        context = MagicMock()
        context.user_data = {}

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_user = MagicMock()
            mock_user.id = 1

            # First call: get_user_by_telegram_id
            # Second call: get_user_accounts
            mock_result1 = MagicMock()
            mock_result1.scalar_one_or_none = MagicMock(return_value=mock_user)

            mock_result2 = MagicMock()
            mock_result2.fetchall = MagicMock(return_value=[])

            mock_session.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

            result = await start_trade_wizard(update, context)

            assert result == ConversationHandler.END
            # Get the text from either positional args or kwargs
            call_args = update.callback_query.edit_message_text.call_args
            text = call_args.kwargs.get("text") or call_args[0][0]
            assert "need to create a trading account" in text


class TestHandleAccountSelect:
    """Tests for account selection handler."""

    @pytest.mark.asyncio
    async def test_account_select_stores_and_proceeds(self):
        """Test that account selection stores ID and proceeds."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "tw_acc_123"

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_account_select(update, context)

        assert result == SELECT_INSTRUMENT
        assert context.user_data[TRADE_WIZARD_KEY]["account_id"] == 123


class TestHandleInstrumentSelect:
    """Tests for instrument selection handler."""

    @pytest.mark.asyncio
    async def test_instrument_select_dax(self):
        """Test selecting DAX instrument."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "instrument_DAX"

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_instrument_select(update, context)

        assert result == SELECT_DIRECTION
        assert context.user_data[TRADE_WIZARD_KEY]["instrument"] == "DAX"

    @pytest.mark.asyncio
    async def test_instrument_custom_prompts_input(self):
        """Test custom instrument option."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "instrument_custom"

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_instrument_select(update, context)

        assert result == SELECT_INSTRUMENT  # Stay on same state for input


class TestHandleInstrumentCustom:
    """Tests for custom instrument text input."""

    @pytest.mark.asyncio
    async def test_valid_custom_instrument(self):
        """Test valid custom instrument input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "AAPL"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_instrument_custom(update, context)

        assert result == SELECT_DIRECTION
        assert context.user_data[TRADE_WIZARD_KEY]["instrument"] == "AAPL"

    @pytest.mark.asyncio
    async def test_invalid_custom_instrument(self):
        """Test invalid custom instrument (too short)."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "A"  # Too short
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_instrument_custom(update, context)

        assert result == SELECT_INSTRUMENT
        update.message.reply_text.assert_called_once()


class TestHandleDirectionSelect:
    """Tests for direction selection handler."""

    @pytest.mark.asyncio
    async def test_direction_select_long(self):
        """Test selecting LONG direction."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "direction_long"

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"instrument": "DAX", "step_history": []}
        }

        result = await handle_direction_select(update, context)

        assert result == ENTER_ENTRY
        assert context.user_data[TRADE_WIZARD_KEY]["direction"] == "LONG"

    @pytest.mark.asyncio
    async def test_direction_select_short(self):
        """Test selecting SHORT direction."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "direction_short"

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"instrument": "NASDAQ", "step_history": []}
        }

        result = await handle_direction_select(update, context)

        assert result == ENTER_ENTRY
        assert context.user_data[TRADE_WIZARD_KEY]["direction"] == "SHORT"


class TestHandleEntryPrice:
    """Tests for entry price handler."""

    @pytest.mark.asyncio
    async def test_valid_entry_price(self):
        """Test valid entry price input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "15000.50"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"direction": "LONG", "step_history": []}
        }

        result = await handle_entry_price(update, context)

        assert result == ENTER_SL
        assert context.user_data[TRADE_WIZARD_KEY]["entry_price"] == Decimal("15000.50")

    @pytest.mark.asyncio
    async def test_invalid_entry_price(self):
        """Test invalid entry price input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "not a number"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_entry_price(update, context)

        assert result == ENTER_ENTRY


class TestHandleSLPrice:
    """Tests for stop-loss price handler."""

    @pytest.mark.asyncio
    async def test_valid_sl_for_long(self):
        """Test valid SL below entry for LONG."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "14900"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "entry_price": Decimal("15000"),
                "direction": "LONG",
                "step_history": [],
            }
        }

        result = await handle_sl_price(update, context)

        assert result == ENTER_TP
        assert context.user_data[TRADE_WIZARD_KEY]["sl_price"] == Decimal("14900")

    @pytest.mark.asyncio
    async def test_invalid_sl_for_long(self):
        """Test invalid SL above entry for LONG."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "15100"  # Above entry
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "entry_price": Decimal("15000"),
                "direction": "LONG",
                "step_history": [],
            }
        }

        result = await handle_sl_price(update, context)

        assert result == ENTER_SL  # Stay on same step

    @pytest.mark.asyncio
    async def test_sl_skip(self):
        """Test skipping SL entry."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "entry_price": Decimal("15000"),
                "direction": "LONG",
                "step_history": [],
            }
        }

        result = await handle_sl_skip(update, context)

        assert result == ENTER_TP
        assert context.user_data[TRADE_WIZARD_KEY]["sl_price"] is None


class TestHandleTPPrice:
    """Tests for take-profit price handler."""

    @pytest.mark.asyncio
    async def test_valid_tp_for_long(self):
        """Test valid TP above entry for LONG."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "15200"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "entry_price": Decimal("15000"),
                "direction": "LONG",
                "sl_price": Decimal("14900"),
                "step_history": [],
            }
        }

        result = await handle_tp_price(update, context)

        assert result == ENTER_LOT
        assert context.user_data[TRADE_WIZARD_KEY]["tp_price"] == Decimal("15200")

    @pytest.mark.asyncio
    async def test_tp_skip(self):
        """Test skipping TP entry."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "entry_price": Decimal("15000"),
                "direction": "LONG",
                "sl_price": Decimal("14900"),
                "step_history": [],
            }
        }

        result = await handle_tp_skip(update, context)

        assert result == ENTER_LOT
        assert context.user_data[TRADE_WIZARD_KEY]["tp_price"] is None


class TestHandleLotSize:
    """Tests for lot size handler."""

    @pytest.mark.asyncio
    async def test_valid_lot_size(self):
        """Test valid lot size input."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "0.5"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_user = MagicMock()
            mock_user.id = 1
            mock_result1 = MagicMock()
            mock_result1.scalar_one_or_none = MagicMock(return_value=mock_user)

            mock_result2 = MagicMock()
            mock_result2.fetchall = MagicMock(return_value=[(1, "Test Strategy")])

            mock_session.execute = AsyncMock(side_effect=[mock_result1, mock_result2])

            result = await handle_lot_size(update, context)

        assert result == SELECT_STRATEGY
        assert context.user_data[TRADE_WIZARD_KEY]["lot_size"] == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_invalid_lot_size_too_small(self):
        """Test lot size below minimum."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "0.001"  # Below minimum
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_lot_size(update, context)

        assert result == ENTER_LOT


class TestHandleStrategySelect:
    """Tests for strategy selection handler."""

    @pytest.mark.asyncio
    async def test_strategy_select(self):
        """Test selecting a strategy."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "strategy_select_5"

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[])
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await handle_strategy_select(update, context)

        assert result == SELECT_TAGS
        assert context.user_data[TRADE_WIZARD_KEY]["strategy_id"] == 5

    @pytest.mark.asyncio
    async def test_strategy_skip(self):
        """Test skipping strategy selection."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "strategy_skip"

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[])
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await handle_strategy_select(update, context)

        assert result == SELECT_TAGS
        assert context.user_data[TRADE_WIZARD_KEY]["strategy_id"] is None


class TestHandleTagToggle:
    """Tests for tag toggle handler."""

    @pytest.mark.asyncio
    async def test_tag_toggle_add(self):
        """Test adding a tag via toggle."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "tag_toggle_3"

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"selected_tags": set(), "step_history": []}
        }

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[(3, "Test Tag")])
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await handle_tag_toggle(update, context)

        assert result == SELECT_TAGS
        assert 3 in context.user_data[TRADE_WIZARD_KEY]["selected_tags"]

    @pytest.mark.asyncio
    async def test_tag_toggle_remove(self):
        """Test removing a tag via toggle."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "tag_toggle_3"

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"selected_tags": {3}, "step_history": []}
        }

        with patch("handlers.trades.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.fetchall = MagicMock(return_value=[(3, "Test Tag")])
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await handle_tag_toggle(update, context)

        assert result == SELECT_TAGS
        assert 3 not in context.user_data[TRADE_WIZARD_KEY]["selected_tags"]

    @pytest.mark.asyncio
    async def test_tags_done(self):
        """Test completing tag selection."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.data = "tags_done"

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {"selected_tags": {1, 2}, "step_history": []}
        }

        result = await handle_tag_toggle(update, context)

        assert result == ENTER_NOTES


class TestHandleNotes:
    """Tests for notes handler."""

    @pytest.mark.asyncio
    async def test_notes_input(self):
        """Test entering notes."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "This is a test trade note"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_notes(update, context)

        assert result == UPLOAD_SCREENSHOT
        assert context.user_data[TRADE_WIZARD_KEY]["notes"] == "This is a test trade note"

    @pytest.mark.asyncio
    async def test_notes_skip(self):
        """Test skipping notes."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {TRADE_WIZARD_KEY: {"step_history": []}}

        result = await handle_notes_skip(update, context)

        assert result == UPLOAD_SCREENSHOT
        assert context.user_data[TRADE_WIZARD_KEY]["notes"] is None


class TestHandleScreenshotSkip:
    """Tests for screenshot skip handler."""

    @pytest.mark.asyncio
    async def test_screenshot_skip_proceeds_to_confirm(self):
        """Test that skipping screenshot goes to confirm."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "instrument": "DAX",
                "direction": "LONG",
                "entry_price": Decimal("15000"),
                "lot_size": Decimal("1"),
                "step_history": [],
            }
        }

        result = await handle_screenshot_skip(update, context)

        assert result == CONFIRM
        assert context.user_data[TRADE_WIZARD_KEY]["photo_file_id"] is None


class TestCancelTradeWizard:
    """Tests for cancelling the trade wizard."""

    @pytest.mark.asyncio
    async def test_cancel_clears_wizard_data(self):
        """Test that cancel clears wizard data."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.message = None

        context = MagicMock()
        context.user_data = {
            TRADE_WIZARD_KEY: {
                "instrument": "DAX",
                "direction": "LONG",
            }
        }

        result = await cancel_trade_wizard(update, context)

        assert result == ConversationHandler.END
        assert TRADE_WIZARD_KEY not in context.user_data


class TestCloseTradeFlow:
    """Tests for close trade flow."""

    @pytest.mark.asyncio
    async def test_close_exit_price_calculates_pnl(self):
        """Test that exit price input calculates P&L."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "15100"
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {
            "close_wizard": {
                "trade_id": 1,
                "entry_price": Decimal("15000"),
                "direction": "long",
                "lot_size": Decimal("1"),
                "account_id": 1,
                "currency": "USD",
            }
        }

        result = await handle_close_exit_price(update, context)

        assert result == CLOSE_CONFIRM
        assert context.user_data["close_wizard"]["exit_price"] == Decimal("15100")
        assert context.user_data["close_wizard"]["pnl"] == Decimal("100")


class TestConversationHandlers:
    """Tests for conversation handler configurations."""

    def test_trade_entry_conversation_has_all_states(self):
        """Test that trade entry handler has all 12 states."""
        states = trade_entry_conversation.states

        assert SELECT_ACCOUNT in states
        assert SELECT_INSTRUMENT in states
        assert SELECT_DIRECTION in states
        assert ENTER_ENTRY in states
        assert ENTER_SL in states
        assert ENTER_TP in states
        assert ENTER_LOT in states
        assert SELECT_STRATEGY in states
        assert SELECT_TAGS in states
        assert ENTER_NOTES in states
        assert UPLOAD_SCREENSHOT in states
        assert CONFIRM in states

    def test_trade_entry_conversation_has_entry_points(self):
        """Test that trade entry handler has entry points."""
        assert len(trade_entry_conversation.entry_points) > 0

    def test_trade_entry_conversation_has_fallbacks(self):
        """Test that trade entry handler has fallbacks."""
        assert len(trade_entry_conversation.fallbacks) > 0

    def test_close_trade_conversation_has_states(self):
        """Test that close trade handler has required states."""
        states = close_trade_conversation.states

        assert CLOSE_ENTER_EXIT in states
        assert CLOSE_CONFIRM in states

    def test_close_trade_conversation_has_entry_points(self):
        """Test that close trade handler has entry points."""
        assert len(close_trade_conversation.entry_points) > 0
