"""
Tests for database models.

This module tests:
- Model creation and relationships
- Enum types
- Field constraints and defaults
"""

from datetime import datetime, time
from decimal import Decimal

import pytest
from sqlalchemy import select

from database.models import (
    Account,
    Reminder,
    Strategy,
    Tag,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
    Transaction,
    TransactionType,
    User,
)


class TestUserModel:
    """Tests for the User model."""

    @pytest.mark.asyncio
    async def test_create_user(self, session):
        """Test creating a user with required fields."""
        user = User(telegram_id=999888777, username="newuser")
        session.add(user)
        await session.flush()

        assert user.id is not None
        assert user.telegram_id == 999888777
        assert user.username == "newuser"
        assert isinstance(user.created_at, datetime)

    @pytest.mark.asyncio
    async def test_user_without_username(self, session):
        """Test creating a user without optional username."""
        user = User(telegram_id=111222333)
        session.add(user)
        await session.flush()

        assert user.id is not None
        assert user.username is None

    @pytest.mark.asyncio
    async def test_user_telegram_id_unique(self, session, sample_user):
        """Test that telegram_id must be unique."""
        from sqlalchemy.exc import IntegrityError

        duplicate = User(telegram_id=sample_user.telegram_id, username="duplicate")
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            await session.flush()

    @pytest.mark.asyncio
    async def test_user_repr(self, sample_user):
        """Test User string representation."""
        repr_str = repr(sample_user)
        assert "User" in repr_str
        assert str(sample_user.id) in repr_str
        assert str(sample_user.telegram_id) in repr_str


class TestAccountModel:
    """Tests for the Account model."""

    @pytest.mark.asyncio
    async def test_create_account(self, session, sample_user):
        """Test creating an account with all fields."""
        account = Account(
            user_id=sample_user.id,
            name="Trading Account",
            broker="IC Markets",
            starting_balance=Decimal("5000.00"),
            current_balance=Decimal("5250.50"),
            currency="EUR",
            is_active=True,
        )
        session.add(account)
        await session.flush()

        assert account.id is not None
        assert account.name == "Trading Account"
        assert account.broker == "IC Markets"
        assert account.starting_balance == Decimal("5000.00")
        assert account.current_balance == Decimal("5250.50")
        assert account.currency == "EUR"
        assert account.is_active is True

    @pytest.mark.asyncio
    async def test_account_default_currency(self, session, sample_user):
        """Test account defaults to USD currency."""
        account = Account(
            user_id=sample_user.id,
            name="Default Currency Account",
            starting_balance=Decimal("1000.00"),
            current_balance=Decimal("1000.00"),
        )
        session.add(account)
        await session.flush()

        assert account.currency == "USD"

    @pytest.mark.asyncio
    async def test_account_user_relationship(self, session, sample_user, sample_account):
        """Test account-user relationship."""
        await session.refresh(sample_account, ["user"])
        assert sample_account.user.id == sample_user.id

    @pytest.mark.asyncio
    async def test_account_repr(self, sample_account):
        """Test Account string representation."""
        repr_str = repr(sample_account)
        assert "Account" in repr_str
        assert sample_account.name in repr_str


class TestStrategyModel:
    """Tests for the Strategy model."""

    @pytest.mark.asyncio
    async def test_create_strategy(self, session, sample_user):
        """Test creating a strategy with JSON rules."""
        strategy = Strategy(
            user_id=sample_user.id,
            name="Breakout Strategy",
            description="Trade breakouts from consolidation",
            rules={
                "entry": "price_above_resistance",
                "exit": "trailing_stop_2atr",
                "risk": "1%",
            },
        )
        session.add(strategy)
        await session.flush()

        assert strategy.id is not None
        assert strategy.name == "Breakout Strategy"
        assert strategy.rules["entry"] == "price_above_resistance"

    @pytest.mark.asyncio
    async def test_strategy_without_rules(self, session, sample_user):
        """Test creating a strategy without rules."""
        strategy = Strategy(
            user_id=sample_user.id,
            name="Simple Strategy",
        )
        session.add(strategy)
        await session.flush()

        assert strategy.rules is None

    @pytest.mark.asyncio
    async def test_strategy_repr(self, sample_strategy):
        """Test Strategy string representation."""
        repr_str = repr(sample_strategy)
        assert "Strategy" in repr_str
        assert sample_strategy.name in repr_str


