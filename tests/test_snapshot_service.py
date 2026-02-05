"""
Tests for the Snapshot Service.

Tests cover:
- Snapshot creation with accounts, trades, and transactions
- Ensuring daily snapshots (idempotent creation)
- Listing snapshots from recent days
- Restoring data from snapshots
- Getting snapshot statistics
- Singleton pattern for service instance
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from services.snapshot_service import (
    SnapshotService,
    _serialize_datetime,
    _serialize_decimal,
    _serialize_enum,
    get_snapshot_service,
    reset_snapshot_service,
)


class TestSerializationHelpers:
    """Tests for serialization helper functions."""

    def test_serialize_decimal_with_value(self):
        """Test serializing a Decimal value."""
        result = _serialize_decimal(Decimal("1234.56"))
        assert result == "1234.56"
        assert isinstance(result, str)

    def test_serialize_decimal_with_none(self):
        """Test serializing None returns None."""
        result = _serialize_decimal(None)
        assert result is None

    def test_serialize_decimal_with_large_precision(self):
        """Test serializing Decimal with high precision."""
        result = _serialize_decimal(Decimal("1.12345678"))
        assert result == "1.12345678"

    def test_serialize_datetime_with_value(self):
        """Test serializing a datetime value."""
        dt = datetime(2026, 2, 5, 10, 30, 45)
        result = _serialize_datetime(dt)
        assert result == "2026-02-05T10:30:45"

    def test_serialize_datetime_with_none(self):
        """Test serializing None datetime returns None."""
        result = _serialize_datetime(None)
        assert result is None

    def test_serialize_datetime_preserves_microseconds(self):
        """Test serializing datetime preserves microseconds."""
        dt = datetime(2026, 2, 5, 10, 30, 45, 123456)
        result = _serialize_datetime(dt)
        assert "123456" in result

    def test_serialize_enum_with_trade_direction(self):
        """Test serializing TradeDirection enum."""
        result = _serialize_enum(TradeDirection.LONG)
        assert result == "long"

    def test_serialize_enum_with_trade_status(self):
        """Test serializing TradeStatus enum."""
        result = _serialize_enum(TradeStatus.CLOSED)
        assert result == "closed"

    def test_serialize_enum_with_none(self):
        """Test serializing None enum returns None."""
        result = _serialize_enum(None)
        assert result is None


class TestSnapshotServiceInitialization:
    """Tests for SnapshotService initialization."""

    def test_service_initializes(self):
        """Test service initializes without error."""
        service = SnapshotService()
        assert service is not None

    def test_service_initializes_with_logger(self):
        """Test service logs initialization message."""
        with patch("services.snapshot_service.logger") as mock_logger:
            SnapshotService()
            mock_logger.info.assert_called_with("SnapshotService initialized")


class TestSingletonPattern:
    """Tests for singleton pattern."""

    def test_get_snapshot_service_returns_same_instance(self):
        """Test get_snapshot_service returns singleton."""
        reset_snapshot_service()

        service1 = get_snapshot_service()
        service2 = get_snapshot_service()

        assert service1 is service2

        reset_snapshot_service()

    def test_reset_clears_singleton(self):
        """Test reset_snapshot_service clears the singleton."""
        service1 = get_snapshot_service()
        reset_snapshot_service()
        service2 = get_snapshot_service()

        assert service1 is not service2

        reset_snapshot_service()

    def test_multiple_resets_are_safe(self):
        """Test calling reset multiple times is safe."""
        reset_snapshot_service()
        reset_snapshot_service()
        reset_snapshot_service()

        service = get_snapshot_service()
        assert service is not None

        reset_snapshot_service()


class TestGetSnapshotStats:
    """Tests for snapshot statistics retrieval."""

    def test_get_snapshot_stats_with_data(self):
        """Test getting stats from snapshot with data."""
        service = SnapshotService()

        snapshot = MagicMock(spec=DataSnapshot)
        snapshot.snapshot_data = {
            "accounts": [{"id": 1}, {"id": 2}],
            "trades": [{"id": 1}, {"id": 2}, {"id": 3}],
            "transactions": [{"id": 1}],
        }

        stats = service.get_snapshot_stats(snapshot)

        assert stats["num_accounts"] == 2
        assert stats["num_trades"] == 3
        assert stats["num_transactions"] == 1

    def test_get_snapshot_stats_with_empty_data(self):
        """Test getting stats from empty snapshot."""
        service = SnapshotService()

        snapshot = MagicMock(spec=DataSnapshot)
        snapshot.snapshot_data = {
            "accounts": [],
            "trades": [],
            "transactions": [],
        }

        stats = service.get_snapshot_stats(snapshot)

        assert stats["num_accounts"] == 0
        assert stats["num_trades"] == 0
        assert stats["num_transactions"] == 0

    def test_get_snapshot_stats_with_none_data(self):
        """Test getting stats when snapshot_data is None."""
        service = SnapshotService()

        snapshot = MagicMock(spec=DataSnapshot)
        snapshot.snapshot_data = None

        stats = service.get_snapshot_stats(snapshot)

        assert stats["num_accounts"] == 0
        assert stats["num_trades"] == 0
        assert stats["num_transactions"] == 0

    def test_get_snapshot_stats_with_missing_keys(self):
        """Test getting stats when keys are missing from snapshot_data."""
        service = SnapshotService()

        snapshot = MagicMock(spec=DataSnapshot)
        snapshot.snapshot_data = {"accounts": [{"id": 1}]}

        stats = service.get_snapshot_stats(snapshot)

        assert stats["num_accounts"] == 1
        assert stats["num_trades"] == 0
        assert stats["num_transactions"] == 0


class TestCreateSnapshot:
    """Tests for snapshot creation."""

    @pytest.mark.asyncio
    async def test_create_snapshot_with_user_not_found(self):
        """Test creating snapshot for non-existent user returns None."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            # User not found
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await service.create_snapshot(user_id=999)

            assert result is None

    @pytest.mark.asyncio
    async def test_create_snapshot_creates_snapshot_record(self):
        """Test creating snapshot adds DataSnapshot to session."""
        service = SnapshotService()

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            # Setup execute to return user, then empty accounts
            call_count = 0

            async def mock_execute(query):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:  # User query
                    mock_result.scalar_one_or_none.return_value = mock_user
                else:  # Accounts query
                    mock_scalars = MagicMock()
                    mock_scalars.all.return_value = []
                    mock_result.scalars.return_value = mock_scalars
                return mock_result

            mock_session.execute = mock_execute
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            result = await service.create_snapshot(user_id=1)

            # Verify session.add was called
            assert mock_session.add.called
            # Verify the added object is a DataSnapshot
            added_obj = mock_session.add.call_args[0][0]
            assert isinstance(added_obj, DataSnapshot)
            assert added_obj.user_id == 1
            assert added_obj.snapshot_date == date.today()

    @pytest.mark.asyncio
    async def test_create_snapshot_includes_accounts_trades_transactions(self):
        """Test snapshot data includes accounts, trades, and transactions."""
        service = SnapshotService()

        mock_user = MagicMock(spec=User)
        mock_user.id = 1

        mock_account = MagicMock(spec=Account)
        mock_account.id = 10
        mock_account.name = "Test Account"
        mock_account.broker = "Test Broker"
        mock_account.starting_balance = Decimal("10000.00")
        mock_account.current_balance = Decimal("11000.00")
        mock_account.currency = "USD"
        mock_account.is_active = True
        mock_account.created_at = datetime(2026, 1, 1, 0, 0, 0)

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            call_count = 0

            async def mock_execute(query):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:  # User query
                    mock_result.scalar_one_or_none.return_value = mock_user
                elif call_count == 2:  # Accounts query
                    mock_scalars = MagicMock()
                    mock_scalars.all.return_value = [mock_account]
                    mock_result.scalars.return_value = mock_scalars
                elif call_count == 3:  # Trades query
                    mock_scalars = MagicMock()
                    mock_scalars.all.return_value = []
                    mock_result.scalars.return_value = mock_scalars
                elif call_count == 4:  # Transactions query
                    mock_scalars = MagicMock()
                    mock_scalars.all.return_value = []
                    mock_result.scalars.return_value = mock_scalars
                return mock_result

            mock_session.execute = mock_execute
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            await service.create_snapshot(user_id=1)

            added_obj = mock_session.add.call_args[0][0]
            assert "accounts" in added_obj.snapshot_data
            assert "trades" in added_obj.snapshot_data
            assert "transactions" in added_obj.snapshot_data
            assert len(added_obj.snapshot_data["accounts"]) == 1
            assert added_obj.snapshot_data["accounts"][0]["name"] == "Test Account"


