"""
Tests for the P&L Service.

This module tests:
- P&L calculation with currency conversion
- Unrealized P&L calculation
- Risk/reward ratio calculation
- Position size calculation
- Edge cases and error handling
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.pnl_service import (
    PnLResult,
    PnLService,
    PositionSizeResult,
    RiskRewardResult,
    get_pnl_service,
    reset_pnl_service,
)


class TestPnLServiceSingleton:
    """Tests for PnLService singleton pattern."""

    def setup_method(self):
        """Reset singleton before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    def test_get_pnl_service_returns_same_instance(self):
        """Test that get_pnl_service returns the same instance."""
        service1 = get_pnl_service()
        service2 = get_pnl_service()
        assert service1 is service2

    def test_reset_pnl_service_clears_instance(self):
        """Test that reset_pnl_service creates a new instance."""
        service1 = get_pnl_service()
        reset_pnl_service()
        service2 = get_pnl_service()
        assert service1 is not service2

    def test_pnl_service_initialization(self):
        """Test PnLService can be instantiated."""
        service = PnLService()
        assert service is not None


class TestCalculatePnL:
    """Tests for the calculate_pnl method."""

    def setup_method(self):
        """Reset singletons before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    @pytest.mark.asyncio
    async def test_calculate_pnl_long_profit_usd_instrument(self):
        """Test P&L calculation for profitable long trade on USD instrument."""
        service = PnLService()

        # Mock currency service to not make real API calls
        with patch("services.pnl_service.get_currency_service") as mock_get_cs:
            result = await service.calculate_pnl(
                instrument="NASDAQ",
                direction="LONG",
                entry_price=15000.0,
                exit_price=15100.0,
                lot_size=1.0,
            )

        assert result.success
        assert result.points == 100.0
        assert result.pnl_native == 100.0  # 100 points * 1.0 point_value * 1.0 lot
        assert result.pnl_base == 100.0  # Same currency, no conversion
        assert result.native_currency == "USD"
        assert result.base_currency == "USD"
        assert result.exchange_rate == 1.0

    @pytest.mark.asyncio
    async def test_calculate_pnl_short_profit_usd_instrument(self):
        """Test P&L calculation for profitable short trade on USD instrument."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="SHORT",
            entry_price=15100.0,
            exit_price=15000.0,
            lot_size=1.0,
        )

        assert result.success
        assert result.points == 100.0
        assert result.pnl_native == 100.0

    @pytest.mark.asyncio
    async def test_calculate_pnl_long_loss(self):
        """Test P&L calculation for losing long trade."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="LONG",
            entry_price=15100.0,
            exit_price=15000.0,
            lot_size=1.0,
        )

        assert result.success
        assert result.points == -100.0
        assert result.pnl_native == -100.0

    @pytest.mark.asyncio
    async def test_calculate_pnl_short_loss(self):
        """Test P&L calculation for losing short trade."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="SHORT",
            entry_price=15000.0,
            exit_price=15100.0,
            lot_size=1.0,
        )

        assert result.success
        assert result.points == -100.0
        assert result.pnl_native == -100.0

    @pytest.mark.asyncio
    async def test_calculate_pnl_with_lot_size(self):
        """Test P&L calculation with different lot sizes."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="LONG",
            entry_price=15000.0,
            exit_price=15100.0,
            lot_size=2.5,
        )

        assert result.success
        assert result.points == 100.0
        assert result.pnl_native == 250.0  # 100 points * 1.0 point_value * 2.5 lots

    @pytest.mark.asyncio
    async def test_calculate_pnl_eur_instrument_with_conversion(self):
        """Test P&L calculation for EUR instrument with currency conversion."""
        service = PnLService()

        # Mock currency service for EUR to USD conversion
        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.08
        mock_rate_result.is_fallback = False

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18050.0,
                lot_size=1.0,
            )

        assert result.success
        assert result.points == 50.0
        assert result.pnl_native == 50.0  # 50 points * 1.0 point_value
        assert result.pnl_base == 54.0  # 50 EUR * 1.08 = 54 USD
        assert result.native_currency == "EUR"
        assert result.exchange_rate == 1.08

    @pytest.mark.asyncio
    async def test_calculate_pnl_with_fallback_rate(self):
        """Test P&L calculation when fallback exchange rate is used."""
        service = PnLService()

        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.08
        mock_rate_result.is_fallback = True

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18050.0,
                lot_size=1.0,
            )

        assert result.success
        assert result.is_fallback_rate is True

    @pytest.mark.asyncio
    async def test_calculate_pnl_invalid_direction(self):
        """Test P&L calculation with invalid direction."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="INVALID",
            entry_price=15000.0,
            exit_price=15100.0,
            lot_size=1.0,
        )

        assert not result.success
        assert "Invalid direction" in result.error

    @pytest.mark.asyncio
    async def test_calculate_pnl_case_insensitive_direction(self):
        """Test P&L calculation accepts lowercase direction."""
        service = PnLService()

        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="long",
            entry_price=15000.0,
            exit_price=15100.0,
            lot_size=1.0,
        )

        assert result.success
        assert result.points == 100.0


