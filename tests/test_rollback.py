"""
Tests for the Rollback Handlers.

Tests cover:
- Rollback menu keyboard structure
- Rollback confirm keyboard structure
- Handler functions for rollback flow
- Current stats calculation
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import DataSnapshot
from handlers.rollback import (
    CONFIRMING_RESTORE,
    ROLLBACK_KEY,
    SELECTING_SNAPSHOT,
    get_current_stats,
    handle_rollback_cancel,
    handle_rollback_confirm,
    handle_rollback_menu,
    handle_rollback_select,
    rollback_confirm_keyboard,
    rollback_menu_keyboard,
)


class TestRollbackMenuKeyboard:
    """Tests for rollback_menu_keyboard function."""

    def test_rollback_menu_keyboard_with_snapshots(self):
        """Test keyboard generation with available snapshots."""
        mock_snapshot1 = MagicMock(spec=DataSnapshot)
        mock_snapshot1.id = 1
        mock_snapshot1.snapshot_date = date(2026, 2, 4)
        mock_snapshot1.snapshot_data = {
            "accounts": [{"id": 1}],
            "trades": [{"id": 1}, {"id": 2}],
            "transactions": [],
        }

        mock_snapshot2 = MagicMock(spec=DataSnapshot)
        mock_snapshot2.id = 2
        mock_snapshot2.snapshot_date = date(2026, 2, 3)
        mock_snapshot2.snapshot_data = {
            "accounts": [{"id": 1}, {"id": 2}],
            "trades": [],
            "transactions": [],
        }

        with patch(
            "handlers.rollback.get_snapshot_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_snapshot_stats.side_effect = [
                {"num_accounts": 1, "num_trades": 2, "num_transactions": 0},
                {"num_accounts": 2, "num_trades": 0, "num_transactions": 0},
            ]
            mock_get_service.return_value = mock_service

            keyboard = rollback_menu_keyboard([mock_snapshot1, mock_snapshot2])

        assert isinstance(keyboard, InlineKeyboardMarkup)
        # Should have 2 snapshot buttons + 1 back button
        assert len(keyboard.inline_keyboard) == 3

        # First button should be for snapshot 1
        assert "Feb 04, 2026" in keyboard.inline_keyboard[0][0].text
        assert "2 trades" in keyboard.inline_keyboard[0][0].text
        assert "1 accounts" in keyboard.inline_keyboard[0][0].text
        assert keyboard.inline_keyboard[0][0].callback_data == "rollback_select_1"

        # Second button should be for snapshot 2
        assert "Feb 03, 2026" in keyboard.inline_keyboard[1][0].text
        assert keyboard.inline_keyboard[1][0].callback_data == "rollback_select_2"

        # Last button should be back to menu
        assert keyboard.inline_keyboard[2][0].text == "Back to Menu"
        assert keyboard.inline_keyboard[2][0].callback_data == "menu_main"

    def test_rollback_menu_keyboard_with_no_snapshots(self):
        """Test keyboard generation with no available snapshots."""
        keyboard = rollback_menu_keyboard([])

        assert isinstance(keyboard, InlineKeyboardMarkup)
        # Should have 1 "no snapshots" button + 1 back button
        assert len(keyboard.inline_keyboard) == 2

        # First button should indicate no snapshots
        assert "No snapshots available" in keyboard.inline_keyboard[0][0].text
        assert keyboard.inline_keyboard[0][0].callback_data == "rollback_noop"

        # Last button should be back to menu
        assert keyboard.inline_keyboard[1][0].text == "Back to Menu"

    def test_rollback_menu_keyboard_callback_data_format(self):
        """Test callback data follows expected format."""
        mock_snapshot = MagicMock(spec=DataSnapshot)
        mock_snapshot.id = 42
        mock_snapshot.snapshot_date = date(2026, 2, 5)
        mock_snapshot.snapshot_data = {
            "accounts": [],
            "trades": [],
            "transactions": [],
        }

        with patch(
            "handlers.rollback.get_snapshot_service"
        ) as mock_get_service:
            mock_service = MagicMock()
            mock_service.get_snapshot_stats.return_value = {
                "num_accounts": 0,
                "num_trades": 0,
                "num_transactions": 0,
            }
            mock_get_service.return_value = mock_service

            keyboard = rollback_menu_keyboard([mock_snapshot])

        # Callback data should match pattern "rollback_select_{id}"
        assert keyboard.inline_keyboard[0][0].callback_data == "rollback_select_42"


class TestRollbackConfirmKeyboard:
    """Tests for rollback_confirm_keyboard function."""

    def test_rollback_confirm_keyboard_structure(self):
        """Test confirm keyboard has correct structure."""
        keyboard = rollback_confirm_keyboard(snapshot_id=1)

        assert isinstance(keyboard, InlineKeyboardMarkup)
        # Should have 1 row with 2 buttons
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_rollback_confirm_keyboard_confirm_button(self):
        """Test confirm button has correct text and callback."""
        keyboard = rollback_confirm_keyboard(snapshot_id=5)

        confirm_button = keyboard.inline_keyboard[0][0]
        assert confirm_button.text == "Confirm Restore"
        assert confirm_button.callback_data == "rollback_confirm_5"

    def test_rollback_confirm_keyboard_cancel_button(self):
        """Test cancel button has correct text and callback."""
        keyboard = rollback_confirm_keyboard(snapshot_id=5)

        cancel_button = keyboard.inline_keyboard[0][1]
        assert cancel_button.text == "Cancel"
        assert cancel_button.callback_data == "rollback_cancel"

    def test_rollback_confirm_keyboard_with_different_ids(self):
        """Test confirm keyboard works with different snapshot IDs."""
        for snapshot_id in [1, 10, 100, 999]:
            keyboard = rollback_confirm_keyboard(snapshot_id=snapshot_id)
            confirm_button = keyboard.inline_keyboard[0][0]
            assert confirm_button.callback_data == f"rollback_confirm_{snapshot_id}"


class TestGetCurrentStats:
    """Tests for get_current_stats function."""

    @pytest.mark.asyncio
    async def test_get_current_stats_with_data(self):
        """Test getting stats when user has accounts and trades."""
        mock_session = AsyncMock()

        # Setup mock for accounts count
        accounts_result = MagicMock()
        accounts_result.scalar.return_value = 2

        # Setup mock for account IDs
        account_ids_result = MagicMock()
        account_ids_result.fetchall.return_value = [(1,), (2,)]

        # Setup mock for trades count
        trades_result = MagicMock()
        trades_result.scalar.return_value = 5

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return accounts_result
            elif call_count == 2:
                return account_ids_result
            else:
                return trades_result

        mock_session.execute = mock_execute

        stats = await get_current_stats(mock_session, user_id=1)

        assert stats["num_accounts"] == 2
        assert stats["num_trades"] == 5

    @pytest.mark.asyncio
    async def test_get_current_stats_with_no_accounts(self):
        """Test getting stats when user has no accounts."""
        mock_session = AsyncMock()

        # Setup mock for accounts count
        accounts_result = MagicMock()
        accounts_result.scalar.return_value = 0

        # Setup mock for account IDs
        account_ids_result = MagicMock()
        account_ids_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return accounts_result
            else:
                return account_ids_result

        mock_session.execute = mock_execute

        stats = await get_current_stats(mock_session, user_id=1)

        assert stats["num_accounts"] == 0
        assert stats["num_trades"] == 0

    @pytest.mark.asyncio
    async def test_get_current_stats_with_none_values(self):
        """Test getting stats handles None values gracefully."""
        mock_session = AsyncMock()

        # Setup mock for accounts count returning None
        accounts_result = MagicMock()
        accounts_result.scalar.return_value = None

        # Setup mock for account IDs
        account_ids_result = MagicMock()
        account_ids_result.fetchall.return_value = []

        call_count = 0

        async def mock_execute(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return accounts_result
            else:
                return account_ids_result

        mock_session.execute = mock_execute

        stats = await get_current_stats(mock_session, user_id=1)

        assert stats["num_accounts"] == 0
        assert stats["num_trades"] == 0


class TestHandleRollbackMenu:
    """Tests for handle_rollback_menu handler."""

    @pytest.mark.asyncio
    async def test_handle_rollback_menu_no_query(self):
        """Test handler returns END when no callback query."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_context = MagicMock()

        from telegram.ext import ConversationHandler

        result = await handle_rollback_menu(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_handle_rollback_menu_no_user(self):
        """Test handler returns END when no effective user."""
        mock_update = MagicMock()
        mock_update.callback_query = MagicMock()
        mock_update.effective_user = None
        mock_context = MagicMock()

        from telegram.ext import ConversationHandler

        result = await handle_rollback_menu(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_handle_rollback_menu_user_not_found(self):
        """Test handler returns END when user not found in database."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 12345
        mock_context = MagicMock()

        with patch("handlers.rollback.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch(
                "handlers.rollback.get_user_by_telegram_id",
                new_callable=AsyncMock,
            ) as mock_get_user:
                mock_get_user.return_value = None

                from telegram.ext import ConversationHandler

                result = await handle_rollback_menu(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_query.edit_message_text.assert_called()


class TestHandleRollbackCancel:
    """Tests for handle_rollback_cancel handler."""

    @pytest.mark.asyncio
    async def test_handle_rollback_cancel_with_query(self):
        """Test cancel handler edits message and clears context."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_update.callback_query = mock_query
        mock_context = MagicMock()
        mock_context.user_data = {ROLLBACK_KEY: {"user_id": 1}}

        from telegram.ext import ConversationHandler

        result = await handle_rollback_cancel(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_query.answer.assert_called()
        mock_query.edit_message_text.assert_called()
        assert ROLLBACK_KEY not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_handle_rollback_cancel_without_query(self):
        """Test cancel handler handles missing query gracefully."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_context = MagicMock()
        mock_context.user_data = {ROLLBACK_KEY: {"user_id": 1}}

        from telegram.ext import ConversationHandler

        result = await handle_rollback_cancel(mock_update, mock_context)

        assert result == ConversationHandler.END
        assert ROLLBACK_KEY not in mock_context.user_data


class TestHandleRollbackSelect:
    """Tests for handle_rollback_select handler."""

    @pytest.mark.asyncio
    async def test_handle_rollback_select_noop(self):
        """Test select handler handles noop callback."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_query.data = "rollback_noop"
        mock_update.callback_query = mock_query
        mock_update.effective_user = MagicMock()
        mock_context = MagicMock()

        result = await handle_rollback_select(mock_update, mock_context)

        assert result == SELECTING_SNAPSHOT

    @pytest.mark.asyncio
    async def test_handle_rollback_select_invalid_id(self):
        """Test select handler handles invalid snapshot ID."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_query.data = "rollback_select_invalid"
        mock_update.callback_query = mock_query
        mock_update.effective_user = MagicMock()
        mock_context = MagicMock()

        result = await handle_rollback_select(mock_update, mock_context)

        assert result == SELECTING_SNAPSHOT

    @pytest.mark.asyncio
    async def test_handle_rollback_select_no_query(self):
        """Test select handler returns END when no callback query."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_context = MagicMock()

        from telegram.ext import ConversationHandler

        result = await handle_rollback_select(mock_update, mock_context)

        assert result == ConversationHandler.END


class TestHandleRollbackConfirm:
    """Tests for handle_rollback_confirm handler."""

    @pytest.mark.asyncio
    async def test_handle_rollback_confirm_no_query(self):
        """Test confirm handler returns END when no callback query."""
        mock_update = MagicMock()
        mock_update.callback_query = None
        mock_context = MagicMock()

        from telegram.ext import ConversationHandler

        result = await handle_rollback_confirm(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_handle_rollback_confirm_invalid_id(self):
        """Test confirm handler handles invalid snapshot ID."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_query.data = "rollback_confirm_invalid"
        mock_update.callback_query = mock_query
        mock_update.effective_user = MagicMock()
        mock_context = MagicMock()

        from telegram.ext import ConversationHandler

        result = await handle_rollback_confirm(mock_update, mock_context)

        assert result == ConversationHandler.END

    @pytest.mark.asyncio
    async def test_handle_rollback_confirm_no_user_id_in_context(self):
        """Test confirm handler handles missing user_id in context."""
        mock_update = MagicMock()
        mock_query = AsyncMock()
        mock_query.data = "rollback_confirm_1"
        mock_update.callback_query = mock_query
        mock_update.effective_user = MagicMock()
        mock_update.effective_user.id = 12345
        mock_context = MagicMock()
        mock_context.user_data = {}

        with patch("handlers.rollback.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch(
                "handlers.rollback.get_user_by_telegram_id",
                new_callable=AsyncMock,
            ) as mock_get_user:
                mock_get_user.return_value = None

                from telegram.ext import ConversationHandler

                result = await handle_rollback_confirm(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_query.edit_message_text.assert_called()


class TestConversationStates:
    """Tests for conversation state constants."""

    def test_selecting_snapshot_state(self):
        """Test SELECTING_SNAPSHOT state constant exists."""
        assert SELECTING_SNAPSHOT == 0

    def test_confirming_restore_state(self):
        """Test CONFIRMING_RESTORE state constant exists."""
        assert CONFIRMING_RESTORE == 1

    def test_rollback_key_constant(self):
        """Test ROLLBACK_KEY context key constant exists."""
        assert ROLLBACK_KEY == "rollback_wizard"
