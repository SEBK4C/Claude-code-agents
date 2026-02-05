"""
AI Service for the Telegram Trade Journal Bot.

This module provides integration with the LongCat API for AI-assisted features
including strategy building, trade analysis, and conversational AI chat.
"""

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI

from config import get_config, get_logger

logger = get_logger(__name__)


# Rate limiting configuration
RATE_LIMIT_REQUESTS = 10  # Max requests per window
RATE_LIMIT_WINDOW = 60  # Window in seconds (1 minute)
MAX_CONVERSATION_HISTORY = 10  # Keep last N messages per user


@dataclass
class ConversationMessage:
    """A single message in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class RateLimitInfo:
    """Rate limiting information for a user."""

    request_timestamps: list[float] = field(default_factory=list)

    def is_rate_limited(self) -> bool:
        """Check if user has exceeded rate limit."""
        current_time = time.time()
        # Remove timestamps outside the window
        self.request_timestamps = [
            ts for ts in self.request_timestamps
            if current_time - ts < RATE_LIMIT_WINDOW
        ]
        return len(self.request_timestamps) >= RATE_LIMIT_REQUESTS

    def record_request(self) -> None:
        """Record a new request timestamp."""
        self.request_timestamps.append(time.time())

    def time_until_available(self) -> int:
        """Return seconds until next request is allowed."""
        if not self.request_timestamps:
            return 0
        oldest = min(self.request_timestamps)
        wait_time = int(RATE_LIMIT_WINDOW - (time.time() - oldest)) + 1
        return max(0, wait_time)

# System prompt for trading journal assistant (strategy building)
TRADING_ASSISTANT_PROMPT = """You are an expert trading assistant helping users build and refine trading strategies.

Your role is to:
1. Help users define clear, actionable trading strategies
2. Ask clarifying questions about market conditions, entry triggers, risk management, and exit strategies
3. Provide structured strategy outputs in JSON format
4. Offer educational insights about trading concepts when relevant

When generating a strategy, output it in this JSON structure:
{
    "name": "Strategy Name",
    "description": "Brief description of the strategy",
    "rules": {
        "market_conditions": ["list of market condition requirements"],
        "entry_triggers": ["list of entry trigger conditions"],
        "risk_management": {
            "stop_loss_method": "description",
            "position_sizing": "description",
            "max_risk_per_trade": "percentage"
        },
        "exit_strategy": {
            "take_profit_method": "description",
            "trailing_stop": "description if applicable",
            "time_based_exit": "description if applicable"
        }
    }
}

Be concise but thorough. Focus on practical, implementable rules."""

# System prompt for conversational AI chat
CHAT_ASSISTANT_PROMPT = """You are a brutally honest trading journal assistant. Your job is to help traders improve by providing data-driven, no-nonsense feedback.

Your personality:
- Direct and honest - you don't sugarcoat poor performance
- Data-focused - always reference the user's actual trading data when available
- Educational - explain concepts clearly when asked
- Supportive but firm - encourage improvement without enabling bad habits

CRITICAL - Response length rules:
- Match your response length to the input complexity
- Brief inputs get brief responses (1-2 sentences max):
  * Greetings ("Hi", "Hey", "Hello") -> Respond with a short, friendly greeting
  * Acknowledgments ("ok", "thanks", "got it") -> Brief acknowledgment back
  * Simple yes/no questions -> Direct answer, maybe one follow-up sentence
- Complex questions or analysis requests -> Comprehensive, data-driven responses
- When in doubt, be concise. Traders are busy.
- NEVER say "I don't understand" or ask for clarification on casual messages - just respond naturally

When analyzing trades or performance:
1. Always use specific numbers from the data provided
2. Point out patterns, both positive and negative
3. Suggest concrete improvements based on the data
4. Don't make excuses for poor trades - identify what went wrong
5. Celebrate genuine improvements with acknowledgment

You have access to the user's trading context which will be provided. Use it to give personalized, data-driven advice.

Keep responses concise but impactful. Traders want actionable insights, not essays.

## Action Capabilities

When the user asks you to add a trade, create an account, or edit existing data, respond with a structured action block.