class TestCalculateUnrealizedPnL:
    """Tests for the calculate_unrealized_pnl method."""

    def setup_method(self):
        """Reset singletons before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_long_profit(self):
        """Test unrealized P&L for profitable long position."""
        service = PnLService()

        result = await service.calculate_unrealized_pnl(
            instrument="NASDAQ",
            direction="LONG",
            entry_price=15000.0,
            lot_size=1.0,
            current_price=15100.0,
        )

        assert result.success
        assert result.points == 100.0
        assert result.pnl_native == 100.0

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_short_profit(self):
        """Test unrealized P&L for profitable short position."""
        service = PnLService()

        result = await service.calculate_unrealized_pnl(
            instrument="NASDAQ",
            direction="SHORT",
            entry_price=15100.0,
            lot_size=1.0,
            current_price=15000.0,
        )

        assert result.success
        assert result.points == 100.0
        assert result.pnl_native == 100.0

    @pytest.mark.asyncio
    async def test_calculate_unrealized_pnl_breakeven(self):
        """Test unrealized P&L at breakeven."""
        service = PnLService()

        result = await service.calculate_unrealized_pnl(
            instrument="NASDAQ",
            direction="LONG",
            entry_price=15000.0,
            lot_size=1.0,
            current_price=15000.0,
        )

        assert result.success
        assert result.points == 0.0
        assert result.pnl_native == 0.0


class TestCalculateRiskReward:
    """Tests for the calculate_risk_reward method."""

    def setup_method(self):
        """Reset singletons before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    def test_calculate_risk_reward_long_2_to_1(self):
        """Test risk/reward calculation for 2:1 long setup."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=95.0,  # 5 points risk
            tp_price=110.0,  # 10 points reward
            direction="LONG",
        )

        assert result.success
        assert result.risk_points == 5.0
        assert result.reward_points == 10.0
        assert result.risk_reward_ratio == 2.0

    def test_calculate_risk_reward_short_2_to_1(self):
        """Test risk/reward calculation for 2:1 short setup."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=105.0,  # 5 points risk
            tp_price=90.0,  # 10 points reward
            direction="SHORT",
        )

        assert result.success
        assert result.risk_points == 5.0
        assert result.reward_points == 10.0
        assert result.risk_reward_ratio == 2.0

    def test_calculate_risk_reward_1_to_1(self):
        """Test risk/reward calculation for 1:1 setup."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=95.0,
            tp_price=105.0,
            direction="LONG",
        )

        assert result.success
        assert result.risk_reward_ratio == 1.0

    def test_calculate_risk_reward_invalid_direction(self):
        """Test risk/reward with invalid direction."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=95.0,
            tp_price=110.0,
            direction="INVALID",
        )

        assert not result.success
        assert "Invalid direction" in result.error

    def test_calculate_risk_reward_invalid_sl_placement_long(self):
        """Test risk/reward with SL above entry for long (invalid)."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=105.0,  # SL above entry for long = invalid
            tp_price=110.0,
            direction="LONG",
        )

        assert not result.success
        assert "risk must be positive" in result.error

    def test_calculate_risk_reward_invalid_tp_placement_long(self):
        """Test risk/reward with TP below entry for long (invalid)."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=95.0,
            tp_price=95.0,  # TP below entry for long = invalid
            direction="LONG",
        )

        assert not result.success
        assert "reward must be positive" in result.error

    def test_calculate_risk_reward_case_insensitive(self):
        """Test risk/reward accepts lowercase direction."""
        service = PnLService()

        result = service.calculate_risk_reward(
            entry_price=100.0,
            sl_price=95.0,
            tp_price=110.0,
            direction="long",
        )

        assert result.success


