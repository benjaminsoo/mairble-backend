"""
Simple Pydantic AI agent for mAIrble with PriceLabs integration
"""
import datetime
import json
import requests
from openai import OpenAI
from pydantic_ai import Agent, RunContext
from config import get_settings

settings = get_settings()

# Pydantic AI agent for property management
agent = Agent(
    'openai:gpt-4',
    deps_type=dict,
    system_prompt="""You are an AI assistant for short-term rental hosts.

Help with property availability and pricing questions using available tools:
- get_unbooked_openings(): Find available date ranges (next 60 days) for the selected property
- get_pricing_suggestion(): Get AI pricing analysis for specific dates (use YYYY-MM-DD format) for the selected property
- get_revenue_forecast(): Calculate revenue projections for a date range for the selected property

All tools automatically use the currently selected property's data. When property context is provided, tailor responses to that specific property's characteristics (bedroom count, location, guest type, etc.).

Communication Style: Respond in a concise, data-driven manner like an experienced analyst. Lead with key numbers and metrics, use minimal filler words, and compress insights into dense, actionable statements. Keep responses brief and focused on bottom-line impact.

FORMATTING: Always format your responses using markdown for better readability:
- Use **bold** for important numbers, dates, and key metrics
- Use `code blocks` for specific prices, dates, and technical values  
- Use bullet points (- or *) for lists and recommendations
- Use ### headers for major sections
- Use > blockquotes for important insights or warnings
- Use tables when presenting multiple data points for comparison
- Use --- for horizontal dividers between sections when needed

Example formatting:
### Pricing Analysis
**Current Rate:** `$450/night`
**Market Average:** `$380/night` 

**Key Insights:**
- Premium of **18.4%** above market
- High demand period: `July 15-20`
- Recommended action: **Hold current pricing**

> **Revenue Impact:** Maintaining premium could generate **$2,100** additional revenue over 5 nights."""
)

@agent.system_prompt
def add_property_context(ctx: RunContext[dict]) -> str:
    """Add property context and current date to system prompt"""
    # Always add current date
    today_str = datetime.date.today().isoformat()
    
    property_context = ctx.deps.get('property_context')
    selected_property = ctx.deps.get('selected_property')
    
    # Start with date injection
    sections = []
    
    # Add selected property information
    if selected_property:
        prop_name = selected_property.get('name', 'Property')
        prop_location = selected_property.get('location', 'Unknown Location')
        prop_bedrooms = selected_property.get('no_of_bedrooms', 'Unknown')
        
        property_section = f"""
CURRENT PROPERTY: {prop_name}
LOCATION: {prop_location}
BEDROOMS: {prop_bedrooms} bedroom{'s' if prop_bedrooms != 1 else ''}
MARKET POSITIONING: Use bedroom count for appropriate market segment positioning and pricing strategy.
"""
        sections.append(property_section)
        print(f"🏠 Including selected property context: {prop_name} - {prop_bedrooms} bedrooms in {prop_location}")
    
    # Add existing property context if available
    if property_context:
        print("📝 Including property context in system prompt...")
        
        # Normalize inputs
        main_guest = property_context.get('mainGuest', '')
        features = property_context.get('specialFeature', [])
        goals = property_context.get('pricingGoal', [])
        feature_details = property_context.get('specialFeatureDetails', {})
        
        print(f"🔍 Property context received - features: {features}")
        print(f"🔍 Feature details received: {feature_details}")
        
        if isinstance(features, str):
            features = [features] if features else []
        if isinstance(goals, str):
            goals = [goals] if goals else []
        
        if main_guest or features or goals:
            # Build context sections
            
            # Guest targeting
            guest_profiles = {
                "Leisure": "MAIN GUEST: Leisure travelers. Higher pricing on weekends. More conservative pricing on weekdays.",
                "Business": "MAIN_GUEST: Business travelers. More balanced pricing throughout the week.",
                "Groups": "MAIN GUEST: Group travelers. Focus on multi-night stays. Higher value bookings."
            }
            if main_guest in guest_profiles:
                sections.append(guest_profiles[main_guest])
            
            # Competitive advantages - use custom descriptions if available, otherwise fallback to defaults
            advantage_map = {
                "Location": "Prime location - #1 guest driver, premium justified",
                "Unique Amenity": "Rare amenity (pool/hot tub) - strong premium justified",
                "Size/Capacity": "Large capacity (10+) - higher rates, less competition",
                "Luxury/Design": "Luxury finishes - appeals to high-paying guests",
                "Pet-Friendly": "Pet-friendly - underserved premium market",
                "Exceptional View": "Exceptional view - visual appeal justifies higher rates",
                "Unique Experience": "Unique property type - strong demand, pricing power"
            }
            
            advantages = []
            for feature in features:
                if feature in feature_details and feature_details[feature].strip():
                    # Use custom description provided by user
                    custom_desc = feature_details[feature].strip()
                    advantages.append(f"{feature}: {custom_desc}")
                    print(f"🎯 Using custom description for {feature}: {custom_desc}")
                elif feature in advantage_map:
                    # Fallback to default description
                    advantages.append(f"{feature}: {advantage_map[feature]}")
                    print(f"📝 Using default description for {feature}")
            
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
            return f"Today is {today_str}." + context_prompt
    
    # If no property context, just return the date
    return f"Today is {today_str}."

