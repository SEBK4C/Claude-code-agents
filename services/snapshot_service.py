"""
Snapshot Service for the Telegram Trade Journal Bot.

This module provides functionality for creating and restoring data snapshots,
enabling users to rollback their trading data to a previous state.
Snapshots are created daily and include all accounts, trades, and transactions.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_logger
from database.db import get_session
from database.models import (
    Account,
    DataSnapshot,
    Trade,
    TradeDirection,
    TradeStatus,
    TradeTag,
    Transaction,
    TransactionType,
    User,
)

logger = get_logger(__name__)


def _serialize_decimal(value: Optional[Decimal]) -> Optional[str]:
    """
    Serialize a Decimal value to string for JSON storage.

    Args:
        value: The Decimal value to serialize.

    Returns:
        Optional[str]: String representation of the Decimal, or None if input is None.
    """
    if value is None:
        return None
    return str(value)


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    """
    Serialize a datetime value to ISO format string for JSON storage.

    Args:
        value: The datetime value to serialize.

    Returns:
        Optional[str]: ISO format string, or None if input is None.
    """
    if value is None:
        return None
    return value.isoformat()


def _serialize_enum(value: Any) -> Optional[str]:
    """
    Serialize an enum value to string for JSON storage.

    Args:
        value: The enum value to serialize.

    Returns:
        Optional[str]: The enum's value as string, or None if input is None.
    """
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


class SnapshotService:
    """
    Service class for managing data snapshots and rollback operations.

    Provides functionality to create point-in-time backups of user data
    and restore data from previous snapshots. Supports daily snapshot
    creation with configurable retention periods.
    """

    def __init__(self) -> None:
        """Initialize the snapshot service."""
        logger.info("SnapshotService initialized")

    async def _serialize_account(
        self, account: Account, session: AsyncSession
    ) -> dict[str, Any]:
        """
        Serialize an account and its related data to a dictionary.

        Args:
            account: The account to serialize.
            session: The database session.

        Returns:
            dict: Serialized account data including trades and transactions.
        """
        # Serialize base account data
        account_data = {
            "id": account.id,
            "name": account.name,
            "broker": account.broker,
            "starting_balance": _serialize_decimal(account.starting_balance),
            "current_balance": _serialize_decimal(account.current_balance),
            "currency": account.currency,
            "is_active": account.is_active,
            "created_at": _serialize_datetime(account.created_at),
        }

        return account_data

    async def _serialize_trade(
        self, trade: Trade, session: AsyncSession
    ) -> dict[str, Any]:
        """
        Serialize a trade and its related data to a dictionary.

        Args:
            trade: The trade to serialize.
            session: The database session.

        Returns:
            dict: Serialized trade data including tags.
        """
        # Get trade tags
        tags_result = await session.execute(
            select(TradeTag.tag_id).where(TradeTag.trade_id == trade.id)
        )
        tag_ids = [row[0] for row in tags_result.fetchall()]

        return {
            "id": trade.id,
            "account_id": trade.account_id,
            "instrument": trade.instrument,
            "direction": _serialize_enum(trade.direction),
            "entry_price": _serialize_decimal(trade.entry_price),
            "exit_price": _serialize_decimal(trade.exit_price),
            "sl_price": _serialize_decimal(trade.sl_price),
            "tp_price": _serialize_decimal(trade.tp_price),
            "lot_size": _serialize_decimal(trade.lot_size),
            "status": _serialize_enum(trade.status),
            "pnl": _serialize_decimal(trade.pnl),
            "pnl_percent": _serialize_decimal(trade.pnl_percent),
            "notes": trade.notes,
            "strategy_id": trade.strategy_id,
            "screenshot_path": trade.screenshot_path,
            "opened_at": _serialize_datetime(trade.opened_at),
            "closed_at": _serialize_datetime(trade.closed_at),
            "tag_ids": tag_ids,
        }

    async def _serialize_transaction(
        self, transaction: Transaction
    ) -> dict[str, Any]:
        """
        Serialize a transaction to a dictionary.

        Args:
            transaction: The transaction to serialize.

        Returns:
            dict: Serialized transaction data.
        """
        return {
            "id": transaction.id,
            "account_id": transaction.account_id,
            "type": _serialize_enum(transaction.type),
            "amount": _serialize_decimal(transaction.amount),
            "note": transaction.note,
            "created_at": _serialize_datetime(transaction.created_at),
        }

    async def create_snapshot(self, user_id: int) -> Optional[DataSnapshot]:
        """
        Create a snapshot of all user data.

        Serializes all accounts, trades, and transactions for the user
        and stores them in a DataSnapshot record.

        Args:
            user_id: The internal user ID to create a snapshot for.

        Returns:
            Optional[DataSnapshot]: The created snapshot, or None if no data to snapshot.
        """
        async with get_session() as session:
            # Get user
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                logger.warning("User not found for snapshot", user_id=user_id)
                return None

            # Get all accounts for user
            accounts_result = await session.execute(
                select(Account).where(Account.user_id == user_id)
            )
            accounts = list(accounts_result.scalars().all())

            # Serialize accounts
            serialized_accounts = []
            for account in accounts:
                account_data = await self._serialize_account(account, session)
                serialized_accounts.append(account_data)

            # Get all trades for user's accounts
            account_ids = [a.id for a in accounts]
            serialized_trades = []
            serialized_transactions = []

            if account_ids:
                # Get trades
                trades_result = await session.execute(
                    select(Trade).where(Trade.account_id.in_(account_ids))
                )
                trades = list(trades_result.scalars().all())

                for trade in trades:
                    trade_data = await self._serialize_trade(trade, session)
                    serialized_trades.append(trade_data)

                # Get transactions
                transactions_result = await session.execute(
                    select(Transaction).where(Transaction.account_id.in_(account_ids))
                )
                transactions = list(transactions_result.scalars().all())

                for transaction in transactions:
                    transaction_data = await self._serialize_transaction(transaction)
                    serialized_transactions.append(transaction_data)

            # Create snapshot data
            snapshot_data = {
                "accounts": serialized_accounts,
                "trades": serialized_trades,
                "transactions": serialized_transactions,
            }

            # Create and save snapshot
            snapshot = DataSnapshot(
                user_id=user_id,
                snapshot_date=date.today(),
                snapshot_data=snapshot_data,
            )
            session.add(snapshot)
            await session.flush()

            logger.info(
                "Snapshot created",
                user_id=user_id,
                snapshot_id=snapshot.id,
                num_accounts=len(serialized_accounts),
                num_trades=len(serialized_trades),
                num_transactions=len(serialized_transactions),
            )

            return snapshot

    async def ensure_daily_snapshot(self, user_id: int) -> bool:
        """
        Ensure a snapshot exists for today, creating one if needed.

        This method is idempotent - it will only create a snapshot if
        one doesn't already exist for today.

        Args:
            user_id: The internal user ID to ensure snapshot for.

        Returns:
            bool: True if a new snapshot was created, False if one already existed.
        """
        async with get_session() as session:
            # Check if snapshot exists for today
            existing_result = await session.execute(
                select(DataSnapshot)
                .where(DataSnapshot.user_id == user_id)
                .where(DataSnapshot.snapshot_date == date.today())
            )
            existing = existing_result.scalar_one_or_none()

            if existing:
                logger.debug(
                    "Snapshot already exists for today",
                    user_id=user_id,
                    snapshot_id=existing.id,
                )
                return False

        # Create new snapshot (uses its own session)
        snapshot = await self.create_snapshot(user_id)

        if snapshot:
            logger.info(
                "Daily snapshot created",
                user_id=user_id,
                snapshot_id=snapshot.id,
            )
            return True

        return False

    async def list_snapshots(
        self, user_id: int, days: int = 7
    ) -> list[DataSnapshot]:
        """
        List snapshots for a user from the last N days.

        Args:
            user_id: The internal user ID.
            days: Number of days to look back (default 7).

        Returns:
            list[DataSnapshot]: List of snapshots, ordered by date descending.
        """
        async with get_session() as session:
            cutoff_date = date.today() - timedelta(days=days)

            result = await session.execute(
                select(DataSnapshot)
                .where(DataSnapshot.user_id == user_id)
                .where(DataSnapshot.snapshot_date >= cutoff_date)
                .order_by(DataSnapshot.snapshot_date.desc())
            )
            snapshots = list(result.scalars().all())

            logger.debug(
                "Listed snapshots",
                user_id=user_id,
                days=days,
                count=len(snapshots),
            )

            return snapshots

    async def restore_snapshot(
        self, snapshot_id: int, user_id: int
    ) -> tuple[bool, str]:
        """
        Restore user data from a snapshot.

        This operation will:
        1. Delete all current accounts, trades, and transactions for the user
        2. Recreate all data from the snapshot

        Args:
            snapshot_id: The ID of the snapshot to restore.
            user_id: The user ID (for verification).

        Returns:
            tuple[bool, str]: (success, message) - Success status and descriptive message.
        """
        async with get_session() as session:
            # Get and verify snapshot
            snapshot_result = await session.execute(
                select(DataSnapshot)
                .where(DataSnapshot.id == snapshot_id)
                .where(DataSnapshot.user_id == user_id)
            )
            snapshot = snapshot_result.scalar_one_or_none()

            if not snapshot:
                logger.warning(
                    "Snapshot not found or unauthorized",
                    snapshot_id=snapshot_id,
                    user_id=user_id,
                )
                return False, "Snapshot not found or you don't have permission to restore it."

            snapshot_data = snapshot.snapshot_data

            # Get current account IDs for deletion
            current_accounts_result = await session.execute(
                select(Account.id).where(Account.user_id == user_id)
            )
            current_account_ids = [row[0] for row in current_accounts_result.fetchall()]

            # Delete current data in order (respecting foreign keys)
            if current_account_ids:
                # Delete trade tags first
                await session.execute(
                    delete(TradeTag).where(
                        TradeTag.trade_id.in_(
                            select(Trade.id).where(
                                Trade.account_id.in_(current_account_ids)
                            )
                        )
                    )
                )

                # Delete trades
                await session.execute(
                    delete(Trade).where(Trade.account_id.in_(current_account_ids))
                )

                # Delete transactions
                await session.execute(
                    delete(Transaction).where(
                        Transaction.account_id.in_(current_account_ids)
                    )
                )

                # Delete accounts
                await session.execute(
                    delete(Account).where(Account.id.in_(current_account_ids))
                )

            # Track ID mappings for foreign key updates
            old_to_new_account_id: dict[int, int] = {}

            # Restore accounts
            for account_data in snapshot_data.get("accounts", []):
                old_id = account_data["id"]
                new_account = Account(
                    user_id=user_id,
                    name=account_data["name"],
                    broker=account_data.get("broker"),
                    starting_balance=Decimal(account_data["starting_balance"]),
                    current_balance=Decimal(account_data["current_balance"]),
                    currency=account_data.get("currency", "USD"),
                    is_active=account_data.get("is_active", True),
                    created_at=datetime.fromisoformat(account_data["created_at"])
                    if account_data.get("created_at")
                    else datetime.utcnow(),
                )
                session.add(new_account)
                await session.flush()
                old_to_new_account_id[old_id] = new_account.id

            # Track old trade IDs to new trade IDs for trade tags
            old_to_new_trade_id: dict[int, int] = {}

            # Restore trades
            for trade_data in snapshot_data.get("trades", []):
                old_account_id = trade_data["account_id"]
                new_account_id = old_to_new_account_id.get(old_account_id)

                if new_account_id is None:
                    logger.warning(
                        "Skipping trade with unknown account",
                        old_account_id=old_account_id,
                    )
                    continue

                old_trade_id = trade_data["id"]

                # Parse direction enum
                direction_str = trade_data["direction"]
                direction = (
                    TradeDirection.LONG
                    if direction_str == "long"
                    else TradeDirection.SHORT
                )

                # Parse status enum
                status_str = trade_data.get("status", "open")
                if status_str == "closed":
                    status = TradeStatus.CLOSED
                elif status_str == "cancelled":
                    status = TradeStatus.CANCELLED
                else:
                    status = TradeStatus.OPEN

                new_trade = Trade(
                    account_id=new_account_id,
                    instrument=trade_data["instrument"],
                    direction=direction,
                    entry_price=Decimal(trade_data["entry_price"]),
                    exit_price=(
                        Decimal(trade_data["exit_price"])
                        if trade_data.get("exit_price")
                        else None
                    ),
                    sl_price=(
                        Decimal(trade_data["sl_price"])
                        if trade_data.get("sl_price")
                        else None
                    ),
                    tp_price=(
                        Decimal(trade_data["tp_price"])
                        if trade_data.get("tp_price")
                        else None
                    ),
                    lot_size=Decimal(trade_data["lot_size"]),
                    status=status,
                    pnl=(
                        Decimal(trade_data["pnl"])
                        if trade_data.get("pnl")
                        else None
                    ),
                    pnl_percent=(
                        Decimal(trade_data["pnl_percent"])
                        if trade_data.get("pnl_percent")
                        else None
                    ),
                    notes=trade_data.get("notes"),
                    strategy_id=trade_data.get("strategy_id"),
                    screenshot_path=trade_data.get("screenshot_path"),
                    opened_at=(
                        datetime.fromisoformat(trade_data["opened_at"])
                        if trade_data.get("opened_at")
                        else datetime.utcnow()
                    ),
                    closed_at=(
                        datetime.fromisoformat(trade_data["closed_at"])
                        if trade_data.get("closed_at")
                        else None
                    ),
                )
                session.add(new_trade)
                await session.flush()
                old_to_new_trade_id[old_trade_id] = new_trade.id

                # Restore trade tags
                for tag_id in trade_data.get("tag_ids", []):
                    trade_tag = TradeTag(
                        trade_id=new_trade.id,
                        tag_id=tag_id,
                    )
                    session.add(trade_tag)

            # Restore transactions
            for transaction_data in snapshot_data.get("transactions", []):
                old_account_id = transaction_data["account_id"]
                new_account_id = old_to_new_account_id.get(old_account_id)

                if new_account_id is None:
                    logger.warning(
                        "Skipping transaction with unknown account",
                        old_account_id=old_account_id,
                    )
                    continue

                # Parse transaction type enum
                type_str = transaction_data["type"]
                if type_str == "deposit":
                    trans_type = TransactionType.DEPOSIT
                elif type_str == "withdrawal":
                    trans_type = TransactionType.WITHDRAWAL
                else:
                    trans_type = TransactionType.ADJUSTMENT

                new_transaction = Transaction(
                    account_id=new_account_id,
                    type=trans_type,
                    amount=Decimal(transaction_data["amount"]),
                    note=transaction_data.get("note"),
                    created_at=(
                        datetime.fromisoformat(transaction_data["created_at"])
                        if transaction_data.get("created_at")
                        else datetime.utcnow()
                    ),
                )
                session.add(new_transaction)

            await session.flush()

            # Calculate stats
            stats = self.get_snapshot_stats(snapshot)

            logger.info(
                "Snapshot restored successfully",
                snapshot_id=snapshot_id,
                user_id=user_id,
                snapshot_date=str(snapshot.snapshot_date),
                accounts_restored=stats["num_accounts"],
                trades_restored=stats["num_trades"],
                transactions_restored=stats["num_transactions"],
            )

            return True, (
                f"Data restored from {snapshot.snapshot_date}. "
                f"Restored {stats['num_accounts']} account(s), "
                f"{stats['num_trades']} trade(s), and "
                f"{stats['num_transactions']} transaction(s)."
            )

    def get_snapshot_stats(self, snapshot: DataSnapshot) -> dict[str, int]:
        """
        Get statistics about a snapshot's contents.

        Args:
            snapshot: The snapshot to analyze.

        Returns:
            dict: Statistics including num_accounts, num_trades, num_transactions.
        """
        data = snapshot.snapshot_data or {}

        return {
            "num_accounts": len(data.get("accounts", [])),
            "num_trades": len(data.get("trades", [])),
            "num_transactions": len(data.get("transactions", [])),
        }


# Module-level singleton instance
_snapshot_service: Optional[SnapshotService] = None


def get_snapshot_service() -> SnapshotService:
    """
    Get or create the global SnapshotService instance.

    Returns:
        SnapshotService: The global snapshot service singleton.
    """
    global _snapshot_service
    if _snapshot_service is None:
        _snapshot_service = SnapshotService()
    return _snapshot_service


def reset_snapshot_service() -> None:
    """
    Reset the global SnapshotService instance.

    Useful for testing or reconfiguration.
    """
    global _snapshot_service
    _snapshot_service = None
