"""
Simple Pydantic AI agent for mAIrble with PriceLabs integration
"""
import datetime
import requests
from pydantic_ai import Agent, RunContext
from config import get_settings

settings = get_settings()

# Pydantic AI agent for property management
agent = Agent(
    'openai:gpt-4',
    deps_type=dict,
    system_prompt="""You are an AI assistant for short-term rental hosts. 
Help with property availability and pricing questions. 
Present date ranges clearly and keep responses conversational. 
Communication Style: Respond in a concise, data-driven manner like an experienced analyst. Lead with key numbers and metrics, use minimal filler words, and compress insights into dense, actionable statements. Keep responses brief and focused on bottom-line impact."""
)

@agent.system_prompt
def add_property_context(ctx: RunContext[dict]) -> str:
    """Add property context to system prompt if available"""
    property_context = ctx.deps.get('property_context')
    if not property_context:
        return ""
    
    print("📝 Including property context in system prompt...")
    
    # Normalize inputs
    main_guest = property_context.get('mainGuest', '')
    features = property_context.get('specialFeature', [])
    goals = property_context.get('pricingGoal', [])
    
    if isinstance(features, str):
        features = [features] if features else []
    if isinstance(goals, str):
        goals = [goals] if goals else []
    
    if not (main_guest or features or goals):
        return ""
    
    # Build context sections
    sections = []
    
    # Guest targeting
    guest_profiles = {
        "Leisure": "TARGET: Leisure travelers. Book advance, price-sensitive, want amenities. Peak: weekends/holidays.",
        "Business": "TARGET: Business travelers. Book last-minute, less price-sensitive, need workspace. Peak: weekdays.",
        "Groups": "TARGET: Groups/events. Price-sensitive per-person, need capacity/entertainment. Peak: weekends."
    }
    if main_guest in guest_profiles:
        sections.append(guest_profiles[main_guest])
    
    # Competitive advantages
    advantage_map = {
        "Location": "Prime location - #1 guest driver, premium justified",
        "Unique Amenity": "Rare amenity (pool/hot tub) - strong premium justified",
        "Size/Capacity": "Large capacity (10+) - higher rates, less competition",
        "Luxury/Design": "Luxury finishes - appeals to high-paying guests",
        "Pet-Friendly": "Pet-friendly - underserved premium market",
        "Exceptional View": "Exceptional view - visual appeal justifies higher rates",
        "Unique Experience": "Unique property type - strong demand, pricing power"
    }
    advantages = [advantage_map[f] for f in features if f in advantage_map]
    if advantages:
        sections.append("ADVANTAGES: " + "; ".join(advantages))
    
    # Pricing strategy
    strategy_map = {
        "Fill Dates": "FILL DATES: Prioritize occupancy over rate, aggressive discounts",
        "Max Price": "MAX PRICE: Highest rates priority, highlight premium features",
        "Avoid Bad Guests": "QUALITY FILTER: Price floors to filter guests"
    }
    strategies = [strategy_map[g] for g in goals if g in strategy_map]
    if strategies:
        prefix = "STRATEGY" if len(strategies) == 1 else "STRATEGIES (balance)"
        sections.append(f"{prefix}: {'; '.join(strategies)}")
    
    context_prompt = f"""

PROPERTY CONTEXT: {' | '.join(sections)}

CRITICAL: Reference this context in all advice. Align recommendations with guest type, advantages, and pricing strategy."""
    
    print(f"✅ Property context added: {' | '.join(sections)}")
    return context_prompt

