from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import requests
import datetime
import os
from openai import OpenAI
from config import get_settings

# Get application settings
settings = get_settings()

# Create FastAPI app with production-ready configuration
app = FastAPI(
    title="mAIrble Backend API",
    description="AI-powered pricing analysis for Short Term Rental hosts",
    version="1.0.0",
    docs_url="/docs" if settings.is_development else None,  # Disable docs in production
    redoc_url="/redoc" if settings.is_development else None,
)

# Production-ready CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS if settings.is_production else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {
        "status": "healthy", 
        "message": "mAIrble Backend API is running!",
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT,
        "config": {
            "has_pricelabs_key": bool(settings.PRICELABS_API_KEY),
            "has_openai_key": bool(settings.OPENAI_API_KEY),
            "listing_id": settings.LISTING_ID,
            "pms": settings.PMS
        }
    }

class FetchRequest(BaseModel):
    date_from: Optional[str] = None  # yyyy-mm-dd
    date_to: Optional[str] = None

class NightData(BaseModel):
    date: str
    your_price: Optional[float]
    market_avg_price: Optional[float]
    occupancy: Optional[float]
    event: Optional[str]
    day_of_week: Optional[str]
    lead_time: Optional[int]

class LLMResult(BaseModel):
    date: str
    suggested_price: Optional[float]
    confidence: Optional[int]
    explanation: Optional[str]
    insight_tag: Optional[str]

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
                    print(f"     Occupancy data points: {occ_data_points}")
                    
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
            12: 0.70  # Dec - Winter
        }
        
        # Base market estimate for luxury Newport properties
        base_market_price = 650.0
        
        # Apply seasonal adjustment
        seasonal_price = base_market_price * seasonal_multipliers.get(month, 1.0)
        
        # Weekend premium
        if is_weekend:
            seasonal_price *= 1.12
            
        # If we have your_price, use it to inform the market estimate
        if your_price and your_price > 0:
            # If your price is significantly higher, adjust market estimate upward
            if your_price > seasonal_price * 1.3:
                seasonal_price = your_price * 0.85  # Market likely 15% below your premium pricing
            elif your_price < seasonal_price * 0.7:
                seasonal_price = your_price * 1.15  # Market likely 15% above your discounted pricing
        
        estimated_price = round(seasonal_price, 2)
        print(f"Intelligent market fallback for {date} in {location}: ${estimated_price} (seasonal factor: {seasonal_multipliers.get(month, 1.0)}, weekend: {is_weekend})")
        return estimated_price
        
    except Exception as e:
        print(f"Error calculating intelligent fallback for {date}: {e}")
        return 650.0  # Safe fallback

