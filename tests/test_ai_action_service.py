"""
Tests for the AI Action Service.

This module tests:
- Parsing AI responses with JSON code blocks
- Parsing AI responses with raw JSON
- Handling responses without actions
- Trade data validation
- Account data validation
- Singleton pattern
"""

import pytest

from services.ai_action_service import (
    AIAction,
    AIActionService,
    AIActionType,
    get_ai_action_service,
    reset_ai_action_service,
)


@pytest.fixture
def service():
    """Provide a fresh AIActionService instance for each test."""
    return AIActionService()


@pytest.fixture(autouse=True)
def reset_service_singleton():
    """Reset the global service singleton before and after each test."""
    reset_ai_action_service()
    yield
    reset_ai_action_service()


class TestParseAIResponseWithJsonCodeBlock:
    """Tests for parsing AI responses with JSON code blocks."""

    def test_parse_add_trade_action(self, service):
        """Test parsing an add_trade action from a JSON code block."""
        response = """
        I'll add that trade for you.

        ```json
        {
            "action": "add_trade",
            "data": {
                "instrument": "DAX",
                "direction": "long",
                "entry_price": 18500.00,
                "lot_size": 0.5,
                "sl_price": 18400.00,
                "tp_price": 18700.00
            },
            "confirmation_message": "I'll add a LONG trade on DAX at 18500..."
        }
        ```

        Let me know if you want to confirm this.
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.ADD_TRADE
        assert action.data["instrument"] == "DAX"
        assert action.data["direction"] == "long"
        assert action.data["entry_price"] == 18500.00
        assert action.data["lot_size"] == 0.5
        assert action.data["sl_price"] == 18400.00
        assert action.data["tp_price"] == 18700.00
        assert "LONG" in action.confirmation_message

    def test_parse_add_account_action(self, service):
        """Test parsing an add_account action from a JSON code block."""
        response = """
        Sure, I'll create that account.

        ```json
        {
            "action": "add_account",
            "data": {
                "name": "Demo Account",
                "starting_balance": 10000.00,
                "currency": "USD"
            },
            "confirmation_message": "Creating Demo Account with $10,000 starting balance"
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.ADD_ACCOUNT
        assert action.data["name"] == "Demo Account"
        assert action.data["starting_balance"] == 10000.00
        assert action.data["currency"] == "USD"

    def test_parse_edit_trade_action(self, service):
        """Test parsing an edit_trade action from a JSON code block."""
        response = """
        ```json
        {
            "action": "edit_trade",
            "data": {
                "trade_id": 123,
                "sl_price": 18350.00
            },
            "confirmation_message": "Updating stop loss to 18350"
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.EDIT_TRADE
        assert action.data["trade_id"] == 123
        assert action.data["sl_price"] == 18350.00

    def test_parse_with_confidence_and_requires_confirmation(self, service):
        """Test parsing action with confidence and requires_confirmation fields."""
        response = """
        ```json
        {
            "action": "add_trade",
            "data": {
                "instrument": "NASDAQ",
                "direction": "short",
                "entry_price": 19000.00
            },
            "confirmation_message": "Adding short trade on NASDAQ",
            "confidence": 0.85,
            "requires_confirmation": false
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.confidence == 0.85
        assert action.requires_confirmation is False


class TestParseAIResponseWithRawJson:
    """Tests for parsing AI responses with raw JSON."""

    def test_parse_raw_json_action(self, service):
        """Test parsing an action from raw JSON in response."""
        response = """
        Based on your request, here's what I'll do:
        {"action": "add_trade", "data": {"instrument": "EURUSD", "direction": "long", "entry_price": 1.0850}, "confirmation_message": "Adding EURUSD long trade"}
        Please confirm.
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.ADD_TRADE
        assert action.data["instrument"] == "EURUSD"
        assert action.data["direction"] == "long"
        assert action.data["entry_price"] == 1.0850

    def test_parse_raw_json_with_nested_objects(self, service):
        """Test parsing raw JSON with nested data structure."""
        response = """
        Here's the action:
        {"action": "add_account", "data": {"name": "Live Trading", "starting_balance": 50000, "currency": "EUR"}, "confirmation_message": "Creating account"}
        Done!
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.ADD_ACCOUNT
        assert action.data["name"] == "Live Trading"
        assert action.data["starting_balance"] == 50000

    def test_ignores_non_action_json(self, service):
        """Test that non-action JSON objects are ignored."""
        response = """
        Here's some data: {"price": 100, "volume": 500}
        But no action here.
        """
        action = service.parse_ai_response(response)
        assert action is None


class TestParseAIResponseNoAction:
    """Tests for responses without actions."""

    def test_no_action_in_plain_text(self, service):
        """Test that plain text responses return None."""
        response = "Sure, I can help you with that. What trade would you like to add?"
        action = service.parse_ai_response(response)
        assert action is None

    def test_no_action_in_empty_response(self, service):
        """Test that empty responses return None."""
        action = service.parse_ai_response("")
        assert action is None

    def test_no_action_in_none_response(self, service):
        """Test that None responses return None."""
        action = service.parse_ai_response(None)
        assert action is None

    def test_no_action_with_malformed_json(self, service):
        """Test that malformed JSON returns None."""
        response = """
        ```json
        {"action": "add_trade", "data": {incomplete json
        ```
        """
        action = service.parse_ai_response(response)
        assert action is None

    def test_no_action_with_unknown_action_type(self, service):
        """Test that unknown action types return None."""
        response = """
        ```json
        {"action": "unknown_action", "data": {}}
        ```
        """
        action = service.parse_ai_response(response)
        assert action is None

    def test_no_action_when_json_missing_action_field(self, service):
        """Test that JSON without 'action' field returns None."""
        response = """
        ```json
        {"data": {"instrument": "DAX"}, "confirmation_message": "test"}
        ```
        """
        action = service.parse_ai_response(response)
        assert action is None


class TestValidateTradeDataValid:
    """Tests for valid trade data validation."""

    def test_valid_minimal_trade_data(self, service):
        """Test validation of minimal valid trade data."""
        data = {
            "instrument": "DAX",
            "direction": "long",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_valid_complete_trade_data(self, service):
        """Test validation of complete trade data."""
        data = {
            "instrument": "NASDAQ",
            "direction": "short",
            "entry_price": 19000.00,
            "lot_size": 1.5,
            "sl_price": 19100.00,
            "tp_price": 18800.00,
            "exit_price": 18850.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_valid_trade_with_string_prices(self, service):
        """Test validation accepts string prices that can be converted."""
        data = {
            "instrument": "EURUSD",
            "direction": "long",
            "entry_price": "1.0850",
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is True
        assert len(errors) == 0


class TestValidateTradeDataMissingRequired:
    """Tests for trade data validation with missing required fields."""

    def test_missing_instrument(self, service):
        """Test validation fails without instrument."""
        data = {
            "direction": "long",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("instrument" in e for e in errors)

    def test_missing_direction(self, service):
        """Test validation fails without direction."""
        data = {
            "instrument": "DAX",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("direction" in e for e in errors)

    def test_missing_entry_price(self, service):
        """Test validation fails without entry_price."""
        data = {
            "instrument": "DAX",
            "direction": "long",
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("entry_price" in e for e in errors)

    def test_multiple_missing_fields(self, service):
        """Test validation reports all missing fields."""
        data = {}
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert len(errors) >= 3

    def test_invalid_direction(self, service):
        """Test validation fails with invalid direction."""
        data = {
            "instrument": "DAX",
            "direction": "sideways",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("direction" in e.lower() for e in errors)

    def test_invalid_entry_price_type(self, service):
        """Test validation fails with non-numeric entry_price."""
        data = {
            "instrument": "DAX",
            "direction": "long",
            "entry_price": "not a number",
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("entry_price" in e for e in errors)

    def test_negative_entry_price(self, service):
        """Test validation fails with negative entry_price."""
        data = {
            "instrument": "DAX",
            "direction": "long",
            "entry_price": -100,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("positive" in e.lower() for e in errors)

    def test_null_required_field(self, service):
        """Test validation fails with null required field."""
        data = {
            "instrument": None,
            "direction": "long",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is False
        assert any("null" in e.lower() for e in errors)


class TestValidateAccountDataValid:
    """Tests for valid account data validation."""

    def test_valid_minimal_account_data(self, service):
        """Test validation of minimal valid account data."""
        data = {
            "name": "My Account",
            "starting_balance": 10000.00,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_valid_complete_account_data(self, service):
        """Test validation of complete account data."""
        data = {
            "name": "Demo Trading",
            "starting_balance": 50000.00,
            "currency": "EUR",
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_valid_account_with_zero_balance(self, service):
        """Test validation accepts zero starting balance."""
        data = {
            "name": "New Account",
            "starting_balance": 0,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is True
        assert len(errors) == 0


class TestValidateAccountDataMissingRequired:
    """Tests for account data validation with missing required fields."""

    def test_missing_name(self, service):
        """Test validation fails without name."""
        data = {
            "starting_balance": 10000.00,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("name" in e for e in errors)

    def test_missing_starting_balance(self, service):
        """Test validation fails without starting_balance."""
        data = {
            "name": "My Account",
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("starting_balance" in e for e in errors)

    def test_empty_name(self, service):
        """Test validation fails with empty name."""
        data = {
            "name": "   ",
            "starting_balance": 10000.00,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("empty" in e.lower() for e in errors)

    def test_invalid_starting_balance_type(self, service):
        """Test validation fails with non-numeric starting_balance."""
        data = {
            "name": "My Account",
            "starting_balance": "lots of money",
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("starting_balance" in e for e in errors)

    def test_negative_starting_balance(self, service):
        """Test validation fails with negative starting_balance."""
        data = {
            "name": "My Account",
            "starting_balance": -1000,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("negative" in e.lower() for e in errors)

    def test_null_name(self, service):
        """Test validation fails with null name."""
        data = {
            "name": None,
            "starting_balance": 10000.00,
        }
        is_valid, errors = service.validate_account_data(data)

        assert is_valid is False
        assert any("null" in e.lower() for e in errors)


class TestSingletonPattern:
    """Tests for the singleton pattern."""

    def test_get_ai_action_service_returns_same_instance(self):
        """Test that get_ai_action_service returns the same instance."""
        service1 = get_ai_action_service()
        service2 = get_ai_action_service()

        assert service1 is service2

    def test_reset_ai_action_service_creates_new_instance(self):
        """Test that reset creates a new instance."""
        service1 = get_ai_action_service()
        reset_ai_action_service()
        service2 = get_ai_action_service()

        assert service1 is not service2

    def test_multiple_resets(self):
        """Test multiple reset and get cycles."""
        instances = []
        for _ in range(3):
            reset_ai_action_service()
            instances.append(get_ai_action_service())

        # All instances should be different
        assert instances[0] is not instances[1]
        assert instances[1] is not instances[2]


class TestAIAction:
    """Tests for the AIAction dataclass."""

    def test_to_dict(self):
        """Test AIAction to_dict serialization."""
        action = AIAction(
            action_type=AIActionType.ADD_TRADE,
            data={"instrument": "DAX", "direction": "long", "entry_price": 18500},
            confidence=0.9,
            confirmation_message="Adding trade",
            requires_confirmation=True,
        )
        result = action.to_dict()

        assert result["action_type"] == "add_trade"
        assert result["data"]["instrument"] == "DAX"
        assert result["confidence"] == 0.9
        assert result["confirmation_message"] == "Adding trade"
        assert result["requires_confirmation"] is True

    def test_default_values(self):
        """Test AIAction default values."""
        action = AIAction(action_type=AIActionType.NONE)

        assert action.data == {}
        assert action.confidence == 1.0
        assert action.confirmation_message == ""
        assert action.requires_confirmation is True


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_validate_trade_data_not_dict(self, service):
        """Test validation handles non-dict input."""
        is_valid, errors = service.validate_trade_data("not a dict")

        assert is_valid is False
        assert any("dictionary" in e.lower() for e in errors)

    def test_validate_account_data_not_dict(self, service):
        """Test validation handles non-dict input."""
        is_valid, errors = service.validate_account_data(["a", "list"])

        assert is_valid is False
        assert any("dictionary" in e.lower() for e in errors)

    def test_confidence_clamped_to_range(self, service):
        """Test that confidence values are clamped to 0.0-1.0."""
        response = """
        ```json
        {
            "action": "add_trade",
            "data": {"instrument": "DAX", "direction": "long", "entry_price": 18500},
            "confidence": 1.5
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.confidence == 1.0

    def test_negative_confidence_clamped(self, service):
        """Test that negative confidence is clamped to 0.0."""
        response = """
        ```json
        {
            "action": "add_trade",
            "data": {"instrument": "DAX", "direction": "long", "entry_price": 18500},
            "confidence": -0.5
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.confidence == 0.0

    def test_case_insensitive_action_type(self, service):
        """Test that action types are case-insensitive."""
        response = """
        ```json
        {
            "action": "ADD_TRADE",
            "data": {"instrument": "DAX", "direction": "long", "entry_price": 18500}
        }
        ```
        """
        action = service.parse_ai_response(response)

        assert action is not None
        assert action.action_type == AIActionType.ADD_TRADE

    def test_direction_case_insensitive(self, service):
        """Test that direction validation is case-insensitive."""
        data = {
            "instrument": "DAX",
            "direction": "LONG",
            "entry_price": 18500.00,
        }
        is_valid, errors = service.validate_trade_data(data)

        assert is_valid is True