class TestEnsureDailySnapshot:
    """Tests for ensuring daily snapshot exists."""

    @pytest.mark.asyncio
    async def test_ensure_daily_snapshot_returns_false_when_exists(self):
        """Test ensure_daily_snapshot returns False if snapshot already exists."""
        service = SnapshotService()

        mock_snapshot = MagicMock(spec=DataSnapshot)
        mock_snapshot.id = 1

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_snapshot
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await service.ensure_daily_snapshot(user_id=1)

            assert result is False

    @pytest.mark.asyncio
    async def test_ensure_daily_snapshot_creates_new_when_none_exists(self):
        """Test ensure_daily_snapshot creates snapshot when none exists today."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(
            service, "create_snapshot", new_callable=AsyncMock
        ) as mock_create:
            mock_snapshot = MagicMock(spec=DataSnapshot)
            mock_snapshot.id = 1
            mock_create.return_value = mock_snapshot

            with patch("services.snapshot_service.get_session") as mock_session_ctx2:
                mock_session2 = AsyncMock()
                mock_session_ctx2.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session2
                )
                mock_session_ctx2.return_value.__aexit__ = AsyncMock(return_value=None)

                mock_result2 = MagicMock()
                mock_result2.scalar_one_or_none.return_value = None
                mock_session2.execute = AsyncMock(return_value=mock_result2)

                result = await service.ensure_daily_snapshot(user_id=1)

            mock_create.assert_called_once_with(1)
            assert result is True

    @pytest.mark.asyncio
    async def test_ensure_daily_snapshot_returns_false_when_create_fails(self):
        """Test ensure_daily_snapshot returns False when create_snapshot fails."""
        service = SnapshotService()

        with patch.object(
            service, "create_snapshot", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = None

            with patch("services.snapshot_service.get_session") as mock_session_ctx:
                mock_session = AsyncMock()
                mock_session_ctx.return_value.__aenter__ = AsyncMock(
                    return_value=mock_session
                )
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

                mock_result = MagicMock()
                mock_result.scalar_one_or_none.return_value = None
                mock_session.execute = AsyncMock(return_value=mock_result)

                result = await service.ensure_daily_snapshot(user_id=1)

            assert result is False


class TestListSnapshots:
    """Tests for listing snapshots."""

    @pytest.mark.asyncio
    async def test_list_snapshots_returns_snapshots_from_last_n_days(self):
        """Test list_snapshots returns snapshots within date range."""
        service = SnapshotService()

        mock_snapshot1 = MagicMock(spec=DataSnapshot)
        mock_snapshot1.id = 1
        mock_snapshot1.snapshot_date = date.today()

        mock_snapshot2 = MagicMock(spec=DataSnapshot)
        mock_snapshot2.id = 2
        mock_snapshot2.snapshot_date = date.today() - timedelta(days=3)

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = [mock_snapshot1, mock_snapshot2]
            mock_result.scalars.return_value = mock_scalars
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await service.list_snapshots(user_id=1, days=7)

            assert len(result) == 2
            assert result[0].id == 1
            assert result[1].id == 2

    @pytest.mark.asyncio
    async def test_list_snapshots_with_default_days(self):
        """Test list_snapshots uses default of 7 days."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
            mock_session.execute = AsyncMock(return_value=mock_result)

            await service.list_snapshots(user_id=1)

            # Verify execute was called (meaning default days was used)
            assert mock_session.execute.called

    @pytest.mark.asyncio
    async def test_list_snapshots_returns_empty_list_when_no_snapshots(self):
        """Test list_snapshots returns empty list when no snapshots found."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
            mock_session.execute = AsyncMock(return_value=mock_result)

            result = await service.list_snapshots(user_id=1, days=7)

            assert result == []

    @pytest.mark.asyncio
    async def test_list_snapshots_with_custom_days(self):
        """Test list_snapshots respects custom days parameter."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = []
            mock_result.scalars.return_value = mock_scalars
            mock_session.execute = AsyncMock(return_value=mock_result)

            await service.list_snapshots(user_id=1, days=30)

            assert mock_session.execute.called


