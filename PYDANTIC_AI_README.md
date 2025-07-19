# Pydantic AI Implementation

This is the new simplified AI chat implementation using Pydantic AI instead of the complex OpenAI function calling system.

## What Changed

- **Replaced**: Complex OpenAI function calling with property context handling
- **Added**: Simple Pydantic AI agent with one tool
- **Simplified**: Chat endpoint to be barebones and guaranteed to work

## Current Tool

### `get_unbooked_openings()`
- Queries PriceLabs API for unbooked dates in next 60 days
- Returns clean list of unbooked dates with prices and day of week
- Automatically filters out booked and unbookable dates

## Files Changed

1. **`requirements.txt`**: Added `pydantic-ai>=0.0.14`
2. **`ai_agent.py`**: New file with Pydantic AI agent
3. **`app.py`**: Simplified chat endpoint to use new agent

## How It Works

1. User sends message to `/chat` endpoint
2. Agent receives message and API credentials from context
3. If user asks about availability, agent calls `get_unbooked_openings()` tool
4. Tool queries PriceLabs API and returns clean data
5. Agent responds conversationally with the information

## Testing

Send a POST request to `/chat` with:
```json
{
  "message": "What dates are available this month?"
}
```

The agent will automatically use the tool to get real availability data.

## Next Steps

This is the foundation. Future enhancements can add:
- More tools (pricing analysis, market data, etc.)
- Better conversation context handling
- Property-specific context integration 