from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import requests
import datetime
import os
import uuid
from openai import OpenAI
from config import get_settings

# Get application settings
settings = get_settings()

# In-memory storage for conversations (production would use database)
conversations_store: Dict[str, Dict] = {}

# Maximum messages to keep in conversation history (to manage token limits)
MAX_CONVERSATION_HISTORY = 20

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
    api_key: str  # PriceLabs API key from frontend
    listing_id: Optional[str] = None  # Listing ID from frontend
    pms: Optional[str] = None  # PMS from frontend
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
    # New valuable fields from PriceLabs
    adr_last_year: Optional[float]  # ADR_STLY - historical benchmark
    neighborhood_demand: Optional[str]  # nhood_demand - granular demand level
    min_price_limit: Optional[float]  # minimum_price - pricing floor
    avg_los_last_year: Optional[float]  # avg_los_STLY - historical stay length
    seasonal_profile: Optional[str]  # minstay_seasonal_profile - seasonal context

class LLMResult(BaseModel):
    date: str
    suggested_price: Optional[float]
    confidence: Optional[int]
    explanation: Optional[str]
    insight_tag: Optional[str]

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime.datetime

class ConversationInfo(BaseModel):
    conversation_id: str
    created_at: datetime.datetime
    last_message_at: datetime.datetime
    message_count: int
    property_context: Optional[dict] = None

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    property_context: Optional[dict] = None  # Guest profile, competitive advantage, booking patterns

class ChatResponse(BaseModel):
    response: str
    conversation_id: str

class GetConversationRequest(BaseModel):
    conversation_id: str

class GetConversationResponse(BaseModel):
    conversation_id: str
    messages: List[ChatMessage]
    property_context: Optional[dict] = None

def create_conversation(conversation_id: str, property_context: Optional[dict] = None) -> None:
    """Create a new conversation in storage"""
    conversations_store[conversation_id] = {
        "messages": [],
        "created_at": datetime.datetime.now(),
        "last_message_at": datetime.datetime.now(),
        "property_context": property_context
    }
    print(f"📝 Created new conversation: {conversation_id}")

def add_message_to_conversation(conversation_id: str, role: str, content: str) -> None:
    """Add a message to the conversation history"""
    if conversation_id not in conversations_store:
        create_conversation(conversation_id)
    
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.datetime.now()
    }
    
    conversations_store[conversation_id]["messages"].append(message)
    conversations_store[conversation_id]["last_message_at"] = datetime.datetime.now()
    
    # Limit conversation history to prevent token overflow
    if len(conversations_store[conversation_id]["messages"]) > MAX_CONVERSATION_HISTORY:
        # Keep the system message (if any) and the most recent messages
        messages = conversations_store[conversation_id]["messages"]
        system_messages = [msg for msg in messages if msg["role"] == "system"]
        recent_messages = messages[-(MAX_CONVERSATION_HISTORY-len(system_messages)):]
        conversations_store[conversation_id]["messages"] = system_messages + recent_messages
        print(f"🗂️ Trimmed conversation {conversation_id} to {len(conversations_store[conversation_id]['messages'])} messages")

def get_conversation_messages(conversation_id: str) -> List[Dict]:
    """Get all messages from a conversation"""
    if conversation_id not in conversations_store:
        return []
    return conversations_store[conversation_id]["messages"]

