"""
Database models for the Telegram Trade Journal Bot.

This module defines all SQLAlchemy 2.0 async models using the
Mapped and mapped_column patterns.
"""

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Date,
    JSON,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Numeric,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class TradeDirection(str, Enum):
    """Trade direction enumeration."""

    LONG = "long"
    SHORT = "short"


class TradeStatus(str, Enum):
    """Trade status enumeration."""

    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TransactionType(str, Enum):
    """Transaction type enumeration."""

    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    ADJUSTMENT = "adjustment"


class User(Base):
    """
    User model representing a Telegram user.

    Stores the mapping between Telegram user IDs and internal user records.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    accounts: Mapped[list["Account"]] = relationship(
        "Account", back_populates="user", cascade="all, delete-orphan"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        "Strategy", back_populates="user", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        "Reminder", back_populates="user", cascade="all, delete-orphan"
    )
    snapshots: Mapped[list["DataSnapshot"]] = relationship(
        "DataSnapshot", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username={self.username})>"


class Account(Base):
    """
    Trading account model.

    Represents a trading account with balance tracking and associated trades.
    """

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    broker: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    starting_balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), nullable=False
    )
    current_balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="accounts")
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="account", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name}, broker={self.broker})>"


class Strategy(Base):
    """
    Trading strategy model.

    Represents a trading strategy with rules stored as JSON.
    """

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rules: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="strategies")
    trades: Mapped[list["Trade"]] = relationship("Trade", back_populates="strategy")

    def __repr__(self) -> str:
        return f"<Strategy(id={self.id}, name={self.name})>"


class Tag(Base):
    """
    Tag model for categorizing trades.

    Tags can be system defaults or user-created.
    """

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    trade_tags: Mapped[list["TradeTag"]] = relationship(
        "TradeTag", back_populates="tag", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name={self.name}, is_default={self.is_default})>"


class Trade(Base):
    """
    Trade model representing a single trade entry.

    Contains all trade details including entry, exit, P&L, and metadata.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    instrument: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[TradeDirection] = mapped_column(
        SQLEnum(TradeDirection), nullable=False
    )
    entry_price: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), nullable=False
    )
    exit_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=8), nullable=True
    )
    sl_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=8), nullable=True
    )
    tp_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=8), nullable=True
    )
    lot_size: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=8), nullable=False
    )
    status: Mapped[TradeStatus] = mapped_column(
        SQLEnum(TradeStatus), default=TradeStatus.OPEN, nullable=False
    )
    pnl: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=18, scale=2), nullable=True
    )
    pnl_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(precision=10, scale=4), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("strategies.id"), nullable=True, index=True
    )
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="trades")
    strategy: Mapped[Optional["Strategy"]] = relationship(
        "Strategy", back_populates="trades"
    )
    trade_tags: Mapped[list["TradeTag"]] = relationship(
        "TradeTag", back_populates="trade", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Trade(id={self.id}, instrument={self.instrument}, "
            f"direction={self.direction.value}, status={self.status.value})>"
        )


class TradeTag(Base):
    """
    Junction table for many-to-many relationship between trades and tags.
    """

    __tablename__ = "trade_tags"

    trade_id: Mapped[int] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    # Relationships
    trade: Mapped["Trade"] = relationship("Trade", back_populates="trade_tags")
    tag: Mapped["Tag"] = relationship("Tag", back_populates="trade_tags")

    def __repr__(self) -> str:
        return f"<TradeTag(trade_id={self.trade_id}, tag_id={self.tag_id})>"


class Transaction(Base):
    """
    Transaction model for account balance adjustments.

    Tracks deposits, withdrawals, and manual adjustments.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    type: Mapped[TransactionType] = mapped_column(
        SQLEnum(TransactionType), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=2), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    account: Mapped["Account"] = relationship("Account", back_populates="transactions")

    def __repr__(self) -> str:
        return f"<Transaction(id={self.id}, type={self.type.value}, amount={self.amount})>"


class Reminder(Base):
    """
    Reminder model for trade journaling reminders.

    Stores user-configured reminder times in UTC.
    """

    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    time_utc: Mapped[time] = mapped_column(Time, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_sent: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="reminders")

    def __repr__(self) -> str:
        return f"<Reminder(id={self.id}, time_utc={self.time_utc}, enabled={self.enabled})>"


class DataSnapshot(Base):
    """
    Data snapshot model for storing point-in-time backups of user data.

    Enables data rollback functionality by storing serialized copies of
    all user accounts, trades, and transactions at a specific date.
    Snapshots are created daily and can be used to restore user data
    to a previous state.
    """

    __tablename__ = "data_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<DataSnapshot(id={self.id}, user_id={self.user_id}, snapshot_date={self.snapshot_date})>"