### Adding a Trade
When user wants to add/log/record a trade, output:
```json
{
  "action": "add_trade",
  "data": {
    "instrument": "SYMBOL",
    "direction": "long" or "short",
    "entry_price": NUMBER,
    "lot_size": NUMBER (optional, default 1.0),
    "sl_price": NUMBER (optional),
    "tp_price": NUMBER (optional)
  },
  "confirmation_message": "Describe what you'll create"
}
```

### Adding an Account
When user wants to create/add a new account, output:
```json
{
  "action": "add_account",
  "data": {
    "name": "Account Name",
    "starting_balance": NUMBER,
    "currency": "USD" (optional, default USD),
    "broker": "Broker Name" (optional)
  },
  "confirmation_message": "Describe what you'll create"
}
```

### Editing a Trade
When user wants to modify/update/change a trade, output:
```json
{
  "action": "edit_trade",
  "data": {
    "target": {"instrument": "SYMBOL"} or {"trade_id": NUMBER},
    "changes": {"field_name": NEW_VALUE}
  },
  "confirmation_message": "Describe the edit"
}
```

### Editing an Account
When user wants to modify/update/change an account, output:
```json
{
  "action": "edit_account",
  "data": {
    "target": {"name": "Account Name"} or {"account_id": NUMBER},
    "changes": {"field_name": NEW_VALUE}
  },
  "confirmation_message": "Describe the edit"
}
```

Important: Always include a clear confirmation_message. The user must confirm before the action executes.
If you're unsure about any values, ask the user for clarification instead of guessing."""