class TestTagModel:
    """Tests for the Tag model."""

    @pytest.mark.asyncio
    async def test_create_tag(self, session):
        """Test creating a tag."""
        tag = Tag(name="Momentum", is_default=False)
        session.add(tag)
        await session.flush()

        assert tag.id is not None
        assert tag.name == "Momentum"
        assert tag.is_default is False

    @pytest.mark.asyncio
    async def test_tag_name_unique(self, session, sample_tag):
        """Test that tag names must be unique."""
        from sqlalchemy.exc import IntegrityError

        duplicate = Tag(name=sample_tag.name, is_default=False)
        session.add(duplicate)

        with pytest.raises(IntegrityError):
            await session.flush()

    @pytest.mark.asyncio
    async def test_tag_repr(self, sample_tag):
        """Test Tag string representation."""
        repr_str = repr(sample_tag)
        assert "Tag" in repr_str
        assert sample_tag.name in repr_str


class TestTradeModel:
    """Tests for the Trade model."""

    @pytest.mark.asyncio
    async def test_create_trade(self, session, sample_account):
        """Test creating a trade with required fields."""
        trade = Trade(
            account_id=sample_account.id,
            instrument="GBPUSD",
            direction=TradeDirection.SHORT,
            entry_price=Decimal("1.25000"),
            lot_size=Decimal("0.50"),
        )
        session.add(trade)
        await session.flush()

        assert trade.id is not None
        assert trade.instrument == "GBPUSD"
        assert trade.direction == TradeDirection.SHORT
        assert trade.status == TradeStatus.OPEN  # Default

    @pytest.mark.asyncio
    async def test_trade_with_all_fields(self, session, sample_account, sample_strategy):
        """Test creating a trade with all optional fields."""
        trade = Trade(
            account_id=sample_account.id,
            instrument="USDJPY",
            direction=TradeDirection.LONG,
            entry_price=Decimal("150.000"),
            exit_price=Decimal("151.500"),
            sl_price=Decimal("149.500"),
            tp_price=Decimal("152.000"),
            lot_size=Decimal("1.00"),
            status=TradeStatus.CLOSED,
            pnl=Decimal("150.00"),
            pnl_percent=Decimal("1.50"),
            notes="Great trade following the trend",
            strategy_id=sample_strategy.id,
            screenshot_path="/screenshots/trade_123.png",
        )
        session.add(trade)
        await session.flush()

        assert trade.exit_price == Decimal("151.500")
        assert trade.pnl == Decimal("150.00")
        assert trade.status == TradeStatus.CLOSED

    @pytest.mark.asyncio
    async def test_trade_direction_enum(self, sample_trade):
        """Test trade direction enum values."""
        assert sample_trade.direction == TradeDirection.LONG
        assert sample_trade.direction.value == "long"

    @pytest.mark.asyncio
    async def test_trade_status_enum(self, sample_trade):
        """Test trade status enum values."""
        assert sample_trade.status == TradeStatus.OPEN
        assert sample_trade.status.value == "open"

    @pytest.mark.asyncio
    async def test_trade_repr(self, sample_trade):
        """Test Trade string representation."""
        repr_str = repr(sample_trade)
        assert "Trade" in repr_str
        assert sample_trade.instrument in repr_str


class TestTradeTagModel:
    """Tests for the TradeTag junction table."""

    @pytest.mark.asyncio
    async def test_create_trade_tag(self, session, sample_trade, sample_tag):
        """Test creating a trade-tag association."""
        trade_tag = TradeTag(trade_id=sample_trade.id, tag_id=sample_tag.id)
        session.add(trade_tag)
        await session.flush()

        assert trade_tag.trade_id == sample_trade.id
        assert trade_tag.tag_id == sample_tag.id

    @pytest.mark.asyncio
    async def test_trade_tag_relationships(self, session, sample_trade, sample_tag):
        """Test trade-tag relationships work correctly."""
        trade_tag = TradeTag(trade_id=sample_trade.id, tag_id=sample_tag.id)
        session.add(trade_tag)
        await session.flush()

        await session.refresh(trade_tag, ["trade", "tag"])
        assert trade_tag.trade.id == sample_trade.id
        assert trade_tag.tag.id == sample_tag.id

    @pytest.mark.asyncio
    async def test_trade_tag_repr(self, session, sample_trade, sample_tag):
        """Test TradeTag string representation."""
        trade_tag = TradeTag(trade_id=sample_trade.id, tag_id=sample_tag.id)
        repr_str = repr(trade_tag)
        assert "TradeTag" in repr_str