@app.post("/fetch-pricing-data", response_model=List[NightData])
def fetch_pricing_data(req: FetchRequest):
    try:
        BASE_URL = "https://api.pricelabs.co"
        HEADERS = {"X-API-Key": settings.PRICELABS_API_KEY}
        today = datetime.date.today()
        date_from = req.date_from or today.isoformat()
        date_to = req.date_to or (today + datetime.timedelta(days=90)).isoformat()

        print(f"🔍 Fetching pricing data for listing {settings.LISTING_ID} from {date_from} to {date_to}")
        print(f"🔑 Using API key: {settings.PRICELABS_API_KEY[:10]}...")

        # Fetch prices
        prices_url = f"{BASE_URL}/v1/listing_prices"
        body = {
            "listings": [
                {
                    "id": settings.LISTING_ID,
                    "pms": settings.PMS,
                    "dateFrom": date_from,
                    "dateTo": date_to,
                    "reason": True
                }
            ]
        }
        
        print(f"📡 Calling PriceLabs listing_prices API...")
        print(f"URL: {prices_url}")
        print(f"Headers: {HEADERS}")
        print(f"Body: {body}")
        
        resp = requests.post(prices_url, headers=HEADERS, json=body)
        print(f"Response status: {resp.status_code}")
        print(f"Response headers: {dict(resp.headers)}")
        print(f"Response text (first 500 chars): {resp.text[:500]}...")
        
        if resp.status_code != 200:
            print(f"❌ Listing prices API failed: {resp.status_code} - {resp.text}")
            # For demo purposes, if the real API fails, return mock data
            print("🔄 Falling back to mock data for demo...")
            return get_mock_data()
            
        try:
            response_data = resp.json()
            print(f"✅ Parsed JSON response. Type: {type(response_data)}")
            
            if isinstance(response_data, list) and len(response_data) > 0:
                data = response_data[0].get("data", [])
            else:
                print(f"❌ Unexpected response structure: {response_data}")
                return get_mock_data()
                
        except Exception as e:
            print(f"❌ Error parsing JSON response: {e}")
            print(f"Raw response: {resp.text}")
            return get_mock_data()
        
        print(f"✅ Retrieved {len(data)} nights of pricing data")

        # Fetch neighborhood data for market averages
        nb_url = f"{BASE_URL}/v1/neighborhood_data"
        nb_params = {"listing_id": settings.LISTING_ID, "pms": settings.PMS}
        
        print(f"📡 Calling PriceLabs neighborhood_data API...")
        print(f"URL: {nb_url}")
        print(f"Params: {nb_params}")
        
        nb_resp = requests.get(nb_url, headers=HEADERS, params=nb_params)
        print(f"Response status: {nb_resp.status_code}")
        
        if nb_resp.status_code != 200:
            print(f"⚠️  Warning: Could not fetch neighborhood data. Status: {nb_resp.status_code}")
            print(f"Response text: {nb_resp.text}")
            nb_data = None
        else:
            try:
                full_response = nb_resp.json()
                print(f"✅ Neighborhood API response received")
                print(f"Response structure: {list(full_response.keys())}")
                
                # Navigate to the actual data
                nb_data = full_response.get("data", {})
                if isinstance(nb_data, dict) and "data" in nb_data:
                    nb_data = nb_data["data"]
                
                print(f"Neighborhood data structure: {list(nb_data.keys()) if nb_data else 'None'}")
                
                # Debug: Print complete structure to understand occupancy data location
                if nb_data:
                    for key in nb_data.keys():
                        if "occ" in key.lower() or "canc" in key.lower():
                            print(f"🔍 Found potential occupancy key: {key}")
                            occ_section = nb_data[key]
                            if isinstance(occ_section, dict):
                                print(f"   Structure: {list(occ_section.keys())}")
                                if "Labels" in occ_section:
                                    print(f"   Labels: {occ_section['Labels']}")
                                if "Category" in occ_section:
                                    print(f"   Categories: {list(occ_section['Category'].keys())}")
                
                if nb_data and "Future Percentile Prices" in nb_data:
                    fpp = nb_data["Future Percentile Prices"]
                    print(f"Future Percentile Prices available categories: {list(fpp.get('Category', {}).keys())}")
                    print(f"Labels: {fpp.get('Labels', [])}")
                    
                    # Show sample of available dates
                    for cat, cat_data in fpp.get('Category', {}).items():
                        x_vals = cat_data.get('X_values', [])
                        if x_vals:
                            print(f"Category {cat} has {len(x_vals)} dates: {x_vals[:3]}...{x_vals[-3:] if len(x_vals) > 6 else x_vals[3:]}")
                            break
                else:
                    print("❌ No Future Percentile Prices found in neighborhood data")
                    
            except Exception as e:
                print(f"❌ Error parsing neighborhood response: {e}")
                nb_data = None

        # Structure data for LLM, filter to unbooked nights only
        nights = []
        print(f"🔄 Processing {len(data)} nights...")
        
        for night in data:
            if night.get("booking_status") == "booked":
                continue
            if night.get("unbookable", 0) != 0:
                continue
                
            date = night.get("date")
            your_price = night.get("user_price") or night.get("price")
            
            # Extract market average price using the new logic
            market_avg_price = extract_market_data_for_date(nb_data, date)
            
            # If no market data, use intelligent fallback
            if market_avg_price is None:
                market_avg_price = get_intelligent_market_fallback(your_price, date)
                print(f"📊 Using intelligent fallback for {date}: ${market_avg_price}")
            else:
                print(f"📊 Market data found for {date}: ${market_avg_price}")
            
            # Extract occupancy from neighborhood data
            occupancy = extract_occupancy_for_date(nb_data, date)
            
            # Extract event data
            event = None
            lead_time = None
            
            if "demand_desc" in night:
                event = night["demand_desc"]
                
            if "reason" in night and "listing_info" in night["reason"]:
                listing_info = night["reason"]["listing_info"]
                
                # DEBUG: Log the full listing_info structure
                print(f"🔍 LEAD TIME DEBUG for {date}:")
                print(f"   Full listing_info: {listing_info}")
                print(f"   Available keys: {list(listing_info.keys())}")
                
                # Calculate lead time from booking date data
                lead_time = None
                
                # Method 1: Use historical lead time from last year's data
                booked_date_stly = listing_info.get("booked_date_STLY")
                date_stly = listing_info.get("date_STLY")
                
                if booked_date_stly and date_stly and booked_date_stly != '-1':
                    try:
                        booked_dt = datetime.datetime.strptime(booked_date_stly, "%Y-%m-%d")
                        stay_dt = datetime.datetime.strptime(date_stly, "%Y-%m-%d")
                        historical_lead_time = (stay_dt - booked_dt).days
                        if historical_lead_time > 0:
                            lead_time = historical_lead_time
                            print(f"   ✅ Historical lead time: {historical_lead_time} days (booked {booked_date_stly} for {date_stly})")
                    except Exception as e:
                        print(f"   ❌ Error calculating historical lead time: {e}")
                
                # Method 2: Look for any explicit lead time fields (in case PriceLabs adds them)
                for key, value in listing_info.items():
                    if "lead" in key.lower() and isinstance(value, (int, float)) and value > 0:
                        lead_time = value
                        print(f"   ✅ Found explicit lead time field '{key}': {value}")
                        break
                
                # Log what we're using
                if lead_time:
                    print(f"   ✅ Final lead_time value: {lead_time} days")
                else:
                    print(f"   ⚠️ No lead time data available")
                    
                # Also log avg_los separately for context (but don't use as lead_time)
                avg_los = listing_info.get("avg_los", 0)
                print(f"   📊 Average Length of Stay: {avg_los} nights (separate from lead time)")
                print("="*50)
            
            # Calculate day of week
            day_of_week = None
            if date:
                try:
                    dt = datetime.datetime.strptime(date, "%Y-%m-%d")
                    day_of_week = dt.strftime("%A")
                except:
                    pass
            
            nights.append(NightData(
                date=date,
                your_price=your_price,
                market_avg_price=market_avg_price,
                occupancy=occupancy,
                event=event,
                day_of_week=day_of_week,
                lead_time=lead_time
            ))
        
        # Filter to available nights with valid pricing
        available_nights = [n for n in nights if n.your_price not in (None, -1.0) and (n.event or '').lower() != 'unavailable']
        
        print(f"✅ Filtered to {len(available_nights)} available nights with valid pricing")
        
        # If no nights after filtering, return mock data for demo
        if len(available_nights) == 0:
            print("⚠️ No available nights after filtering, returning mock data...")
            return get_mock_data()
        
        # Return first 5 nights for testing
        result_nights = available_nights[:5]
        
        for night in result_nights:
            print(f"📅 {night.date}: Your ${night.your_price} | Market ${night.market_avg_price} | {night.event}")
        
        return result_nights
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR in fetch_pricing_data: {e}")
        import traceback
        traceback.print_exc()
        # Return mock data for demo purposes
        print("🔄 Returning mock data due to error...")
        return get_mock_data()

