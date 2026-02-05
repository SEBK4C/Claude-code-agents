"""
Tests for the start command and main dashboard handlers.

This module tests:
- /start command behavior
- /help command behavior
- Dashboard display with account summary
- First-time user handling
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Account, Trade, TradeDirection, TradeStatus, User
from handlers.start import (
    HELP_MESSAGE,
    WELCOME_MESSAGE,
    build_dashboard_message,
    get_account_summary,
    get_or_create_user,
    handle_help_callback,
    handle_menu_home,
    help_command,
    start_command,
)


class TestGetOrCreateUser:
    """Tests for get_or_create_user function."""

    @pytest_asyncio.fixture
    async def setup_session(self, session: AsyncSession):
        """Setup fixture providing a clean session."""
        return session

    @pytest.mark.asyncio
    async def test_creates_new_user(self, setup_session: AsyncSession):
        """Test that a new user is created when not found."""
        user = await get_or_create_user(setup_session, telegram_id=999999, username="newuser")

        assert user is not None
        assert user.telegram_id == 999999
        assert user.username == "newuser"
        assert user.id is not None

    @pytest.mark.asyncio
    async def test_returns_existing_user(self, setup_session: AsyncSession, sample_user: User):
        """Test that existing user is returned without creating duplicate."""
        user = await get_or_create_user(
            setup_session,
            telegram_id=sample_user.telegram_id,
            username=sample_user.username,
        )

        assert user.id == sample_user.id
        assert user.telegram_id == sample_user.telegram_id

    @pytest.mark.asyncio
    async def test_updates_username_if_changed(self, setup_session: AsyncSession, sample_user: User):
        """Test that username is updated when it changes."""
        new_username = "updated_username"
        user = await get_or_create_user(
            setup_session,
            telegram_id=sample_user.telegram_id,
            username=new_username,
        )

        assert user.id == sample_user.id
        assert user.username == new_username


class TestGetAccountSummary:
    """Tests for get_account_summary function."""

    @pytest.mark.asyncio
    async def test_returns_zero_for_user_without_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test summary for user with no accounts."""
        total_balance, open_trades = await get_account_summary(session, sample_user.id)

        assert total_balance == Decimal("0.00")
        assert open_trades == 0

    @pytest.mark.asyncio
    async def test_calculates_total_balance(
        self, session: AsyncSession, sample_user: User
    ):
        """Test total balance calculation across multiple accounts."""
        account1 = Account(
            user_id=sample_user.id,
            name="Account 1",
            broker="Broker 1",
            starting_balance=Decimal("5000.00"),
            current_balance=Decimal("5500.00"),
            currency="USD",
            is_active=True,
        )
        account2 = Account(
            user_id=sample_user.id,
            name="Account 2",
            broker="Broker 2",
            starting_balance=Decimal("3000.00"),
            current_balance=Decimal("3200.00"),
            currency="USD",
            is_active=True,
        )
        session.add(account1)
        session.add(account2)
        await session.flush()

        total_balance, open_trades = await get_account_summary(session, sample_user.id)

        assert total_balance == Decimal("8700.00")

    @pytest.mark.asyncio
    async def test_counts_open_trades(
        self, session: AsyncSession, sample_user: User, sample_account: Account
    ):
        """Test open trade counting."""
        trade1 = Trade(
            account_id=sample_account.id,
            instrument="EURUSD",
            direction=TradeDirection.LONG,
            entry_price=Decimal("1.1000"),
            lot_size=Decimal("0.1"),
            status=TradeStatus.OPEN,
        )
        trade2 = Trade(
            account_id=sample_account.id,
            instrument="GBPUSD",
            direction=TradeDirection.SHORT,
            entry_price=Decimal("1.2500"),
            lot_size=Decimal("0.2"),
            status=TradeStatus.OPEN,
        )
        trade3 = Trade(
            account_id=sample_account.id,
            instrument="USDJPY",
            direction=TradeDirection.LONG,
            entry_price=Decimal("150.00"),
            lot_size=Decimal("0.1"),
            status=TradeStatus.CLOSED,
        )
        session.add_all([trade1, trade2, trade3])
        await session.flush()

        total_balance, open_trades = await get_account_summary(session, sample_user.id)

        assert open_trades == 2

    @pytest.mark.asyncio
    async def test_excludes_inactive_accounts(
        self, session: AsyncSession, sample_user: User
    ):
        """Test that inactive accounts are excluded from summary."""
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

        total_balance, _ = await get_account_summary(session, sample_user.id)

        assert total_balance == Decimal("1000.00")


