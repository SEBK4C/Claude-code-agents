"""
Tests for the main entry point and error handling.

This module tests:
- Application initialization
- Error handler behavior
- Directory creation
- Handler registration
"""

import os
import traceback
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update

from main import (
    ensure_directories,
    error_handler,
    handle_unknown_callback,
    handle_unified_text_message,
    handle_unified_photo_message,
    register_handlers,
    return_to_menu_keyboard,
)


class TestReturnToMenuKeyboard:
    """Tests for return_to_menu_keyboard function."""

    def test_returns_valid_keyboard(self):
        """Test that a valid keyboard is returned."""
        keyboard = return_to_menu_keyboard()

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 1
        assert len(keyboard.inline_keyboard[0]) == 1

    def test_keyboard_has_return_button(self):
        """Test that keyboard has return to menu button."""
        keyboard = return_to_menu_keyboard()

        button = keyboard.inline_keyboard[0][0]
        assert button.text == "Return to Menu"
        assert button.callback_data == "menu_home"


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_screenshots_directory(self, tmp_path):
        """Test that screenshots directory is created."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ensure_directories()
            assert (tmp_path / "screenshots").exists()
        finally:
            os.chdir(original_cwd)

    def test_creates_exports_directory(self, tmp_path):
        """Test that exports directory is created."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            ensure_directories()
            assert (tmp_path / "exports").exists()
        finally:
            os.chdir(original_cwd)

    def test_handles_existing_directories(self, tmp_path):
        """Test that existing directories don't cause errors."""
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            (tmp_path / "screenshots").mkdir()
            (tmp_path / "exports").mkdir()

            ensure_directories()

            assert (tmp_path / "screenshots").exists()
            assert (tmp_path / "exports").exists()
        finally:
            os.chdir(original_cwd)


class TestErrorHandler:
    """Tests for error_handler function.

    IMPORTANT: The error handler is now SILENT - it only logs errors and does NOT
    send any message to the user. This prevents error messages from interfering
    with normal bot operation.
    """

    @pytest.mark.asyncio
    async def test_silent_error_handler_does_not_message_user(self):
        """Test that error handler does NOT send any message to user (silent mode)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()
        update.effective_chat = MagicMock()
        update.effective_chat.id = 123456

        context = MagicMock()
        context.error = ValueError("Test error")
        context.bot = MagicMock()
        context.bot.send_message = AsyncMock()

        with patch("main.logger", MagicMock()):
            await error_handler(update, context)

        # Verify NO user-facing methods were called (silent mode)
        update.callback_query.answer.assert_not_called()
        update.callback_query.edit_message_text.assert_not_called()
        update.message.reply_text.assert_not_called()
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_update(self):
        """Test error handling when update is None."""
        context = MagicMock()
        context.error = Exception("Test error")

        with patch("main.logger", MagicMock()):
            await error_handler(None, context)

    @pytest.mark.asyncio
    async def test_logs_exception_details(self):
        """Test that error details are logged."""
        update = MagicMock(spec=Update)
        update.callback_query = None
        update.message = MagicMock()
        update.effective_chat = None

        context = MagicMock()
        test_error = ValueError("Specific test error")
        context.error = test_error

        mock_logger = MagicMock()
        with patch("main.logger", mock_logger):
            await error_handler(update, context)

        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args.kwargs
        assert call_kwargs["error_type"] == "ValueError"
        assert "Specific test error" in call_kwargs["error_message"]

    @pytest.mark.asyncio
    async def test_logs_even_without_update(self):
        """Test that errors are logged even when update is None."""
        context = MagicMock()
        context.error = RuntimeError("Background task error")

        mock_logger = MagicMock()
        with patch("main.logger", mock_logger):
            await error_handler(None, context)

        mock_logger.error.assert_called_once()
        call_kwargs = mock_logger.error.call_args.kwargs
        assert call_kwargs["error_type"] == "RuntimeError"


class TestHandleUnknownCallback:
    """Tests for handle_unknown_callback handler."""

    @pytest.mark.asyncio
    async def test_answers_unknown_callback(self):
        """Test that unknown callbacks are answered appropriately."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()

        context = MagicMock()

        await handle_unknown_callback(update, context)

        update.callback_query.answer.assert_called_once_with(
            "This feature is not yet implemented."
        )