@agent.tool
def get_pricing_suggestion(ctx: RunContext[dict], dates: str) -> str:
    """
    Get comprehensive AI-powered pricing suggestions for specific dates.
    
    Args:
        dates: Comma-separated dates in YYYY-MM-DD format (max 5 dates)
               Examples: "2025-07-21" or "2025-07-21,2025-08-11,2025-08-15"
    
    Returns:
        Detailed pricing analysis for the specified dates only
    """
    # Extract API credentials from context dependencies
    deps = ctx.deps
    api_key = deps.get('api_key')
    listing_id = deps.get('listing_id')
    pms = deps.get('pms', 'airbnb')
    selected_property = deps.get('selected_property')
    
    # Require selected property for pricing analysis
    if not selected_property or not selected_property.get('id'):
        return "❌ No property selected. Please select a property first to get pricing suggestions."
    
    listing_id = selected_property['id']
    print(f"🏠 Using selected property: {listing_id} ({selected_property.get('name', 'Unknown Property')})")
    
    if not api_key or not listing_id:
        return "Missing required API credentials (api_key or listing_id)"
    
    # Parse and validate dates
    try:
        requested_dates = [date.strip() for date in dates.split(',')]
        
        # Enforce 5-date maximum
        if len(requested_dates) > 5:
            return f"Maximum 5 dates allowed per request. You requested {len(requested_dates)} dates. Please split into smaller requests."
        
        # Validate each date format and ensure not in past
        today = datetime.date.today()
        validated_dates = []
        
        for date_str in requested_dates:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                if date_obj < today:
                    return f"Cannot analyze past dates. {date_str} is before today ({today}). Please use current or future dates."
                validated_dates.append(date_str)
            except ValueError:
                return f"Invalid date format: '{date_str}'. Please use YYYY-MM-DD format (e.g., {today.isoformat()})"
        
        # Determine date range for API call (from earliest to latest requested date)
        validated_dates.sort()
        date_from = validated_dates[0]
        date_to = validated_dates[-1]
        
    except Exception as e:
        return f"Error parsing dates: {str(e)}. Please use comma-separated YYYY-MM-DD format."
    
    print(f"💰 Getting pricing analysis for {len(validated_dates)} specific dates: {', '.join(validated_dates)}")
    
    try:
        # Check OpenAI configuration
        if not settings.OPENAI_API_KEY:
            return "OpenAI API key not configured for pricing analysis"
        
        BASE_URL = "https://api.pricelabs.co"
        HEADERS = {"X-API-Key": api_key}
        
        # 1. Fetch pricing data for the date range (but only process specific dates)
        print(f"📡 Fetching pricing data for range {date_from} to {date_to}...")
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
            return f"PriceLabs pricing API error: {resp.status_code} - {resp.text}"
        
        response_data = resp.json()
        if isinstance(response_data, list) and len(response_data) > 0:
            pricing_data = response_data[0].get("data", [])
        else:
            return "Unexpected response format from PriceLabs pricing API"
        
        if not pricing_data:
            return f"No pricing data available for requested dates"
        
        # 2. Fetch neighborhood market data
        print("📡 Fetching neighborhood market data...")
        nb_url = f"{BASE_URL}/v1/neighborhood_data"
        nb_params = {"listing_id": listing_id, "pms": pms}
        
        nb_resp = requests.get(nb_url, headers=HEADERS, params=nb_params)
        nb_data = None
        if nb_resp.status_code == 200:
            try:
                full_response = nb_resp.json()
                nb_data = full_response.get("data", {})
                if isinstance(nb_data, dict) and "data" in nb_data:
                    nb_data = nb_data["data"]
                print("✅ Neighborhood data retrieved")
            except Exception as e:
                print(f"⚠️ Error parsing neighborhood data: {e}")
        else:
            print(f"⚠️ Could not fetch neighborhood data: {nb_resp.status_code}")
        
        # 3. Process ONLY the specifically requested dates
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        suggestions = []
        # Use the selected property's bedroom count for market analysis
        property_bedrooms = str(selected_property.get('no_of_bedrooms', 3))
        print(f"🛏️ Using {property_bedrooms} bedrooms for market analysis")
        
        # Create a lookup dict for faster access
        pricing_lookup = {night.get("date"): night for night in pricing_data}
        
        for requested_date in validated_dates:
            night = pricing_lookup.get(requested_date)
            
            if not night:
                suggestions.append(f"{requested_date}:\n{{\n  \"error\": \"No pricing data available for this date\"\n}}")
                continue
            
            # Skip booked or unbookable nights
            if night.get("booking_status") == "booked" or night.get("unbookable", 0) != 0:
                suggestions.append(f"{requested_date}:\n{{\n  \"error\": \"Date is booked or unavailable\"\n}}")
                continue
            
            your_price = night.get("user_price") or night.get("price")
            
            if not your_price:
                suggestions.append(f"{requested_date}:\n{{\n  \"error\": \"No price data available\"\n}}")
                continue
            
            # Extract market data once (avoid duplicate calls)
            real_market_data = extract_market_data_for_date(nb_data, requested_date, property_bedrooms) if nb_data else None
            market_avg_price = real_market_data if real_market_data else get_intelligent_market_fallback(your_price, requested_date)
            market_source = "real PriceLabs data" if real_market_data else "intelligent seasonal estimate"
            
            # Extract occupancy and day of week
            occupancy = extract_occupancy_for_date(nb_data, requested_date, property_bedrooms) if nb_data else None
            try:
                date_obj = datetime.datetime.strptime(requested_date, "%Y-%m-%d").date()
                day_of_week = date_obj.strftime("%A")
                days_from_today = (date_obj - datetime.date.today()).days
            except ValueError:
                day_of_week = "Unknown"
                days_from_today = 0
            
            # Extract PriceLabs enrichment data
            event = night.get("demand_desc")
            adr_last_year = None
            neighborhood_demand = None
            min_price_limit = None
            avg_los_last_year = None
            seasonal_profile = None
            
            if "reason" in night and "listing_info" in night["reason"]:
                listing_info = night["reason"]["listing_info"]
                try:
                    if listing_info.get("ADR_STLY", -1) != -1:
                        adr_last_year = float(listing_info["ADR_STLY"])
                    neighborhood_demand = listing_info.get("nhood_demand")
                    if listing_info.get("minimum_price"):
                        min_price_limit = float(listing_info["minimum_price"])
                    if listing_info.get("avg_los_STLY", 0) > 0:
                        avg_los_last_year = float(listing_info["avg_los_STLY"])
                    seasonal_profile = listing_info.get("minstay_seasonal_profile")
                except (ValueError, TypeError) as e:
                    print(f"⚠️ Error parsing PriceLabs fields for {requested_date}: {e}")
            
            # Build property context if available
            property_context_str = ""
            property_context = deps.get('property_context')
            if property_context:
                main_guest = property_context.get('mainGuest', '')
                features = property_context.get('specialFeature', [])
                goals = property_context.get('pricingGoal', [])
                feature_details = property_context.get('specialFeatureDetails', {})
                
                print(f"🔍 Pricing tool - features: {features}")
                print(f"🔍 Pricing tool - feature details: {feature_details}")
                
                if isinstance(features, str):
                    features = [features] if features else []
                if isinstance(goals, str):
                    goals = [goals] if goals else []
                
                # Build context sections
                sections = []
                
                # Guest targeting
                guest_profiles = {
                    "Leisure": "MAIN GUEST: Leisure travelers. Higher pricing on weekends. More conservative pricing on weekdays.",
                    "Business": "MAIN_GUEST: Business travelers. More balanced pricing throughout the week.",
                    "Groups": "MAIN_GUEST: Groups/events.",
                    "Balanced": "MAIN_GUEST: Variety of guests. Adapt pricing to demand patterns - premium weekends for leisure, competitive but conservative weekdays for business."
                }
                if main_guest in guest_profiles:
                    sections.append(guest_profiles[main_guest])
                
                # Competitive advantages - use custom descriptions if available, otherwise fallback to defaults
                advantage_map = {
                    "Location": "Prime location - #1 guest driver, premium justified",
                    "Unique Amenity": "Rare amenity (pool/hot tub) - strong premium justified",
                    "Size/Capacity": "Large capacity (10+) - higher rates, less competition",
                    "Luxury/Design": "Luxury finishes - appeals to high-paying guests",
                    "Pet-Friendly": "Pet-friendly - underserved premium market",
                    "Exceptional View": "Exceptional view - visual appeal justifies higher rates",
                    "Unique Experience": "Unique property type - strong demand, pricing power"
                }
                
                advantages = []
                for feature in features:
                    if feature in feature_details and feature_details[feature].strip():
                        # Use custom description provided by user
                        custom_desc = feature_details[feature].strip()
                        advantages.append(f"{feature}: {custom_desc}")
                        print(f"🎯 Using custom description for {feature}: {custom_desc}")
                    elif feature in advantage_map:
                        # Fallback to default description
                        advantages.append(f"{feature}: {advantage_map[feature]}")
                        print(f"📝 Using default description for {feature}")
                
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
                    prefix = "PRICING STRATEGY" if len(strategies) == 1 else "STRATEGIES (balance)"
                    sections.append(f"{prefix}: {'; '.join(strategies)}")
                
                if sections:
                    property_context_str = f"\n\nPROPERTY CONTEXT: {' | '.join(sections)}\nCRITICAL: Reference this context in pricing decisions. Align recommendations with guest type, advantages, and pricing strategy."
            
            # Build prompt with available data
            historical_info = f"Last year: ${adr_last_year:.0f}" if adr_last_year else ""
            demand_info = f"Demand: {neighborhood_demand or 'Unknown'}"
            constraints_info = f"Min price: ${min_price_limit:.0f}" if min_price_limit else ""
            stay_info = f"Avg stay: {avg_los_last_year:.0f} nights" if avg_los_last_year else ""
            
            prompt = f"""You are a revenue manager for a short-term rental property. Analyze and recommend pricing in JSON:{property_context_str}

PROPERTY DATA:
- Date: {requested_date} ({day_of_week}) - {days_from_today} days from today
- Current: ${your_price}
- Market: ${market_avg_price:.0f} ({market_source})
- {historical_info}
- {demand_info}
- Event: {event or 'Standard'}
- Occupancy: {occupancy or 'Unknown'}%
- {stay_info}
- {constraints_info}
- Season: {seasonal_profile or 'Standard'}

STRATEGY: Analyze all property data to suggest a nightly rate that maximizes total revenue. Prioritize higher pricing during peak season, weekends, local events, or when market occupancy and demand are high. Lower prices modestly during low-demand periods, for last-minute openings, or mid-week stays to protect occupancy. Compare the current price to market averages and adjust upward if underpriced and justified by property quality or scarcity. Respect minimum price constraints, but allow competitive discounts when needed to avoid vacancies. Always balance rate with booking likelihood to optimize both ADR and occupancy.

JSON FORMAT:
{{
  "suggested_price": [number],
  "confidence": [0-100],
  "explanation": "[max 2 sentences]"
}}"""
            print(f"🔍 Prompt: {prompt}")
            try:
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300
                )
                
                ai_response = response.choices[0].message.content.strip()
                
                # Parse JSON response
                try:
                    parsed = json.loads(ai_response)
                    # Create new dict with current_price first
                    output = {"current_price": your_price}
                    output.update(parsed)
                    suggestions.append(f"{requested_date}:\n{json.dumps(output, indent=2)}")
                except json.JSONDecodeError:
                    suggestions.append(f"{requested_date}:\n{{\n  \"error\": \"Failed to parse JSON\",\n  \"raw_response\": \"{ai_response[:100]}\"\n}}")
                
            except Exception as e:
                suggestions.append(f"{requested_date}: Analysis failed - {str(e)}")
        
        if not suggestions:
            return f"No pricing suggestions available for requested dates"
        
        result = "\n\n".join(suggestions)
        print(f"✅ Pricing analysis complete for {len(suggestions)} specific dates")
        print(f"📤 Tool output to LLM:\n{result}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to get pricing suggestions: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

# Helper functions from app.py for market data extraction
def extract_market_data_for_date(nb_data, target_date, property_bedrooms="3"):
    """
    Extract market average price for a specific date from PriceLabs neighborhood data.
    
    Args:
        nb_data: The neighborhood data from PriceLabs API
        target_date: Date string in format "2025-06-22"
        property_bedrooms: Bedroom category to use ("0" for studio, "1" for 1BR, etc.)
    
    Returns:
        float: Market average price or None if not found
    """
    try:
        if not nb_data or "Future Percentile Prices" not in nb_data:
            print(f"No Future Percentile Prices data available for {target_date}")
            return None
            
        fpp = nb_data["Future Percentile Prices"]
        
        if "Category" not in fpp:
            print(f"No Category data in Future Percentile Prices for {target_date}")
            return None
            
        categories = fpp["Category"]
        labels = fpp.get("Labels", [])
        
        # Try to find the best bedroom category match
        # Priority: exact match -> 1BR -> 2BR -> any available
        bedroom_keys_to_try = [property_bedrooms, "1", "2", "0", "3", "4"]
        
        for bedroom_key in bedroom_keys_to_try:
            if bedroom_key in categories:
                category_data = categories[bedroom_key]
                x_values = category_data.get("X_values", [])
                y_values = category_data.get("Y_values", [])
                
                # Find the date index
                if target_date in x_values:
                    date_index = x_values.index(target_date)
                    
                    # Extract pricing data for this date
                    # Y_values structure: [[25th percentile], [50th percentile], [75th percentile], [median booked], [90th percentile]]
                    # We'll use the 50th percentile (median) as market average
                    
                    if len(y_values) >= 2 and len(y_values[1]) > date_index:
                        market_avg = y_values[1][date_index]  # 50th percentile
                        print(f"Found market avg for {target_date} in bedroom category {bedroom_key}: ${market_avg}")
                        return float(market_avg)
                    
                    # Fallback: try median booked price if available
                    if len(y_values) >= 4 and len(y_values[3]) > date_index:
                        market_avg = y_values[3][date_index]  # Median booked price
                        print(f"Using median booked price for {target_date} in bedroom category {bedroom_key}: ${market_avg}")
                        return float(market_avg)
                
                print(f"Date {target_date} not found in X_values for bedroom category {bedroom_key}")
                
        print(f"No suitable bedroom category found for {target_date}")
        return None
        
    except Exception as e:
        print(f"Error extracting market data for {target_date}: {e}")
        return None

def extract_occupancy_for_date(nb_data, target_date, property_bedrooms="3"):
    """
    Extract market occupancy percentage for a specific date from neighborhood data.
    """
    if not nb_data or "Future Occ/New/Canc" not in nb_data:
        print(f"No occupancy data available for {target_date}")
        # Debug: show what keys are actually available
        if nb_data:
            print(f"Available keys in nb_data: {list(nb_data.keys())}")
        return None
        
    try:
        occ_data = nb_data["Future Occ/New/Canc"]
        labels = occ_data.get("Labels", [])
        
        print(f"🔍 Debugging occupancy extraction for {target_date}:")
        print(f"   Labels available: {labels}")
        
        # Find the occupancy index
        if "Occupancy" not in labels:
            print(f"❌ Occupancy label not found in: {labels}")
            return None
            
        occ_idx = labels.index("Occupancy")
        print(f"   Occupancy index: {occ_idx}")
        
        # Try different bedroom categories
        bedroom_categories = [str(property_bedrooms), "3", "2", "1", "4", "5"]
        
        categories = occ_data.get("Category", {})
        print(f"   Available bedroom categories: {list(categories.keys())}")
        
        for bedroom_key in bedroom_categories:
            if bedroom_key in categories:
                cat_data = categories[bedroom_key]
                x_values = cat_data.get("X_values", [])
                y_values = cat_data.get("Y_values", [])
                
                print(f"   Trying bedroom category {bedroom_key}:")
                print(f"     X_values length: {len(x_values)}")
                print(f"     Y_values length: {len(y_values)}")
                print(f"     Y_values structure: {[len(yv) if isinstance(yv, list) else type(yv) for yv in y_values]}")
                
                if target_date in x_values and len(y_values) > occ_idx:
                    date_index = x_values.index(target_date)
                    print(f"     Found {target_date} at index {date_index}")
                    
                    occ_data_points = y_values[occ_idx]
                    print(f"     Occupancy data points type: {type(occ_data_points)}")
                    
                    # The occupancy data might be nested differently
                    if isinstance(occ_data_points, list) and len(occ_data_points) > 0:
                        print(f"     Occupancy data points[0] type: {type(occ_data_points[0])}")
                        if isinstance(occ_data_points[0], list) and len(occ_data_points[0]) > date_index:
                            occupancy = occ_data_points[0][date_index]
                            print(f"     Found occupancy via [0][{date_index}]: {occupancy}")
                        elif len(occ_data_points) > date_index:
                            occupancy = occ_data_points[date_index]
                            print(f"     Found occupancy via [{date_index}]: {occupancy}")
                        else:
                            print(f"     Date index {date_index} out of range")
                            continue
                    else:
                        print(f"     Unexpected occupancy data structure")
                        continue
                        
                    if occupancy is not None:
                        # Convert to percentage if needed (PriceLabs might return 0-1 or 0-100)
                        if isinstance(occupancy, (int, float)):
                            if occupancy <= 1.0:
                                occupancy = occupancy * 100  # Convert from decimal to percentage
                            print(f"✅ Found occupancy for {target_date} in bedroom category {bedroom_key}: {occupancy}%")
                            return float(occupancy)
                
                print(f"     Date {target_date} not found in occupancy data for bedroom category {bedroom_key}")
                
        print(f"❌ No suitable bedroom category found for occupancy data for {target_date}")
        return None
        
    except Exception as e:
        print(f"❌ Error extracting occupancy data for {target_date}: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_intelligent_market_fallback(your_price, date, location="Newport, RI"):
    """
    Provide intelligent market price fallback based on property characteristics and location.
    """
    try:
        # Parse date to get seasonality
        date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
        month = date_obj.month
        is_weekend = date_obj.weekday() >= 5  # Saturday = 5, Sunday = 6
        
        # Newport, RI luxury property seasonal adjustments
        seasonal_multipliers = {
            1: 0.70,  # Jan - Winter low
            2: 0.70,  # Feb - Winter low  
            3: 0.75,  # Mar - Early spring
            4: 0.85,  # Apr - Spring
            5: 0.95,  # May - Pre-season
            6: 1.10,  # Jun - Summer peak
            7: 1.15,  # Jul - Peak summer
            8: 1.15,  # Aug - Peak summer
            9: 1.05,  # Sep - Late summer
            10: 0.90, # Oct - Fall
            11: 0.75, # Nov - Late fall
            12: 0.75  # Dec - Winter
        }
        
        # Base estimate: 85% of current price (assume slight premium pricing)
        base_market = your_price * 0.85
        
        # Apply seasonal multiplier
        seasonal_factor = seasonal_multipliers.get(month, 0.85)
        base_market *= seasonal_factor
        
        # Weekend premium for summer months
        if is_weekend and month in [5, 6, 7, 8, 9]:
            base_market *= 1.15
        
        print(f"Intelligent fallback for {date}: ${round(base_market)} (seasonal: {seasonal_factor}, weekend: {is_weekend})")
        return round(base_market)
        
    except Exception as e:
        print(f"Error in intelligent fallback: {e}")
        return your_price * 0.85

@agent.tool
def get_revenue_forecast(ctx: RunContext[dict], date_from: str, date_to: str) -> str:
    """
    Calculate revenue projections for a date range, splitting booked vs unbooked revenue. Also works when user wants to know what a certain date or multiple dates is priced at.
    
    Args:
        date_from: Start date in YYYY-MM-DD format
        date_to: End date in YYYY-MM-DD format
    
    Returns:
        Revenue breakdown showing booked revenue, potential unbooked revenue, and totals
    """
    # Extract API credentials from context dependencies
    deps = ctx.deps
    api_key = deps.get('api_key')
    listing_id = deps.get('listing_id')
    pms = deps.get('pms', 'airbnb')
    selected_property = deps.get('selected_property')
    
    # Require selected property for revenue forecast
    if not selected_property or not selected_property.get('id'):
        return "❌ No property selected. Please select a property first to get revenue forecasts."
    
    listing_id = selected_property['id']
    print(f"🏠 Using selected property: {listing_id} ({selected_property.get('name', 'Unknown Property')})")
    
    if not api_key or not listing_id:
        return "Missing required API credentials (api_key or listing_id)"
    
    # Validate dates are not in the past
    try:
        from_date = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
        to_date = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()
        today = datetime.date.today()
        
        if from_date < today:
            return f"Cannot forecast past dates. {date_from} is before today ({today}). Please use current or future dates."
        if to_date < today:
            return f"Cannot forecast past dates. {date_to} is before today ({today}). Please use current or future dates."
        if from_date > to_date:
            return f"Invalid date range. Start date {date_from} is after end date {date_to}."
            
    except ValueError:
        return f"Invalid date format. Please use YYYY-MM-DD format (e.g., {datetime.date.today().isoformat()})"
    
    print(f"📊 Getting revenue forecast for {listing_id} from {date_from} to {date_to}")
    
    try:
        BASE_URL = "https://api.pricelabs.co"
        HEADERS = {"X-API-Key": api_key}
        
        # Call PriceLabs API to get pricing data for the range
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
            return f"PriceLabs API error: {resp.status_code} - {resp.text}"
        
        response_data = resp.json()
        if isinstance(response_data, list) and len(response_data) > 0:
            data = response_data[0].get("data", [])
        else:
            return "Unexpected response format from PriceLabs API"
        
        if not data:
            return f"No pricing data available for {date_from} to {date_to}"
        
        # Initialize revenue tracking
        booked_revenue = 0
        unbooked_revenue = 0
        booked_nights = 0
        unbooked_nights = 0
        unbookable_nights = 0
        
        # Process each night
        for night in data:
            date = night.get("date")
            price = night.get("price", 0)
            user_price = night.get("user_price", 0)
            booking_status = night.get("booking_status", "")
            unbookable = night.get("unbookable", 0)
            adr = night.get("ADR", 0)
            
            # Skip if no price data
            if not price:
                continue
            
            # Categorize by booking status
            if booking_status and "booked" in booking_status.lower():
                # Booked nights: Use 'ADR' field (actual daily rate) for booked dates
                booked_price = adr if adr > 0 else price  # Fallback to price if ADR not available
                booked_revenue += booked_price
                booked_nights += 1
            elif unbookable != 0:
                unbookable_nights += 1
                # Don't count unbookable nights in revenue
            else:
                # Available for booking - use user_price or fall back to price
                available_price = user_price if user_price > 0 else price
                unbooked_revenue += available_price
                unbooked_nights += 1
        
        # Calculate totals and metrics
        total_nights = booked_nights + unbooked_nights + unbookable_nights
        confirmed_revenue = booked_revenue
        potential_revenue = unbooked_revenue
        total_potential = confirmed_revenue + potential_revenue
        
        # Calculate averages
        avg_booked_rate = booked_revenue / booked_nights if booked_nights > 0 else 0
        avg_unbooked_rate = unbooked_revenue / unbooked_nights if unbooked_nights > 0 else 0
        
        # Format results
        result = f"""Revenue Forecast ({date_from} to {date_to}):

CONFIRMED REVENUE (Booked): ${confirmed_revenue:,.0f}
- {booked_nights} nights @ ${avg_booked_rate:.0f}/night average

POTENTIAL REVENUE (Available): ${potential_revenue:,.0f}
- {unbooked_nights} nights @ ${avg_unbooked_rate:.0f}/night average

TOTAL POTENTIAL: ${total_potential:,.0f}
- {total_nights} total nights ({unbookable_nights} unbookable)
- {(booked_nights/max(total_nights-unbookable_nights, 1)*100):.0f}% occupancy rate"""

        print(f"✅ Revenue forecast complete: ${total_potential:,.0f} total potential (${confirmed_revenue:,.0f} confirmed + ${potential_revenue:,.0f} available)")
        print(f"📤 Tool output to LLM:\n{result}")
        return result
        
    except Exception as e:
        error_msg = f"Failed to get revenue forecast: {str(e)}"
        print(f"❌ {error_msg}")
        return error_msg

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
    selected_property = deps.get('selected_property')
    
    # Require selected property for availability check
    if not selected_property or not selected_property.get('id'):
        raise Exception("❌ No property selected. Please select a property first to check availability.")
    
    listing_id = selected_property['id']
    print(f"🏠 Using selected property: {listing_id} ({selected_property.get('name', 'Unknown Property')})")
    
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

async def run_agent(message: str, api_key: str, listing_id: str = None, pms: str = "airbnb", property_context: dict = None, selected_property: dict = None) -> str:
    """Run the Pydantic AI agent with user message, API credentials, and optional property context."""
    try:
        # Create dependencies dictionary with API credentials and property context
        deps = {
            "api_key": api_key,
            "listing_id": listing_id,
            "pms": pms,
            "property_context": property_context,
            "selected_property": selected_property
        }
        
        # Run the agent with proper deps parameter
        result = await agent.run(message, deps=deps)
        return result.output
        
    except Exception as e:
        print(f"❌ Error running agent: {e}")
        return f"I'm sorry, I encountered an error: {str(e)}" 