"""
AI Action Service for detecting and executing AI-requested actions.

This module provides parsing and validation for AI-generated action requests
including adding trades, adding accounts, and editing existing records.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from config import get_logger

logger = get_logger(__name__)


class AIActionType(str, Enum):
    """Types of actions that can be requested by the AI."""

    ADD_TRADE = "add_trade"
    ADD_ACCOUNT = "add_account"
    EDIT_TRADE = "edit_trade"
    EDIT_ACCOUNT = "edit_account"
    NONE = "none"


# Mapping from string action names to AIActionType enum
ACTION_TYPE_MAP: dict[str, AIActionType] = {
    "add_trade": AIActionType.ADD_TRADE,
    "add_account": AIActionType.ADD_ACCOUNT,
    "edit_trade": AIActionType.EDIT_TRADE,
    "edit_account": AIActionType.EDIT_ACCOUNT,
    "none": AIActionType.NONE,
}


@dataclass
class AIAction:
    """
    Represents an action requested by the AI.

    Attributes:
        action_type: The type of action to perform.
        data: Dictionary containing action-specific data.
        confidence: Confidence score (0.0-1.0) for this action.
        confirmation_message: Human-readable message for user confirmation.
        requires_confirmation: Whether user confirmation is required before execution.
    """

    action_type: AIActionType
    data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    confirmation_message: str = ""
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the AIAction to a dictionary for serialization.

        Returns:
            dict: Dictionary representation of the action.
        """
        return {
            "action_type": self.action_type.value,
            "data": self.data,
            "confidence": self.confidence,
            "confirmation_message": self.confirmation_message,
            "requires_confirmation": self.requires_confirmation,
        }