def build_openai_messages(conversation_id: str, system_prompt: str) -> List[Dict]:
    """Build OpenAI messages array with conversation history"""
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history
    conversation_messages = get_conversation_messages(conversation_id)
    for msg in conversation_messages:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })
    
    return messages

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
        HEADERS = {"X-API-Key": req.api_key}
        today = datetime.date.today()
        date_from = req.date_from or today.isoformat()
        date_to = req.date_to or (today + datetime.timedelta(days=90)).isoformat()
        
        # Use provided values or fallback to defaults
        listing_id = req.listing_id or settings.LISTING_ID
        pms = req.pms or settings.PMS

        print(f"🔍 Fetching pricing data for listing {listing_id} from {date_from} to {date_to}")
        print(f"🔑 Using API key: {req.api_key[:10]}...")
        print(f"🏠 PMS: {pms}")

        # Fetch prices
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
            
            # Return proper error messages based on status code
            if resp.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid PriceLabs API key. Please check your API key and try again.")
            elif resp.status_code == 403:
                raise HTTPException(status_code=403, detail="PriceLabs API access denied. Please verify your API key permissions.")
            elif resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Listing not found. Please check your listing ID and try again.")
            else:
                raise HTTPException(status_code=resp.status_code, detail=f"PriceLabs API error: {resp.text}")
            
        try:
            response_data = resp.json()
            print(f"✅ Parsed JSON response. Type: {type(response_data)}")
            
            if isinstance(response_data, list) and len(response_data) > 0:
                data = response_data[0].get("data", [])
            else:
                print(f"❌ Unexpected response structure: {response_data}")
                raise HTTPException(status_code=500, detail="Unexpected response format from PriceLabs API")
                
        except Exception as e:
            print(f"❌ Error parsing JSON response: {e}")
            print(f"Raw response: {resp.text}")
            raise HTTPException(status_code=500, detail="Failed to parse PriceLabs API response")
        
        print(f"✅ Retrieved {len(data)} nights of pricing data")

        # Fetch neighborhood data for market averages
        nb_url = f"{BASE_URL}/v1/neighborhood_data"
        nb_params = {"listing_id": listing_id, "pms": pms}
        
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
            
            # Extract valuable PriceLabs fields for AI context
            adr_last_year = None
            neighborhood_demand = None
            min_price_limit = None
            avg_los_last_year = None
            seasonal_profile = None
            
            if "reason" in night and "listing_info" in night["reason"]:
                listing_info = night["reason"]["listing_info"]
                
                # Extract and convert PriceLabs fields
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
                    print(f"   ⚠️ Error parsing PriceLabs fields: {e}")

            nights.append(NightData(
                date=date,
                your_price=your_price,
                market_avg_price=market_avg_price,
                occupancy=occupancy,
                event=event,
                day_of_week=day_of_week,
                lead_time=lead_time,
                adr_last_year=adr_last_year,
                neighborhood_demand=neighborhood_demand,
                min_price_limit=min_price_limit,
                avg_los_last_year=avg_los_last_year,
                seasonal_profile=seasonal_profile
            ))
        
        # Filter to available nights with valid pricing
        available_nights = [n for n in nights if n.your_price not in (None, -1.0) and (n.event or '').lower() != 'unavailable']
        
        print(f"✅ Filtered to {len(available_nights)} available nights with valid pricing")
        
        # If no nights after filtering, return error
        if len(available_nights) == 0:
            print("⚠️ No available nights found after filtering")
            raise HTTPException(status_code=404, detail="No available nights found for the specified listing. Check your listing ID or try a different date range.")
        
        # Determine how many nights to return based on request parameters
        if req.date_from and req.date_to:
            # For custom date ranges, return all available nights (no limit)
            result_nights = available_nights
            print(f"📅 Custom date range requested: returning all {len(result_nights)} available nights")
        else:
            # For default requests, return first 5 nights (existing behavior)
            result_nights = available_nights[:5]
            print(f"📅 Default request: returning first {len(result_nights)} nights")
        
        for night in result_nights:
            historical_info = f" | LY: ${night.adr_last_year}" if night.adr_last_year else ""
            demand_info = f" | Demand: {night.neighborhood_demand}" if night.neighborhood_demand else ""
            print(f"📅 {night.date}: Your ${night.your_price} | Market ${night.market_avg_price} | {night.event}{historical_info}{demand_info}")
        
        return result_nights
        
    except HTTPException:
        # Re-raise HTTP exceptions (our proper error responses)
        raise
    except Exception as e:
        print(f"❌ CRITICAL ERROR in fetch_pricing_data: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error occurred while fetching pricing data")