@agent.tool
def get_unbooked_openings(ctx: RunContext[dict]) -> str:
    """
    Get available date ranges for the property in the next 60 days.
    Returns consecutive unbooked periods formatted as "start to end (X nights)".
    """
    # Extract API credentials from context dependencies
    deps = ctx.deps
    api_key = deps.get('api_key')
    listing_id = deps.get('listing_id')
    pms = deps.get('pms', 'airbnb')
    
    if not api_key or not listing_id:
        raise Exception("Missing required API credentials (api_key or listing_id)")
    
    print(f"🔍 Getting unbooked openings for listing {listing_id}")
    
    try:
        BASE_URL = "https://api.pricelabs.co"
        HEADERS = {"X-API-Key": api_key}
        
        # Get next 60 days
        today = datetime.date.today()
        date_from = today.isoformat()
        date_to = (today + datetime.timedelta(days=60)).isoformat()
        
        # Call PriceLabs API
        prices_url = f"{BASE_URL}/v1/listing_prices"
        body = {
            "listings": [
                {
                    "id": listing_id,
                    "pms": pms,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "reason": True
                }
            ]
        }
        
        resp = requests.post(prices_url, headers=HEADERS, json=body)
        
        if resp.status_code != 200:
            raise Exception(f"PriceLabs API error: {resp.status_code} - {resp.text}")
        
        response_data = resp.json()
        if isinstance(response_data, list) and len(response_data) > 0:
            data = response_data[0].get("data", [])
        else:
            raise Exception("Unexpected response format from PriceLabs API")
        
        # Filter for unbooked dates - just collect the dates
        unbooked_dates = []
        booked_count = 0
        unbookable_count = 0
        
        for night in data:
            date = night.get("date")
            booking_status = night.get("booking_status")
            unbookable = night.get("unbookable", 0)
            
            # Skip if booked or unbookable
            # booking_status can be: "Booked", "Booked (Check-In)", "" (available)
            if booking_status and "booked" in booking_status.lower():
                booked_count += 1
                continue
            if unbookable != 0:
                unbookable_count += 1
                continue
                
            if date:
                unbooked_dates.append(date)
        
        print(f"📊 PriceLabs Data: {len(data)} total nights | Booked: {booked_count} | Unbookable: {unbookable_count} | Available: {len(unbooked_dates)}")
        
        # Group consecutive dates into ranges and format directly as strings
        if not unbooked_dates:
            result = "No available dates found in the next 60 days."
        else:
            unbooked_dates.sort()
            ranges = []
            total_nights = 0
            
            range_start = unbooked_dates[0]
            range_end = unbooked_dates[0]
            
            for i in range(1, len(unbooked_dates)):
                current_date = datetime.datetime.strptime(unbooked_dates[i], "%Y-%m-%d")
                prev_date = datetime.datetime.strptime(unbooked_dates[i-1], "%Y-%m-%d")
                
                # If consecutive days, extend current range
                if (current_date - prev_date).days == 1:
                    range_end = unbooked_dates[i]
                else:
                    # Gap found, save current range and start new one
                    nights = (datetime.datetime.strptime(range_end, "%Y-%m-%d") - 
                             datetime.datetime.strptime(range_start, "%Y-%m-%d")).days + 1
                    total_nights += nights
                    
                    if range_start == range_end:
                        ranges.append(f"{range_start} (1 night)")
                    else:
                        ranges.append(f"{range_start} to {range_end} ({nights} nights)")
                    
                    range_start = unbooked_dates[i]
                    range_end = unbooked_dates[i]
            
            # Add the final range
            nights = (datetime.datetime.strptime(range_end, "%Y-%m-%d") - 
                     datetime.datetime.strptime(range_start, "%Y-%m-%d")).days + 1
            total_nights += nights
            
            if range_start == range_end:
                ranges.append(f"{range_start} (1 night)")
            else:
                ranges.append(f"{range_start} to {range_end} ({nights} nights)")
            
            result = f"Available: {', '.join(ranges)}. Total: {len(ranges)} gaps, {total_nights} nights."
        
        print(f"✅ Tool result: {result}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to get unbooked openings: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

async def run_agent(message: str, api_key: str, listing_id: str, pms: str = "airbnb", property_context: dict = None) -> str:
    """Run the Pydantic AI agent with user message, API credentials, and optional property context."""
    try:
        # Create dependencies dictionary with API credentials and property context
        deps = {
            "api_key": api_key,
            "listing_id": listing_id,
            "pms": pms,
            "property_context": property_context
        }
        
        # Run the agent with proper deps parameter
        result = await agent.run(message, deps=deps)
        return result.data
        
    except Exception as e:
        print(f"❌ Error running agent: {e}")
        return f"I'm sorry, I encountered an error: {str(e)}" 