class AIActionService:
    """
    Service for parsing and validating AI-generated action requests.

    This service extracts structured action data from AI responses and
    validates the data before execution.
    """

    # Regex pattern to find JSON code blocks in markdown
    JSON_CODE_BLOCK_PATTERN = re.compile(
        r"```json\s*([\s\S]*?)\s*```",
        re.IGNORECASE,
    )

    # Regex pattern to find raw JSON objects
    RAW_JSON_PATTERN = re.compile(
        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
        re.MULTILINE,
    )

    # Required fields for trade data
    TRADE_REQUIRED_FIELDS = ["instrument", "direction", "entry_price"]

    # Required fields for account data
    ACCOUNT_REQUIRED_FIELDS = ["name", "starting_balance"]

    def __init__(self) -> None:
        """Initialize the AI Action Service."""
        logger.info("AIActionService initialized")

    def parse_ai_response(self, response: str) -> Optional[AIAction]:
        """
        Parse an AI response and extract any action requests.

        Looks for JSON action blocks in the response, first checking for
        markdown code blocks (```json ... ```) and then falling back to
        raw JSON objects.

        Args:
            response: The AI-generated response text.

        Returns:
            Optional[AIAction]: Parsed action if found and valid, None otherwise.
        """
        if not response:
            logger.debug("Empty response provided to parse_ai_response")
            return None

        # First try to find JSON code blocks
        json_str = self._extract_json_from_code_block(response)

        # If no code block found, try to find raw JSON
        if json_str is None:
            json_str = self._extract_raw_json(response)

        # If no JSON found at all, return None
        if json_str is None:
            logger.debug("No JSON action found in AI response")
            return None

        # Parse the JSON and create an AIAction
        return self._parse_json_to_action(json_str)

    def _extract_json_from_code_block(self, response: str) -> Optional[str]:
        """
        Extract JSON from a markdown code block.

        Args:
            response: The AI response text.

        Returns:
            Optional[str]: The extracted JSON string or None.
        """
        match = self.JSON_CODE_BLOCK_PATTERN.search(response)
        if match:
            return match.group(1).strip()
        return None

    def _extract_raw_json(self, response: str) -> Optional[str]:
        """
        Extract raw JSON object from response text.

        Args:
            response: The AI response text.

        Returns:
            Optional[str]: The extracted JSON string or None.
        """
        # Find all potential JSON objects
        matches = self.RAW_JSON_PATTERN.findall(response)

        for match in matches:
            # Check if this looks like an action JSON
            if '"action"' in match:
                return match

        return None

    def _parse_json_to_action(self, json_str: str) -> Optional[AIAction]:
        """
        Parse a JSON string into an AIAction object.

        Args:
            json_str: The JSON string to parse.

        Returns:
            Optional[AIAction]: The parsed action or None if invalid.
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse JSON action",
                error=str(e),
                json_preview=json_str[:100] if len(json_str) > 100 else json_str,
            )
            return None

        # Validate that this is an action JSON
        if not isinstance(data, dict) or "action" not in data:
            logger.debug("JSON does not contain 'action' field")
            return None

        # Map the action string to an AIActionType
        action_str = data.get("action", "").lower()
        action_type = ACTION_TYPE_MAP.get(action_str, AIActionType.NONE)

        if action_type == AIActionType.NONE and action_str != "none":
            logger.warning(
                "Unknown action type in AI response",
                action=action_str,
            )
            return None

        # Extract action data
        action_data = data.get("data", {})
        if not isinstance(action_data, dict):
            action_data = {}

        # Extract confirmation message
        confirmation_message = data.get("confirmation_message", "")
        if not isinstance(confirmation_message, str):
            confirmation_message = str(confirmation_message)

        # Extract confidence (default to 1.0 if not provided)
        confidence = data.get("confidence", 1.0)
        if not isinstance(confidence, (int, float)):
            confidence = 1.0
        confidence = max(0.0, min(1.0, float(confidence)))

        # Extract requires_confirmation (default to True)
        requires_confirmation = data.get("requires_confirmation", True)
        if not isinstance(requires_confirmation, bool):
            requires_confirmation = True

        action = AIAction(
            action_type=action_type,
            data=action_data,
            confidence=confidence,
            confirmation_message=confirmation_message,
            requires_confirmation=requires_confirmation,
        )

        logger.info(
            "Parsed AI action",
            action_type=action_type.value,
            confidence=confidence,
            has_data=bool(action_data),
        )

        return action

    def validate_trade_data(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate trade data for required fields and types.

        Required fields: instrument, direction, entry_price

        Args:
            data: Dictionary containing trade data.

        Returns:
            tuple[bool, list[str]]: (is_valid, list of error messages)
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            return False, ["Trade data must be a dictionary"]

        # Check required fields
        for field_name in self.TRADE_REQUIRED_FIELDS:
            if field_name not in data:
                errors.append(f"Missing required field: {field_name}")
            elif data[field_name] is None:
                errors.append(f"Field '{field_name}' cannot be null")

        # Validate direction if present
        if "direction" in data and data["direction"] is not None:
            direction = str(data["direction"]).lower()
            if direction not in ("long", "short"):
                errors.append(
                    f"Invalid direction: {data['direction']}. Must be 'long' or 'short'"
                )

        # Validate entry_price is a number if present
        if "entry_price" in data and data["entry_price"] is not None:
            try:
                price = float(data["entry_price"])
                if price <= 0:
                    errors.append("Entry price must be positive")
            except (ValueError, TypeError):
                errors.append(
                    f"Invalid entry_price: {data['entry_price']}. Must be a number"
                )

        # Validate optional price fields if present
        for price_field in ["sl_price", "tp_price", "exit_price"]:
            if price_field in data and data[price_field] is not None:
                try:
                    price = float(data[price_field])
                    if price <= 0:
                        errors.append(f"{price_field} must be positive")
                except (ValueError, TypeError):
                    errors.append(
                        f"Invalid {price_field}: {data[price_field]}. Must be a number"
                    )

        # Validate lot_size if present
        if "lot_size" in data and data["lot_size"] is not None:
            try:
                lot_size = float(data["lot_size"])
                if lot_size <= 0:
                    errors.append("Lot size must be positive")
            except (ValueError, TypeError):
                errors.append(
                    f"Invalid lot_size: {data['lot_size']}. Must be a number"
                )

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning(
                "Trade data validation failed",
                error_count=len(errors),
                errors=errors,
            )
        else:
            logger.debug("Trade data validation passed")

        return is_valid, errors

    def validate_account_data(self, data: dict[str, Any]) -> tuple[bool, list[str]]:
        """
        Validate account data for required fields and types.

        Required fields: name, starting_balance

        Args:
            data: Dictionary containing account data.

        Returns:
            tuple[bool, list[str]]: (is_valid, list of error messages)
        """
        errors: list[str] = []

        if not isinstance(data, dict):
            return False, ["Account data must be a dictionary"]

        # Check required fields
        for field_name in self.ACCOUNT_REQUIRED_FIELDS:
            if field_name not in data:
                errors.append(f"Missing required field: {field_name}")
            elif data[field_name] is None:
                errors.append(f"Field '{field_name}' cannot be null")

        # Validate name is a non-empty string if present
        if "name" in data and data["name"] is not None:
            if not isinstance(data["name"], str):
                errors.append(f"Invalid name: {data['name']}. Must be a string")
            elif len(data["name"].strip()) == 0:
                errors.append("Account name cannot be empty")

        # Validate starting_balance is a number if present
        if "starting_balance" in data and data["starting_balance"] is not None:
            try:
                balance = float(data["starting_balance"])
                if balance < 0:
                    errors.append("Starting balance cannot be negative")
            except (ValueError, TypeError):
                errors.append(
                    f"Invalid starting_balance: {data['starting_balance']}. "
                    "Must be a number"
                )

        # Validate currency if present
        if "currency" in data and data["currency"] is not None:
            if not isinstance(data["currency"], str):
                errors.append(f"Invalid currency: {data['currency']}. Must be a string")
            elif len(data["currency"].strip()) == 0:
                errors.append("Currency cannot be empty")

        is_valid = len(errors) == 0

        if not is_valid:
            logger.warning(
                "Account data validation failed",
                error_count=len(errors),
                errors=errors,
            )
        else:
            logger.debug("Account data validation passed")

        return is_valid, errors


# Module-level singleton instance
_ai_action_service: Optional[AIActionService] = None


def get_ai_action_service() -> AIActionService:
    """
    Get or create the global AIActionService instance.

    Returns:
        AIActionService: The global AI action service singleton.
    """
    global _ai_action_service
    if _ai_action_service is None:
        _ai_action_service = AIActionService()
    return _ai_action_service


def reset_ai_action_service() -> None:
    """
    Reset the global AIActionService instance.

    Useful for testing or reconfiguration.
    """
    global _ai_action_service
    _ai_action_service = None