def get_mock_data():
    """Return mock data for demo purposes when API fails"""
    return [
        NightData(
            date="2025-06-22",
            your_price=848.0,
            market_avg_price=533.0,
            occupancy=28.5,
            event="Low Demand",
            day_of_week="Sunday",
            lead_time=None
        ),
        NightData(
            date="2025-06-23",
            your_price=757.0,
            market_avg_price=500.0,
            occupancy=25.2,
            event="Low Demand",
            day_of_week="Monday",
            lead_time=None
        ),
        NightData(
            date="2025-06-24",
            your_price=771.0,
            market_avg_price=500.0,
            occupancy=22.8,
            event="Low Demand",
            day_of_week="Tuesday",
            lead_time=None
        ),
        NightData(
            date="2025-06-25",
            your_price=792.0,
            market_avg_price=505.0,
            occupancy=31.5,
            event="Low Demand",
            day_of_week="Wednesday",
            lead_time=None
        ),
        NightData(
            date="2025-06-29",
            your_price=880.0,
            market_avg_price=550.5,
            occupancy=35.2,
            event="Normal Demand",
            day_of_week="Sunday",
            lead_time=None
        )
    ]

class AnalyzeRequest(BaseModel):
    nights: List[NightData]
    model: Optional[str] = "gpt-4"

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str