class TestHandleUnifiedTextMessage:
    """Tests for handle_unified_text_message handler.

    This is the SINGLE text message handler that routes based on context.user_data state.
    """

    @pytest.mark.asyncio
    async def test_returns_early_if_no_message(self):
        """Test that handler returns early if update has no message."""
        update = MagicMock()
        update.message = None

        context = MagicMock()
        context.user_data = {}

        # Should return without error
        await handle_unified_text_message(update, context)

    @pytest.mark.asyncio
    async def test_returns_early_if_no_text(self):
        """Test that handler returns early if message has no text."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = None

        context = MagicMock()
        context.user_data = {}

        # Should return without error
        await handle_unified_text_message(update, context)

    @pytest.mark.asyncio
    async def test_silent_fallback_when_no_state(self):
        """Test that handler is silent when no state is active.

        When no state keys are present and natural trade parsing fails,
        the handler should do nothing (no "I didn't understand" message).
        """
        update = MagicMock()
        update.message = MagicMock()
        update.message.text = "hello world"
        update.message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345

        context = MagicMock()
        context.user_data = {}

        with patch("main.handle_natural_trade_input", new_callable=AsyncMock) as mock_natural:
            mock_natural.return_value = False  # Parsing failed
            await handle_unified_text_message(update, context)

        # Verify no reply was sent (silent fallback)
        update.message.reply_text.assert_not_called()


class TestHandleUnifiedPhotoMessage:
    """Tests for handle_unified_photo_message handler."""

    @pytest.mark.asyncio
    async def test_returns_early_if_no_message(self):
        """Test that handler returns early if update has no message."""
        update = MagicMock()
        update.message = None

        context = MagicMock()
        context.user_data = {}

        # Should return without error
        await handle_unified_photo_message(update, context)

    @pytest.mark.asyncio
    async def test_returns_early_if_no_photo(self):
        """Test that handler returns early if message has no photo."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.photo = None

        context = MagicMock()
        context.user_data = {}

        # Should return without error
        await handle_unified_photo_message(update, context)

    @pytest.mark.asyncio
    async def test_silent_fallback_when_not_in_screenshot_upload_state(self):
        """Test that handler ignores photos when not in screenshot upload state."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.photo = [MagicMock()]  # Has photo
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.user_data = {}  # No edit_wizard state

        await handle_unified_photo_message(update, context)

        # Verify no reply was sent (silent fallback)
        update.message.reply_text.assert_not_called()


class TestRegisterHandlers:
    """Tests for register_handlers function."""

    def test_registers_command_handlers(self):
        """Test that command handlers are registered."""
        application = MagicMock()
        application.add_handler = MagicMock()
        application.add_error_handler = MagicMock()

        register_handlers(application)

        assert application.add_handler.call_count >= 4

    def test_registers_error_handler(self):
        """Test that error handler is registered."""
        application = MagicMock()
        application.add_handler = MagicMock()
        application.add_error_handler = MagicMock()

        register_handlers(application)

        application.add_error_handler.assert_called_once_with(error_handler)

    def test_registers_conversation_handler_first(self):
        """Test that conversation handlers are registered before others."""
        application = MagicMock()
        application.add_handler = MagicMock()
        application.add_error_handler = MagicMock()

        register_handlers(application)

        first_call = application.add_handler.call_args_list[0]
        handler = first_call[0][0]

        from telegram.ext import ConversationHandler
        assert isinstance(handler, ConversationHandler)


class TestMainFunction:
    """Tests for the main entry point."""

    def test_main_validates_config(self):
        """Test that main validates configuration."""
        mock_config = MagicMock()
        mock_config.validate.return_value = ["TELEGRAM_BOT_TOKEN is required"]
        mock_config.telegram.token = ""

        with patch("main.get_config", return_value=mock_config):
            with patch("main.configure_logging"):
                with patch("main.get_logger") as mock_get_logger:
                    mock_get_logger.return_value = MagicMock()
                    with pytest.raises(SystemExit) as exc_info:
                        from main import main
                        main()

                    assert exc_info.value.code == 1


class TestApplicationLifecycle:
    """Tests for application startup and shutdown hooks."""

    @pytest.mark.asyncio
    async def test_on_startup_initializes_database(self):
        """Test that on_startup calls init_db."""
        from main import on_startup

        application = MagicMock()

        with patch("main.init_db", new_callable=AsyncMock) as mock_init_db:
            with patch("main.ensure_directories"):
                with patch("main.get_logger") as mock_get_logger:
                    mock_get_logger.return_value = MagicMock()
                    await on_startup(application)

        mock_init_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_shutdown_closes_database(self):
        """Test that on_shutdown calls close_db."""
        from main import on_shutdown

        application = MagicMock()

        with patch("main.close_db", new_callable=AsyncMock) as mock_close_db:
            with patch("main.logger", MagicMock()):
                await on_shutdown(application)

        mock_close_db.assert_called_once()