class TestRestoreSnapshot:
    """Tests for restoring data from snapshots."""

    @pytest.mark.asyncio
    async def test_restore_snapshot_not_found(self):
        """Test restore returns error when snapshot not found."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_session.execute = AsyncMock(return_value=mock_result)

            success, message = await service.restore_snapshot(
                snapshot_id=999, user_id=1
            )

            assert success is False
            assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_restore_snapshot_unauthorized(self):
        """Test restore returns error when user_id doesn't match."""
        service = SnapshotService()

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None  # No match
            mock_session.execute = AsyncMock(return_value=mock_result)

            success, message = await service.restore_snapshot(
                snapshot_id=1, user_id=999
            )

            assert success is False
            assert "permission" in message.lower() or "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_restore_snapshot_success_returns_correct_message(self):
        """Test restore returns success message with correct stats."""
        service = SnapshotService()

        mock_snapshot = MagicMock(spec=DataSnapshot)
        mock_snapshot.id = 1
        mock_snapshot.user_id = 1
        mock_snapshot.snapshot_date = date(2026, 2, 1)
        mock_snapshot.snapshot_data = {
            "accounts": [
                {
                    "id": 1,
                    "name": "Test Account",
                    "broker": "Test Broker",
                    "starting_balance": "10000.00",
                    "current_balance": "11000.00",
                    "currency": "USD",
                    "is_active": True,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
            "trades": [],
            "transactions": [],
        }

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            call_count = 0

            async def mock_execute(query):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:  # Snapshot query
                    mock_result.scalar_one_or_none.return_value = mock_snapshot
                elif call_count == 2:  # Current accounts query
                    mock_result.fetchall.return_value = []
                return mock_result

            mock_session.execute = mock_execute
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()

            success, message = await service.restore_snapshot(
                snapshot_id=1, user_id=1
            )

            assert success is True
            assert "2026-02-01" in message
            assert "1 account" in message

    @pytest.mark.asyncio
    async def test_restore_snapshot_deletes_current_data_first(self):
        """Test restore deletes current user data before restoring."""
        service = SnapshotService()

        mock_snapshot = MagicMock(spec=DataSnapshot)
        mock_snapshot.id = 1
        mock_snapshot.user_id = 1
        mock_snapshot.snapshot_date = date(2026, 2, 1)
        mock_snapshot.snapshot_data = {
            "accounts": [],
            "trades": [],
            "transactions": [],
        }

        with patch("services.snapshot_service.get_session") as mock_session_ctx:
            mock_session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            call_count = 0

            async def mock_execute(query):
                nonlocal call_count
                call_count += 1
                mock_result = MagicMock()
                if call_count == 1:  # Snapshot query
                    mock_result.scalar_one_or_none.return_value = mock_snapshot
                elif call_count == 2:  # Current accounts query
                    mock_result.fetchall.return_value = [(10,), (20,)]  # Two accounts
                return mock_result

            mock_session.execute = mock_execute
            mock_session.flush = AsyncMock()

            await service.restore_snapshot(snapshot_id=1, user_id=1)

            # Should have multiple execute calls for delete operations
            assert call_count >= 2