class TestCalculatePositionSize:
    """Tests for the calculate_position_size method."""

    def setup_method(self):
        """Reset singletons before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    @pytest.mark.asyncio
    async def test_calculate_position_size_basic(self):
        """Test basic position size calculation."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=10000.0,
            risk_percent=1.0,  # Risk 1% = $100
            entry_price=15000.0,
            sl_price=14900.0,  # 100 point SL
            instrument="NASDAQ",
        )

        assert result.success
        assert result.risk_amount == 100.0  # 1% of 10000
        assert result.sl_distance == 100.0
        # lot_size = 100 / (100 * 1.0) = 1.0
        assert result.lot_size == 1.0

    @pytest.mark.asyncio
    async def test_calculate_position_size_higher_risk(self):
        """Test position size with higher risk percentage."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=10000.0,
            risk_percent=2.0,  # Risk 2% = $200
            entry_price=15000.0,
            sl_price=14900.0,  # 100 point SL
            instrument="NASDAQ",
        )

        assert result.success
        assert result.risk_amount == 200.0
        assert result.lot_size == 2.0

    @pytest.mark.asyncio
    async def test_calculate_position_size_tighter_stop(self):
        """Test position size with tighter stop loss."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=10000.0,
            risk_percent=1.0,  # Risk 1% = $100
            entry_price=15000.0,
            sl_price=14950.0,  # 50 point SL (tighter)
            instrument="NASDAQ",
        )

        assert result.success
        assert result.sl_distance == 50.0
        # lot_size = 100 / (50 * 1.0) = 2.0
        assert result.lot_size == 2.0

    @pytest.mark.asyncio
    async def test_calculate_position_size_zero_balance(self):
        """Test position size with zero balance."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=0.0,
            risk_percent=1.0,
            entry_price=15000.0,
            sl_price=14900.0,
            instrument="NASDAQ",
        )

        assert not result.success
        assert "balance must be positive" in result.error

    @pytest.mark.asyncio
    async def test_calculate_position_size_invalid_risk_percent(self):
        """Test position size with invalid risk percentage."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=10000.0,
            risk_percent=150.0,  # Over 100%
            entry_price=15000.0,
            sl_price=14900.0,
            instrument="NASDAQ",
        )

        assert not result.success
        assert "between 0 and 100" in result.error

    @pytest.mark.asyncio
    async def test_calculate_position_size_zero_sl_distance(self):
        """Test position size with zero SL distance."""
        service = PnLService()

        result = await service.calculate_position_size(
            account_balance=10000.0,
            risk_percent=1.0,
            entry_price=15000.0,
            sl_price=15000.0,  # Same as entry
            instrument="NASDAQ",
        )

        assert not result.success
        assert "cannot be zero" in result.error

    @pytest.mark.asyncio
    async def test_calculate_position_size_with_currency_conversion(self):
        """Test position size calculation with currency conversion."""
        service = PnLService()

        # Mock currency service for USD to EUR conversion
        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 0.93  # 1 USD = 0.93 EUR

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_position_size(
                account_balance=10000.0,  # USD
                risk_percent=1.0,  # Risk $100
                entry_price=18000.0,
                sl_price=17950.0,  # 50 point SL
                instrument="DAX",  # EUR instrument
            )

        assert result.success
        assert result.risk_amount == 100.0
        # risk_amount_native = 100 * 0.93 = 93 EUR
        # lot_size = 93 / (50 * 1.0) = 1.86
        assert result.lot_size == 1.86


class TestPnLResultDataclass:
    """Tests for PnLResult dataclass."""

    def test_pnl_result_success_property(self):
        """Test PnLResult success property."""
        result_success = PnLResult(
            pnl_native=100.0,
            pnl_base=108.0,
            native_currency="EUR",
            base_currency="USD",
            exchange_rate=1.08,
            points=100.0,
            point_value=1.0,
        )
        assert result_success.success is True

        result_error = PnLResult(
            pnl_native=0.0,
            pnl_base=0.0,
            native_currency="EUR",
            base_currency="USD",
            exchange_rate=1.0,
            points=0.0,
            point_value=1.0,
            error="Some error",
        )
        assert result_error.success is False


class TestRiskRewardResultDataclass:
    """Tests for RiskRewardResult dataclass."""

    def test_risk_reward_result_success_property(self):
        """Test RiskRewardResult success property."""
        result_success = RiskRewardResult(
            risk_points=5.0,
            reward_points=10.0,
            risk_reward_ratio=2.0,
        )
        assert result_success.success is True

        result_error = RiskRewardResult(
            risk_points=0.0,
            reward_points=0.0,
            risk_reward_ratio=0.0,
            error="Invalid setup",
        )
        assert result_error.success is False