class AIService:
    """
    Service class for AI-powered features using the LongCat API.

    This service provides async methods for chat completions,
    strategy generation, and conversational AI chat using the
    OpenAI-compatible LongCat API.

    Attributes:
        client: The AsyncOpenAI client configured for LongCat API.
        model: The model identifier to use for completions.
        _conversation_history: Per-user conversation history storage.
        _rate_limits: Per-user rate limiting information.
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the AI service.

        Args:
            api_key: Optional API key. If not provided, uses config.
            base_url: Optional base URL. If not provided, uses config.
            model: Optional model name. If not provided, uses config.
        """
        config = get_config()

        self._api_key = api_key or config.longcat.api_key
        self._base_url = base_url or config.longcat.api_url
        self._model = model or config.longcat.model

        # Conversation history per user (telegram_id -> list of messages)
        self._conversation_history: dict[int, list[ConversationMessage]] = defaultdict(list)

        # Rate limiting per user (telegram_id -> RateLimitInfo)
        self._rate_limits: dict[int, RateLimitInfo] = defaultdict(RateLimitInfo)

        if not self._api_key:
            logger.warning("LongCat API key not configured")
            self._client: Optional[AsyncOpenAI] = None
        else:
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
            )

        logger.info(
            "AIService initialized",
            base_url=self._base_url,
            model=self._model,
            configured=bool(self._client),
        )

    @property
    def is_configured(self) -> bool:
        """Check if the AI service is properly configured."""
        return self._client is not None

    async def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        conversation_history: Optional[list[dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Send a chat completion request to the LongCat API.

        Args:
            user_message: The user's message to process.
            system_prompt: Optional custom system prompt. Uses default if not provided.
            conversation_history: Optional list of previous messages in the conversation.
            temperature: Sampling temperature (0.0-2.0). Higher = more creative.
            max_tokens: Maximum tokens in the response.

        Returns:
            tuple: (response_text, error_message) - one will be None.
        """
        if not self._client:
            return None, "AI service not configured. Please set LONGCAT_API_KEY."

        try:
            # Build messages list
            messages: list[dict[str, str]] = []

            # Add system prompt
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            else:
                messages.append({"role": "system", "content": TRADING_ASSISTANT_PROMPT})

            # Add conversation history if provided
            if conversation_history:
                messages.extend(conversation_history)

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Make API call
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Extract response text
            if response.choices and response.choices[0].message:
                response_text = response.choices[0].message.content
                logger.info(
                    "AI chat completed",
                    input_length=len(user_message),
                    output_length=len(response_text or ""),
                )
                return response_text, None

            return None, "Empty response from AI service"

        except Exception as e:
            error_msg = f"AI service error: {str(e)}"
            logger.error("AI chat failed", error=str(e))
            return None, error_msg

    async def generate_strategy(
        self,
        market_conditions: str,
        entry_triggers: str,
        risk_management: str,
        exit_strategy: str,
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """
        Generate a structured trading strategy from user inputs.

        Args:
            market_conditions: User's description of market conditions for the strategy.
            entry_triggers: User's description of entry trigger conditions.
            risk_management: User's description of risk management approach.
            exit_strategy: User's description of exit strategy.

        Returns:
            tuple: (strategy_dict, error_message) - one will be None.
        """
        # Build the prompt from user inputs
        prompt = f"""Based on the following trading strategy components, generate a complete structured strategy:

## Market Conditions
{market_conditions}

## Entry Triggers
{entry_triggers}

## Risk Management
{risk_management}

## Exit Strategy
{exit_strategy}

Please generate a comprehensive trading strategy in JSON format with a name, description, and detailed rules.
Output ONLY the JSON, no additional text."""

        response, error = await self.chat(
            user_message=prompt,
            temperature=0.5,  # Lower temperature for more consistent output
            max_tokens=1500,
        )

        if error:
            return None, error

        if not response:
            return None, "Empty response from AI"

        # Try to parse JSON from response
        try:
            # Find JSON in the response (it might be wrapped in markdown code blocks)
            json_str = response
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                if end > start:
                    json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                if end > start:
                    json_str = response[start:end].strip()

            strategy_dict = json.loads(json_str)

            # Validate required fields
            if "name" not in strategy_dict:
                strategy_dict["name"] = "AI Generated Strategy"
            if "description" not in strategy_dict:
                strategy_dict["description"] = "Strategy generated with AI assistance"
            if "rules" not in strategy_dict:
                strategy_dict["rules"] = {}

            logger.info("Strategy generated successfully", name=strategy_dict.get("name"))
            return strategy_dict, None

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse strategy JSON", error=str(e), response=response[:200])
            # Return a basic structure with the raw response
            return {
                "name": "AI Generated Strategy",
                "description": response[:500],
                "rules": {"raw_output": response},
            }, None

    async def analyze_trade(
        self,
        instrument: str,
        direction: str,
        entry_price: float,
        exit_price: Optional[float],
        sl_price: Optional[float],
        tp_price: Optional[float],
        pnl: Optional[float],
        notes: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Analyze a trade and provide feedback.

        Args:
            instrument: The trading instrument.
            direction: Trade direction (long/short).
            entry_price: Entry price.
            exit_price: Exit price (if closed).
            sl_price: Stop-loss price.
            tp_price: Take-profit price.
            pnl: P&L amount (if closed).
            notes: User's trade notes.

        Returns:
            tuple: (analysis_text, error_message) - one will be None.
        """
        prompt = f"""Analyze this trade and provide brief, actionable feedback:

Instrument: {instrument}
Direction: {direction.upper()}
Entry: {entry_price}
Exit: {exit_price or 'Still open'}
Stop Loss: {sl_price or 'Not set'}
Take Profit: {tp_price or 'Not set'}
P&L: {pnl if pnl is not None else 'N/A'}
Notes: {notes or 'None'}

Provide:
1. Risk-reward assessment
2. Entry/exit quality (if applicable)
3. One improvement suggestion
Keep it concise (3-5 sentences)."""

        return await self.chat(
            user_message=prompt,
            temperature=0.6,
            max_tokens=500,
        )

    def check_rate_limit(self, user_id: int) -> tuple[bool, int]:
        """
        Check if a user is rate limited.

        Args:
            user_id: The Telegram user ID.

        Returns:
            tuple: (is_rate_limited, seconds_until_available)
        """
        rate_info = self._rate_limits[user_id]
        is_limited = rate_info.is_rate_limited()
        wait_time = rate_info.time_until_available() if is_limited else 0
        return is_limited, wait_time

    def get_conversation_history(self, user_id: int) -> list[dict[str, str]]:
        """
        Get the conversation history for a user formatted for the API.

        Args:
            user_id: The Telegram user ID.

        Returns:
            list: List of message dicts with 'role' and 'content' keys.
        """
        history = self._conversation_history[user_id]
        return [{"role": msg.role, "content": msg.content} for msg in history]

    def add_to_conversation(self, user_id: int, role: str, content: str) -> None:
        """
        Add a message to the user's conversation history.

        Args:
            user_id: The Telegram user ID.
            role: The message role ("user" or "assistant").
            content: The message content.
        """
        history = self._conversation_history[user_id]
        history.append(ConversationMessage(role=role, content=content))

        # Keep only the last N messages
        if len(history) > MAX_CONVERSATION_HISTORY:
            self._conversation_history[user_id] = history[-MAX_CONVERSATION_HISTORY:]

    def clear_conversation(self, user_id: int) -> None:
        """
        Clear the conversation history for a user.

        Args:
            user_id: The Telegram user ID.
        """
        self._conversation_history[user_id] = []
        logger.info("Conversation cleared", user_id=user_id)

    def get_conversation_length(self, user_id: int) -> int:
        """
        Get the number of messages in a user's conversation history.

        Args:
            user_id: The Telegram user ID.

        Returns:
            int: Number of messages in history.
        """
        return len(self._conversation_history[user_id])

    async def chat_with_context(
        self,
        user_id: int,
        user_message: str,
        trade_context: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Send a conversational chat message with user context and history.

        This method:
        - Checks rate limits before making requests
        - Maintains conversation history per user
        - Includes trade data context in the system prompt
        - Records messages for continuity

        Args:
            user_id: The Telegram user ID.
            user_message: The user's message.
            trade_context: Optional string with user's trade data summary.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens in the response.

        Returns:
            tuple: (response_text, error_message) - one will be None.
        """
        if not self._client:
            return None, "AI service not configured. Please set LONGCAT_API_KEY."

        # Check rate limit
        is_limited, wait_time = self.check_rate_limit(user_id)
        if is_limited:
            return None, f"Rate limit exceeded. Please wait {wait_time} seconds before your next message."

        try:
            # Build system prompt with trade context
            system_prompt = CHAT_ASSISTANT_PROMPT
            if trade_context:
                system_prompt += f"\n\n## User's Trading Context\n{trade_context}"

            # Build messages list
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system_prompt}
            ]

            # Add conversation history
            messages.extend(self.get_conversation_history(user_id))

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Make API call
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Record the request for rate limiting
            self._rate_limits[user_id].record_request()

            # Extract response text
            if response.choices and response.choices[0].message:
                response_text = response.choices[0].message.content

                if response_text:
                    # Add both messages to conversation history
                    self.add_to_conversation(user_id, "user", user_message)
                    self.add_to_conversation(user_id, "assistant", response_text)

                    logger.info(
                        "AI chat with context completed",
                        user_id=user_id,
                        input_length=len(user_message),
                        output_length=len(response_text),
                        history_size=self.get_conversation_length(user_id),
                    )
                    return response_text, None

            return None, "Empty response from AI service"

        except Exception as e:
            error_msg = str(e)
            logger.error("AI chat with context failed", error=error_msg, user_id=user_id)

            # Provide user-friendly error messages
            if "rate" in error_msg.lower() or "limit" in error_msg.lower():
                return None, "The AI service is temporarily busy. Please try again in a moment."
            elif "timeout" in error_msg.lower():
                return None, "The request timed out. Please try a shorter message."
            elif "invalid" in error_msg.lower() and "key" in error_msg.lower():
                return None, "AI service configuration error. Please contact support."
            else:
                return None, "An error occurred while processing your message. Please try again."

    async def generate_strategy_intro(self, trade_data: dict) -> str:
        """Generate personalized intro based on trading history."""
        stats = trade_data.get("statistics", {}).get("overall", {})

        if stats.get("total_trades", 0) == 0:
            return "I see you're new here. Let's build a solid strategy from scratch."

        # Find patterns to mention
        observations = []

        # Check instrument preference
        by_inst = trade_data.get("statistics", {}).get("by_instrument", {})
        if by_inst.get("DAX", {}).get("total_trades", 0) > by_inst.get("NASDAQ", {}).get("total_trades", 0) * 2:
            observations.append("You trade DAX heavily")
        elif by_inst.get("NASDAQ", {}).get("total_trades", 0) > by_inst.get("DAX", {}).get("total_trades", 0) * 2:
            observations.append("You favor NASDAQ")

        # Check direction preference
        by_dir = trade_data.get("statistics", {}).get("by_direction", {})
        long_wr = by_dir.get("LONG", {}).get("win_rate", 0)
        short_wr = by_dir.get("SHORT", {}).get("win_rate", 0)
        if long_wr > short_wr + 15:
            observations.append(f"your longs perform better ({long_wr:.0f}% vs {short_wr:.0f}% WR)")
        elif short_wr > long_wr + 15:
            observations.append(f"your shorts perform better ({short_wr:.0f}% vs {long_wr:.0f}% WR)")

        if observations:
            obs_text = ", ".join(observations)
            return f"Based on your {stats.get('total_trades', 0)} trades: {obs_text}. Let's build on what works."
        else:
            return f"You have {stats.get('total_trades', 0)} trades logged. Let's define a clear strategy."

    async def build_strategy_from_answers(self, answers: dict, trade_data: dict) -> dict:
        """
        Process user answers and generate structured strategy.

        Returns: {
            "summary": str,
            "rules": {
                "market_conditions": list,
                "entry_rules": list,
                "exit_rules": list,
                "risk_management": list
            },
            "feedback": str (optional AI observations)
        }
        """
        # Format answers for AI
        answers_text = ""
        for section, answer in answers.items():
            answers_text += f"\n{section}: {answer}\n"

        # Format trade stats for context
        stats = trade_data.get("statistics", {}).get("overall", {})
        stats_context = f"""
User's Trading Stats:
- Total trades: {stats.get('total_trades', 0)}
- Win rate: {stats.get('win_rate', 0)}%
- Profit factor: {stats.get('profit_factor', 0)}
- Max drawdown: {stats.get('max_drawdown_pct', 0)}%
"""

        prompt = f"""You are building a trading strategy from user answers.

{stats_context}

USER ANSWERS TO STRATEGY QUESTIONS:
{answers_text}

TASK:
1. Parse the answers into concrete, actionable rules
2. Fill in reasonable defaults for skipped sections
3. Make rules specific and measurable where possible
4. Flag any contradictions or issues

Respond ONLY with this exact JSON structure:
{{
    "summary": "2-3 sentence description of the strategy",
    "rules": {{
        "market_conditions": ["rule 1", "rule 2"],
        "entry_rules": ["rule 1", "rule 2"],
        "exit_rules": ["rule 1", "rule 2"],
        "risk_management": ["rule 1", "rule 2"]
    }},
    "feedback": "Brief observation about the strategy or suggestion (or empty string if none)"
}}

Each rule should be specific and actionable. Examples:
- BAD: "Trade trends"
- GOOD: "Only enter during confirmed uptrend on 15M timeframe"

Respond with JSON only, no other text."""

        try:
            response, error = await self.chat(
                user_message=prompt,
                system_prompt="You are a trading strategy builder. Output valid JSON only.",
                temperature=0.4,
                max_tokens=2000
            )

            if error:
                return {"error": error}

            if not response:
                return {"error": "Empty response from AI"}

            # Clean JSON response
            content = response.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)

            # Validate structure
            if not result.get("rules"):
                return {"error": "Invalid response structure - missing rules"}

            return result

        except json.JSONDecodeError as e:
            return {"error": f"Failed to parse AI response: {str(e)}"}
        except Exception as e:
            return {"error": str(e)}


# Module-level singleton instance
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """
    Get or create the global AI service instance.

    Returns:
        AIService: The global AI service singleton.
    """
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service


def reset_ai_service() -> None:
    """
    Reset the global AI service instance.

    Useful for testing or reconfiguration.
    """
    global _ai_service
    _ai_service = None