class TestBuildDashboardMessage:
    """Tests for build_dashboard_message function."""

    def test_returns_welcome_for_new_user(self):
        """Test that new users see welcome message."""
        message = build_dashboard_message(
            total_balance=Decimal("0"),
            open_trade_count=0,
            is_new_user=True,
        )

        assert message == WELCOME_MESSAGE

    def test_includes_balance_for_existing_user(self):
        """Test that existing users see their balance."""
        message = build_dashboard_message(
            total_balance=Decimal("10000.00"),
            open_trade_count=3,
            is_new_user=False,
        )

        assert "Trade Journal Dashboard" in message
        assert "$10,000.00" in message
        assert "Open Trades: 3" in message

    def test_handles_zero_balance(self):
        """Test dashboard with zero balance."""
        message = build_dashboard_message(
            total_balance=Decimal("0"),
            open_trade_count=0,
            is_new_user=False,
        )

        assert "$0.00" in message
        assert "Open Trades: 0" in message


class TestStartCommand:
    """Tests for start_command handler."""

    @pytest.mark.asyncio
    async def test_start_command_creates_user_and_shows_dashboard(self):
        """Test that /start creates user and displays dashboard."""
        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456789
        update.effective_user.username = "testuser"
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        with patch("handlers.start.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_session.execute = AsyncMock()
            mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
            mock_session.execute.return_value.scalar = MagicMock(return_value=Decimal("0"))
            mock_session.execute.return_value.fetchall = MagicMock(return_value=[])
            mock_session.flush = AsyncMock()
            mock_session.add = MagicMock()

            await start_command(update, context)

            update.message.reply_text.assert_called_once()
            call_kwargs = update.message.reply_text.call_args.kwargs
            assert "reply_markup" in call_kwargs

    @pytest.mark.asyncio
    async def test_start_command_handles_missing_user(self):
        """Test that /start handles missing effective_user gracefully."""
        update = MagicMock()
        update.effective_user = None
        update.message = MagicMock()

        context = MagicMock()

        await start_command(update, context)

        update.message.reply_text.assert_not_called()


class TestHelpCommand:
    """Tests for help_command handler."""

    @pytest.mark.asyncio
    async def test_help_command_shows_help_message(self):
        """Test that /help displays the help message."""
        update = MagicMock()
        update.message = MagicMock()
        update.message.reply_text = AsyncMock()

        context = MagicMock()

        await help_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert call_args.kwargs["text"] == HELP_MESSAGE

    @pytest.mark.asyncio
    async def test_help_command_handles_no_message(self):
        """Test that /help handles missing message gracefully."""
        update = MagicMock()
        update.message = None

        context = MagicMock()

        await help_command(update, context)


class TestHandleMenuHome:
    """Tests for handle_menu_home callback handler."""

    @pytest.mark.asyncio
    async def test_menu_home_returns_to_dashboard(self):
        """Test that menu_home callback returns to dashboard."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123456789
        update.effective_user.username = "testuser"

        context = MagicMock()

        with patch("handlers.start.get_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_user = MagicMock()
            mock_user.id = 1
            mock_session.execute = AsyncMock()
            mock_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=mock_user)
            mock_session.execute.return_value.scalar = MagicMock(return_value=Decimal("5000"))
            mock_session.execute.return_value.fetchall = MagicMock(return_value=[])
            mock_session.flush = AsyncMock()

            await handle_menu_home(update, context)

            update.callback_query.answer.assert_called_once()
            update.callback_query.edit_message_text.assert_called_once()


class TestHandleHelpCallback:
    """Tests for handle_help_callback handler."""

    @pytest.mark.asyncio
    async def test_help_callback_shows_help(self):
        """Test that help callback displays help message."""
        update = MagicMock()
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock()

        await handle_help_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()
        call_kwargs = update.callback_query.edit_message_text.call_args.kwargs
        assert call_kwargs["text"] == HELP_MESSAGE

    @pytest.mark.asyncio
    async def test_help_callback_handles_no_query(self):
        """Test that help callback handles missing query gracefully."""
        update = MagicMock()
        update.callback_query = None

        context = MagicMock()

        await handle_help_callback(update, context)