class TestTransactionModel:
    """Tests for the Transaction model."""

    @pytest.mark.asyncio
    async def test_create_deposit(self, session, sample_account):
        """Test creating a deposit transaction."""
        transaction = Transaction(
            account_id=sample_account.id,
            type=TransactionType.DEPOSIT,
            amount=Decimal("1000.00"),
            note="Initial deposit",
        )
        session.add(transaction)
        await session.flush()

        assert transaction.id is not None
        assert transaction.type == TransactionType.DEPOSIT
        assert transaction.amount == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_create_withdrawal(self, session, sample_account):
        """Test creating a withdrawal transaction."""
        transaction = Transaction(
            account_id=sample_account.id,
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("500.00"),
        )
        session.add(transaction)
        await session.flush()

        assert transaction.type == TransactionType.WITHDRAWAL

    @pytest.mark.asyncio
    async def test_transaction_type_enum(self):
        """Test transaction type enum values."""
        assert TransactionType.DEPOSIT.value == "deposit"
        assert TransactionType.WITHDRAWAL.value == "withdrawal"
        assert TransactionType.ADJUSTMENT.value == "adjustment"

    @pytest.mark.asyncio
    async def test_transaction_repr(self, session, sample_account):
        """Test Transaction string representation."""
        transaction = Transaction(
            account_id=sample_account.id,
            type=TransactionType.DEPOSIT,
            amount=Decimal("100.00"),
        )
        session.add(transaction)
        await session.flush()

        repr_str = repr(transaction)
        assert "Transaction" in repr_str


class TestReminderModel:
    """Tests for the Reminder model."""

    @pytest.mark.asyncio
    async def test_create_reminder(self, session, sample_user):
        """Test creating a reminder."""
        reminder = Reminder(
            user_id=sample_user.id,
            time_utc=time(14, 30),
            enabled=True,
        )
        session.add(reminder)
        await session.flush()

        assert reminder.id is not None
        assert reminder.time_utc == time(14, 30)
        assert reminder.enabled is True
        assert reminder.last_sent is None

    @pytest.mark.asyncio
    async def test_reminder_disabled(self, session, sample_user):
        """Test creating a disabled reminder."""
        reminder = Reminder(
            user_id=sample_user.id,
            time_utc=time(9, 0),
            enabled=False,
        )
        session.add(reminder)
        await session.flush()

        assert reminder.enabled is False

    @pytest.mark.asyncio
    async def test_reminder_with_last_sent(self, session, sample_user):
        """Test reminder with last_sent timestamp."""
        now = datetime.utcnow()
        reminder = Reminder(
            user_id=sample_user.id,
            time_utc=time(8, 0),
            enabled=True,
            last_sent=now,
        )
        session.add(reminder)
        await session.flush()

        assert reminder.last_sent == now

    @pytest.mark.asyncio
    async def test_reminder_repr(self, sample_reminder):
        """Test Reminder string representation."""
        repr_str = repr(sample_reminder)
        assert "Reminder" in repr_str


class TestModelRelationships:
    """Tests for model relationships and cascades."""

    @pytest.mark.asyncio
    async def test_user_has_accounts(self, session, sample_user, sample_account):
        """Test user can access their accounts."""
        await session.refresh(sample_user, ["accounts"])
        assert len(sample_user.accounts) == 1
        assert sample_user.accounts[0].id == sample_account.id

    @pytest.mark.asyncio
    async def test_account_has_trades(self, session, sample_account, sample_trade):
        """Test account can access its trades."""
        await session.refresh(sample_account, ["trades"])
        assert len(sample_account.trades) == 1
        assert sample_account.trades[0].id == sample_trade.id

    @pytest.mark.asyncio
    async def test_trade_has_strategy(self, session, sample_trade, sample_strategy):
        """Test trade can access its strategy."""
        await session.refresh(sample_trade, ["strategy"])
        assert sample_trade.strategy.id == sample_strategy.id