class AnalyzeRequest(BaseModel):
    nights: List[NightData]
    model: Optional[str] = "gpt-4"

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
    
    # Process all provided nights (frontend handles chunking)
    nights_to_process = req.nights
    print(f"🧠 Processing {len(nights_to_process)} nights with AI analysis...")
    
    for i, night in enumerate(nights_to_process):
        historical_context = f" (LY: ${night.adr_last_year})" if night.adr_last_year else ""
        demand_level = f" D{night.neighborhood_demand}" if night.neighborhood_demand else ""
        print(f"📅 Night {i+1}/{len(nights_to_process)}: {night.date} - ${night.your_price} vs ${night.market_avg_price} market{historical_context}{demand_level}")
    
    for night in nights_to_process:
        print(f"🔄 Analyzing night: {night.date}")
        
        # Enhanced prompt with market data context
        market_context = f"${night.market_avg_price:.0f}" if night.market_avg_price else "unavailable"
        
        # Determine if we're using real market data or intelligent fallback
        # Based on whether we have actual market_avg_price vs None
        has_real_market_data = night.market_avg_price is not None
        market_source = "real PriceLabs data" if has_real_market_data else "intelligent seasonal estimate"
        
        # Build enhanced context with new PriceLabs data
        historical_context = ""
        if night.adr_last_year:
            yoy_change = ((night.your_price - night.adr_last_year) / night.adr_last_year) * 100
            historical_context = f"Last year: ${night.adr_last_year:.0f} (YoY change: {yoy_change:+.0f}%)"
        
        demand_context = f"Demand Level: {night.neighborhood_demand or 'Unknown'}"
        
        constraints_context = ""
        if night.min_price_limit:
            constraints_context = f"Minimum Price: ${night.min_price_limit:.0f}"
        
        stay_context = ""
        if night.avg_los_last_year:
            stay_context = f"Typical Stay: {night.avg_los_last_year:.0f} nights"

        prompt = f"""Act as a revenue manager for a luxury STR property in Newport, RI. Analyze this night's data and provide pricing recommendations in valid JSON:

YOUR PROPERTY:
- Date: {night.date} ({night.day_of_week})
- Current Price: ${night.your_price}
- Market Average: {market_context} ({market_source})
- {historical_context}
- {demand_context}
- Local Event: {night.event or 'Standard'}
- Area Occupancy: {night.occupancy}%
- {stay_context}
- {constraints_context}
- Season: {night.seasonal_profile or 'Standard'}

ENHANCED PRICING STRATEGY:
- Historical Performance: Factor in last year's proven rate vs current pricing
- Demand Signals: Use neighborhood demand level (1=low, 5=high) for pricing
- Price Constraints: Respect minimum price limit
- Stay Patterns: Consider typical length of stay for rate optimization
- Real market data: Price competitively vs actual market (10-20% premium for luxury)
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

        # LOG: Complete prompt sent to LLM
        print(f"📝 COMPLETE PROMPT SENT TO LLM:")
        print("="*60)
        print(prompt)
        print("="*60)

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
    """Chat with AI assistant with conversation history and personalized property context"""
    print(f"💬 Received chat request: {req.message[:50]}...")
    
    if not settings.OPENAI_API_KEY:
        print("❌ OpenAI API key not configured!")
        raise HTTPException(status_code=500, detail="OpenAI API key not configured.")
    
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        # Generate or use provided conversation ID
        conversation_id = req.conversation_id or f"chat_{uuid.uuid4().hex[:8]}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create conversation if it doesn't exist
        if conversation_id not in conversations_store:
            create_conversation(conversation_id, req.property_context)
        
        # Update property context if provided
        if req.property_context and conversation_id in conversations_store:
            conversations_store[conversation_id]["property_context"] = req.property_context
            print("📝 Updated property context for conversation")
        
        # Build enhanced system prompt with property context
        base_prompt = """You are an expert AI assistant for short-term rental property management, specializing in luxury properties. 