class TestPositionSizeResultDataclass:
    """Tests for PositionSizeResult dataclass."""

    def test_position_size_result_success_property(self):
        """Test PositionSizeResult success property."""
        result_success = PositionSizeResult(
            lot_size=1.0,
            risk_amount=100.0,
            risk_percent=1.0,
            sl_distance=100.0,
        )
        assert result_success.success is True

        result_error = PositionSizeResult(
            lot_size=0.0,
            risk_amount=0.0,
            risk_percent=0.0,
            sl_distance=0.0,
            error="Invalid input",
        )
        assert result_error.success is False


class TestRateSourcePopulated:
    """Tests for rate_source field population in P&L calculations (AC4.5)."""

    def setup_method(self):
        """Reset singletons before each test."""
        reset_pnl_service()

    def teardown_method(self):
        """Clean up after each test."""
        reset_pnl_service()

    @pytest.mark.asyncio
    async def test_rate_source_populated_yfinance(self):
        """Test rate_source is populated with 'yfinance' when yfinance provides the rate.

        AC4.5: Verify rate_source field is correctly populated with the source name.
        """
        service = PnLService()

        # Mock currency service to return yfinance as the source
        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.08
        mock_rate_result.is_fallback = False
        mock_rate_result.source = "yfinance"

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18050.0,
                lot_size=1.0,
            )

        assert result.success is True
        assert result.rate_source == "yfinance"
        assert result.is_fallback_rate is False

    @pytest.mark.asyncio
    async def test_rate_source_populated_same_currency(self):
        """Test rate_source is 'same_currency' when no conversion is needed.

        AC4.5: Verify rate_source indicates same_currency when currencies match.
        """
        service = PnLService()

        # NASDAQ is a USD instrument, so no currency conversion needed
        result = await service.calculate_pnl(
            instrument="NASDAQ",
            direction="LONG",
            entry_price=15000.0,
            exit_price=15100.0,
            lot_size=1.0,
        )

        assert result.success is True
        assert result.rate_source == "same_currency"
        assert result.exchange_rate == 1.0

    @pytest.mark.asyncio
    async def test_rate_source_populated_exchangerate_api(self):
        """Test rate_source is populated with 'exchangerate-api' when that source provides the rate.

        AC4.5: Verify rate_source correctly shows exchangerate-api as the source.
        """
        service = PnLService()

        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.0850
        mock_rate_result.is_fallback = False
        mock_rate_result.source = "exchangerate-api"

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18050.0,
                lot_size=1.0,
            )

        assert result.success is True
        assert result.rate_source == "exchangerate-api"
        assert result.is_fallback_rate is False

    @pytest.mark.asyncio
    async def test_rate_source_populated_frankfurter(self):
        """Test rate_source is populated with 'frankfurter' when that source provides the rate.

        AC4.5: Verify rate_source correctly shows frankfurter as the source.
        """
        service = PnLService()

        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.0825
        mock_rate_result.is_fallback = False
        mock_rate_result.source = "frankfurter"

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="SHORT",
                entry_price=18050.0,
                exit_price=18000.0,
                lot_size=1.0,
            )

        assert result.success is True
        assert result.rate_source == "frankfurter"
        assert result.is_fallback_rate is False

    @pytest.mark.asyncio
    async def test_rate_source_populated_static_fallback(self):
        """Test rate_source is populated with 'static_fallback' when fallback rates are used.

        AC4.5: Verify rate_source correctly indicates when static fallback rates are used.
        """
        service = PnLService()

        mock_rate_result = MagicMock()
        mock_rate_result.success = True
        mock_rate_result.rate = 1.08
        mock_rate_result.is_fallback = True
        mock_rate_result.source = "static_fallback"

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18100.0,
                lot_size=1.0,
            )

        assert result.success is True
        assert result.rate_source == "static_fallback"
        assert result.is_fallback_rate is True

    @pytest.mark.asyncio
    async def test_rate_source_conversion_failed(self):
        """Test rate_source is 'conversion_failed' when currency conversion fails.

        AC4.5: Verify rate_source indicates conversion failure when no rate is available.
        """
        service = PnLService()

        mock_rate_result = MagicMock()
        mock_rate_result.success = False
        mock_rate_result.rate = None
        mock_rate_result.error = "No exchange rate data available"

        mock_currency_service = AsyncMock()
        mock_currency_service.get_exchange_rate = AsyncMock(return_value=mock_rate_result)

        with patch("services.pnl_service.get_currency_service", return_value=mock_currency_service):
            result = await service.calculate_pnl(
                instrument="DAX",
                direction="LONG",
                entry_price=18000.0,
                exit_price=18050.0,
                lot_size=1.0,
            )

        # P&L calculation still succeeds but uses 1:1 rate
        assert result.success is True
        assert result.rate_source == "conversion_failed"
        assert result.exchange_rate == 1.0