@app.post("/analyze-pricing", response_model=List[LLMResult])
def analyze_pricing(req: AnalyzeRequest):
    print("📥 Received analyze request")
    print(f"📊 Request details: {len(req.nights)} nights, model: {req.model}")
    
    if not settings.OPENAI_API_KEY:
        print("❌ OpenAI API key not configured!")
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")
    
    print(f"✅ OpenAI API key available (length: {len(settings.OPENAI_API_KEY)})")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    results = []
    
    # Only process the first 5 nights for testing
    nights_to_process = req.nights[:5]
    print(f"🧠 Processing {len(nights_to_process)} nights with AI analysis...")
    
    for i, night in enumerate(nights_to_process):
        print(f"📅 Night {i+1}/5: {night.date} - ${night.your_price} vs ${night.market_avg_price} market")
    
    for night in nights_to_process:
        print(f"🔄 Analyzing night: {night.date}")
        
        # Enhanced prompt with market data context
        market_context = f"${night.market_avg_price:.0f}" if night.market_avg_price else "unavailable"
        
        # Determine if we're using real market data or intelligent fallback
        # Based on whether we have actual market_avg_price vs None
        has_real_market_data = night.market_avg_price is not None
        market_source = "real PriceLabs data" if has_real_market_data else "intelligent seasonal estimate"
        
        prompt = f"""Act as a revenue manager for a luxury STR property in Newport, RI. Analyze this night's data and provide pricing recommendations in valid JSON:

YOUR PROPERTY:
- Date: {night.date} ({night.day_of_week})
- Current Price: ${night.your_price}
- Market Average: {market_context} ({market_source})
- Local Demand: {night.event or 'Standard'}
- Area Occupancy: {night.occupancy}%

PRICING STRATEGY:
- Real market data: Price competitively vs actual market (10-20% premium for luxury)
- Estimated data: Be more conservative, focus on occupancy optimization
- Low demand: Aggressively undercut to capture bookings (15-25% reduction)
- High demand/events: Maintain or raise prices (10-30% premium)
- Weekend premium: Add 10-15% for Friday/Saturday nights

REQUIRED JSON FORMAT:
{{
  "suggested_price": [number],
  "confidence": [0-100 integer],
  "explanation": "[1-2 sentences max]",
  "insight_tag": "[short headline 3-5 words]"
}}"""

        try:
            print(f"🔮 Calling OpenAI Responses API (reasoning model) for {night.date}...")
            
            # Check if we're using a reasoning model (o3, o4-mini, etc.)
            if req.model.startswith(('o1', 'o3', 'o4')):
                # Use Responses API for reasoning models
                response = client.responses.create(
                    model=req.model,
                    reasoning={"effort": "low"},  # Use "low" to save tokens for output
                    input=[{"role": "user", "content": prompt}],
                    max_output_tokens=2000  # Much higher limit for reasoning models
                )
                content = response.output_text
                print(f"🧠 Reasoning tokens used: {response.usage.output_tokens_details.reasoning_tokens}")
                print(f"🧠 Total output tokens: {response.usage.output_tokens}")
                print(f"🧠 Context window usage: {response.usage.total_tokens} tokens")
            else:
                # Use Chat Completions API for regular models
                response = client.chat.completions.create(
                    model=req.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=256
                )
                content = response.choices[0].message.content
            
            print(f"🤖 OpenAI response received (length: {len(content)})")
            print(f"🤖 Full response: {content}")
            
            # Parse JSON from LLM output with improved reasoning model support
            import json as pyjson
            import re
            
            # Clean the content first - reasoning models sometimes add extra text
            content_clean = content.strip()
            
            # Try multiple JSON extraction methods
            parsed = None
            
            # Method 1: Direct JSON parsing
            try:
                parsed = pyjson.loads(content_clean)
                print(f"✅ Direct JSON parse successful: {parsed}")
            except Exception as e:
                print(f"⚠️ Direct JSON parse failed: {e}")
                
                # Method 2: Extract JSON from anywhere in the response
                json_patterns = [
                    r'\{[^{}]*"suggested_price"[^{}]*\}',  # Look for JSON with our key
                    r'\{.*?"suggested_price".*?\}',        # More flexible
                    r'\{.*\}',                             # Any JSON object
                ]
                
                for pattern in json_patterns:
                    matches = re.findall(pattern, content_clean, re.DOTALL)
                    for match in matches:
                        try:
                            parsed = pyjson.loads(match)
                            print(f"✅ Extracted JSON with pattern '{pattern}': {parsed}")
                            break
                        except:
                            continue
                    if parsed:
                        break
                
                # Method 3: Extract values using regex if JSON parsing completely fails
                if not parsed:
                    print(f"⚠️ All JSON extraction failed, trying regex extraction...")
                    print(f"Full content: {repr(content_clean)}")
                    
                    # Try to extract individual values
                    price_match = re.search(r'suggested_price["\s:]*(\d+(?:\.\d+)?)', content_clean)
                    confidence_match = re.search(r'confidence["\s:]*(\d+)', content_clean)
                    explanation_match = re.search(r'explanation["\s:]*["\']([^"\']+)["\']', content_clean)
                    tag_match = re.search(r'insight_tag["\s:]*["\']([^"\']+)["\']', content_clean)
                    
                    parsed = {
                        "suggested_price": float(price_match.group(1)) if price_match else None,
                        "confidence": int(confidence_match.group(1)) if confidence_match else None,
                        "explanation": explanation_match.group(1) if explanation_match else content_clean[:100],
                        "insight_tag": tag_match.group(1) if tag_match else "Parsing Issue"
                    }
                    print(f"✅ Regex extraction result: {parsed}")
                    
            # Final fallback if everything fails
            if not parsed:
                parsed = {"suggested_price": None, "confidence": None, "explanation": content_clean, "insight_tag": "Parse Failed"}
            
            # Safe parsing functions for LLM output
            def safe_float(val):
                if isinstance(val, (int, float)):
                    return float(val)
                if isinstance(val, str):
                    return float(val.replace('$', '').replace(',', '').strip())
                return None

            def safe_int(val):
                if isinstance(val, int):
                    return val
                if isinstance(val, str):
                    return int(val.strip())
                return None

            try:
                result = LLMResult(
                    date=night.date,
                    suggested_price=safe_float(parsed.get("suggested_price")),
                    confidence=safe_int(parsed.get("confidence")),
                    explanation=parsed.get("explanation"),
                    insight_tag=parsed.get("insight_tag")
                )
                print(f"✅ Created result: {result.json()}")
                results.append(result)
                
            except Exception as validation_error:
                print(f"❌ Validation error creating LLMResult: {validation_error}")
                print(f"Parsed data: {parsed}")
                # Create a fallback result
                results.append(LLMResult(
                    date=night.date,
                    suggested_price=night.your_price,  # fallback to current price
                    confidence=50,  # neutral confidence
                    explanation=f"Analysis unavailable due to validation error: {validation_error}",
                    insight_tag="Analysis Error"
                ))
                
        except Exception as e:
            print(f"❌ ERROR: OpenAI API call failed for {night.date}: {e}")
            print(f"❌ Exception type: {type(e).__name__}")
            import traceback
            print(f"❌ Full traceback: {traceback.format_exc()}")
            
            # Provide intelligent fallback analysis based on market data
            print(f"🔄 Using fallback analysis for {night.date}")
            if night.market_avg_price and night.your_price:
                price_gap = night.your_price - night.market_avg_price
                price_gap_pct = (price_gap / night.market_avg_price) * 100
                print(f"📊 Price gap: ${price_gap:.2f} ({price_gap_pct:.1f}%)")
                
                # Simple rule-based analysis as fallback
                if price_gap_pct > 50:  # Significantly overpriced
                    suggested = night.market_avg_price * 1.15  # 15% premium for luxury
                    explanation = f"Your price is {price_gap_pct:.0f}% above market. Suggest lowering to ${suggested:.0f} for better booking chances."
                    confidence = 85
                    tag = "Overpriced vs Market"
                    print(f"🔻 Fallback: Overpriced scenario")
                elif price_gap_pct < -10:  # Underpriced
                    suggested = night.market_avg_price * 1.1   # 10% premium
                    explanation = f"You're underpricing by {abs(price_gap_pct):.0f}%. Consider raising to ${suggested:.0f} to capture more revenue."
                    confidence = 80
                    tag = "Revenue Opportunity"
                    print(f"🔺 Fallback: Underpriced scenario")
                else:  # Well priced
                    suggested = night.your_price
                    explanation = f"Your pricing is competitive vs market average of ${night.market_avg_price:.0f}. Hold steady."
                    confidence = 75
                    tag = "Market Aligned"
                    print(f"➡️ Fallback: Market aligned scenario (THIS IS THE ISSUE!)")
            else:
                suggested = night.your_price
                explanation = "OpenAI analysis unavailable. Consider market conditions and demand when pricing."
                confidence = 50
                tag = "Fallback Analysis"
                print(f"❓ Fallback: No market data available")
            
            results.append(LLMResult(
                date=night.date,
                suggested_price=suggested,
                confidence=confidence,
                explanation=explanation,
                insight_tag=tag
            ))
    
    print(f"✅ Analysis complete. Returning {len(results)} results.")
    return results 

@app.post("/chat", response_model=ChatResponse)
def chat_with_ai(req: ChatRequest):
    """Chat with AI assistant - simple implementation without context for now"""
    print(f"💬 Received chat request: {req.message[:50]}...")
    
    if not settings.OPENAI_API_KEY:
        print("❌ OpenAI API key not configured!")
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")
    
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # Simple system prompt for now - we'll add property context later
        system_prompt = """You are a helpful AI assistant for short-term rental property management. 
You provide friendly, professional advice about property management, pricing, marketing, and guest experience.
Keep responses conversational and helpful."""
        
        print(f"🤖 Calling OpenAI Chat API...")
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.message}
            ],
            temperature=0.7,
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content
        print(f"✅ AI response received (length: {len(ai_response)})")
        
        # Generate or use provided conversation ID
        conversation_id = req.conversation_id or f"chat_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return ChatResponse(
            response=ai_response,
            conversation_id=conversation_id
        )
        
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True) 