You provide intelligent, actionable advice about pricing, marketing, guest experience, and revenue optimization.
Keep responses conversational but professional, and always consider the specific property context provided.
Remember previous messages in this conversation to provide contextual and relevant advice."""
        
        # Get property context from conversation or request
        property_context = req.property_context or conversations_store.get(conversation_id, {}).get("property_context")
        
        context_prompt = ""
        if property_context:
            print("📝 Including property context in system prompt...")
            main_guest = property_context.get('mainGuest', '')
            special_feature = property_context.get('specialFeature', '')
            pricing_goal = property_context.get('pricingGoal', '')
            
            if main_guest or special_feature or pricing_goal:
                # Build highly specific context based on user selections
                guest_context = ""
                if main_guest == "Leisure":
                    guest_context = """TARGET GUESTS: Leisure travelers who book further in advance, are sensitive to total cost, and prioritize amenities and experiences. Key booking periods: weekends, holidays, summer. Price sensitivity: High for total cost. Lead time: Longer advance bookings."""
                elif main_guest == "Business":
                    guest_context = """TARGET GUESTS: Business travelers who book last-minute, are less price-sensitive, and prioritize location, workspace, and reliable internet. Key booking periods: weekdays. Price sensitivity: Low. Lead time: Short, last-minute bookings."""
                elif main_guest == "Groups":
                    guest_context = """TARGET GUESTS: Groups (parties, retreats, events) who are highly sensitive to per-person cost and look for capacity and entertainment amenities. Key booking periods: weekends and events. Price sensitivity: High for per-person cost. Focus: Group capacity and entertainment value."""
                
                feature_context = ""
                if special_feature == "Location":
                    feature_context = """COMPETITIVE ADVANTAGE: Prime location (beachfront, downtown, mountain view) - proximity to key attractions, natural beauty, or urban convenience. This is often the #1 driver for guests. Price premium justified by location exclusivity."""
                elif special_feature == "Unique Amenity":
                    feature_context = """COMPETITIVE ADVANTAGE: Unique amenity (hot tub, pool, sauna, home theater) - specific features that are rare or highly desirable in your market. Strong premium pricing justified by amenity scarcity."""
                elif special_feature == "Size/Capacity":
                    feature_context = """COMPETITIVE ADVANTAGE: Large size/capacity (sleeps 10+, multiple bedrooms/baths) - ability to accommodate larger groups. Higher per-night rates and less competition in large-group segment."""
                elif special_feature == "Luxury/Design":
                    feature_context = """COMPETITIVE ADVANTAGE: Luxury/high-end design (premium finishes, architecturally unique) - appeals to discerning guests willing to pay significantly more for aesthetic and comfort."""
                elif special_feature == "Pet-Friendly":
                    feature_context = """COMPETITIVE ADVANTAGE: Pet-friendly with specific features (fenced yard) - taps into underserved market segment willing to pay premium for pet accommodation."""
                elif special_feature == "Exceptional View":
                    feature_context = """COMPETITIVE ADVANTAGE: Exceptional view (ocean, city skyline, mountain panorama) - visual appeal that significantly enhances guest experience and justifies higher rates."""
                elif special_feature == "Unique Experience":
                    feature_context = """COMPETITIVE ADVANTAGE: Unique experience (historic property, farm stay, glamping) - offers something truly different that guests can't find elsewhere, creating strong demand and pricing power."""
                
                strategy_context = ""
                if pricing_goal == "Fill Dates":
                    strategy_context = """PRICING STRATEGY: FILL DATES PRIORITY - Always prioritize getting bookings, even at lower prices. The owner would rather get $750 than $0. Be aggressive with discounts to avoid empty nights. Focus on occupancy over rate optimization."""
                elif pricing_goal == "Max Price":
                    strategy_context = """PRICING STRATEGY: MAXIMIZE PRICE - Push for the highest possible rates, even if it means fewer bookings. Highlight the property's special features and target guest's willingness to pay. Premium pricing is the priority."""
                elif pricing_goal == "Avoid Bad Guests":
                    strategy_context = """PRICING STRATEGY: GUEST QUALITY FILTER - Recommend pricing strategies that naturally filter for higher-quality guests. Better to leave money on the table or have lower occupancy than deal with problem guests. Suggest price floors to maintain guest quality."""
                
                context_prompt = f"""

PROPERTY CONTEXT - Use this to personalize ALL pricing and marketing advice:

{guest_context}

{feature_context}

{strategy_context}

CRITICAL: Always reference this specific context when providing advice. Your recommendations must align with the guest type, competitive advantage, and pricing priority. This context gives you advantages that PriceLabs doesn't have - use it to provide superior, personalized recommendations."""
        
        system_prompt = base_prompt + context_prompt
        
        # Add user message to conversation history
        add_message_to_conversation(conversation_id, "user", req.message)
        
        # Build OpenAI messages with full conversation history
        messages = build_openai_messages(conversation_id, system_prompt)
        
        print(f"🤖 Calling OpenAI Chat API with conversation history ({len(messages)-1} previous messages)...")
        print(f"🗂️ Conversation ID: {conversation_id}")
        
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content
        print(f"✅ AI response received (length: {len(ai_response)})")
        
        # Add AI response to conversation history
        add_message_to_conversation(conversation_id, "assistant", ai_response)
        
        print(f"💾 Conversation {conversation_id} now has {len(conversations_store[conversation_id]['messages'])} messages")
        
        return ChatResponse(
            response=ai_response,
            conversation_id=conversation_id
        )
        
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat service error: {str(e)}")

@app.post("/get-conversation", response_model=GetConversationResponse)
def get_conversation(req: GetConversationRequest):
    """Retrieve full conversation history"""
    print(f"📖 Retrieving conversation: {req.conversation_id}")
    
    if req.conversation_id not in conversations_store:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conversation = conversations_store[req.conversation_id]
    
    # Convert stored messages to response format
    messages = []
    for msg in conversation["messages"]:
        messages.append(ChatMessage(
            role=msg["role"],
            content=msg["content"],
            timestamp=msg["timestamp"]
        ))
    
    return GetConversationResponse(
        conversation_id=req.conversation_id,
        messages=messages,
        property_context=conversation.get("property_context")
    )

@app.get("/conversations", response_model=List[ConversationInfo])
def list_conversations():
    """List all conversations"""
    print(f"📋 Listing {len(conversations_store)} conversations")
    
    conversations = []
    for conv_id, conv_data in conversations_store.items():
        conversations.append(ConversationInfo(
            conversation_id=conv_id,
            created_at=conv_data["created_at"],
            last_message_at=conv_data["last_message_at"],
            message_count=len(conv_data["messages"]),
            property_context=conv_data.get("property_context")
        ))
    
    # Sort by last message time (most recent first)
    conversations.sort(key=lambda x: x.last_message_at, reverse=True)
    
    return conversations

@app.delete("/conversation/{conversation_id}")
def delete_conversation(conversation_id: str):
    """Delete a conversation"""
    print(f"🗑️ Deleting conversation: {conversation_id}")
    
    if conversation_id not in conversations_store:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    del conversations_store[conversation_id]
    
    return {"message": f"Conversation {conversation_id} deleted successfully"}

class SingleOverrideRequest(BaseModel):
    api_key: str
    listing_id: str
    pms: str
    date: str
    price: float
    price_type: str = "fixed"  # Default to fixed
    currency: str = "USD"
    reason: str = "Manual update via mAIrble"
    update_children: bool = False

class SingleOverrideResponse(BaseModel):
    success: bool
    message: str
    updated_date: Optional[str] = None
    error_details: Optional[str] = None

@app.post("/update-single-price", response_model=SingleOverrideResponse)
def update_single_price(req: SingleOverrideRequest):
    """Update pricing for a single date with explicit user control"""
    try:
        print(f"🔄 Updating price for {req.date} to ${req.price} ({req.price_type})")
        
        BASE_URL = "https://api.pricelabs.co"
        HEADERS = {"X-API-Key": req.api_key}
        
        # Validate price_type
        if req.price_type not in ["fixed", "percent"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid price_type. Must be 'fixed' or 'percent'"
            )
        
        # Validate percentage range if percent type
        if req.price_type == "percent" and (req.price < -75 or req.price > 500):
            raise HTTPException(
                status_code=400,
                detail="Percentage must be between -75 and 500"
            )
        
        # PriceLabs overrides endpoint
        url = f"{BASE_URL}/v1/listings/{req.listing_id}/overrides"
        
        # Prepare payload exactly as per PriceLabs API spec
        payload = {
            "pms": req.pms,
            "update_children": req.update_children,
            "overrides": [
                {
                    "date": req.date,
                    "price": str(int(req.price)) if float(req.price).is_integer() else str(req.price),  # Clean price format
                    "price_type": req.price_type,
                    "currency": req.currency,
                    "reason": req.reason
                }
            ]
        }
        
        print(f"📤 Sending to PriceLabs: {payload}")
        
        response = requests.post(url, headers=HEADERS, json=payload)
        
        print(f"📥 PriceLabs response: {response.status_code}")
        print(f"Response body: {response.text}")
        
        if response.status_code != 200:
            error_message = "Unknown error"
            try:
                error_data = response.json()
                error_message = error_data.get('message', error_data.get('detail', str(error_data)))
            except:
                error_message = response.text or f"HTTP {response.status_code}"
            
            print(f"❌ PriceLabs API error: {error_message}")
            
            return SingleOverrideResponse(
                success=False,
                message=f"Failed to update price: {error_message}",
                error_details=error_message
            )
        
        # Parse successful response
        result = response.json()
        
        # Check if our date was successfully updated
        # PriceLabs returns: {"overrides": [...], "child_listings_update_info": {}}
        updated_dates = []
        if "overrides" in result and isinstance(result["overrides"], list):
            updated_dates = [item.get("date") for item in result["overrides"] if item.get("date")]
        
        if req.date in updated_dates:
            return SingleOverrideResponse(
                success=True,
                message=f"Successfully updated price for {req.date} to ${req.price}",
                updated_date=req.date
            )
        else:
            return SingleOverrideResponse(
                success=False,
                message=f"Price update may have failed - {req.date} not found in response",
                error_details=str(result)
            )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return SingleOverrideResponse(
            success=False,
            message=f"Internal error: {str(e)}",
            error_details=str(e)
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True) 