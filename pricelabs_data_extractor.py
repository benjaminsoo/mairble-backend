import requests
import datetime
import json
import os

API_KEY = os.environ.get("PRICELABS_API_KEY", "YOUR_API_KEY")
BASE_URL = "https://api.pricelabs.co"
HEADERS = {"X-API-Key": API_KEY}

def get_listings():
    url = f"{BASE_URL}/v1/listings"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()["listings"]

def get_listing_prices(listing_id, pms, date_from, date_to):
    url = f"{BASE_URL}/v1/listing_prices"
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
    resp = requests.post(url, headers=HEADERS, json=body)
    resp.raise_for_status()
    return resp.json()[0]["data"]

def get_neighborhood_data(listing_id, pms):
    url = f"{BASE_URL}/v1/neighborhood_data"
    params = {"listing_id": listing_id, "pms": pms}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()["data"]["data"]

def build_nightly_records():
    listings = get_listings()
    today = datetime.date.today()
    date_from = (today - datetime.timedelta(days=90)).isoformat()
    date_to = (today + datetime.timedelta(days=90)).isoformat()
    all_nightly_records = []

    for listing in listings:
        listing_id = listing["id"]
        pms = listing["pms"]
        name = listing["name"]
        print(f"Processing {name} ({listing_id})")

        # Fetch nightly prices
        try:
            nightly_data = get_listing_prices(listing_id, pms, date_from, date_to)
        except Exception as e:
            print(f"Failed to fetch prices for {listing_id}: {e}")
            continue

        # Fetch market data
        try:
            market_data = get_neighborhood_data(listing_id, pms)
        except Exception as e:
            print(f"Failed to fetch market data for {listing_id}: {e}")
            market_data = None

        for night in nightly_data:
            # Only include unbooked nights
            if night.get("booking_status") == "booked":
                continue

            # Market price and occupancy (example: 50th percentile and occupancy)
            market_avg_price = None
            market_occupancy = None
            booking_lead_time = None
            events = []
            day_of_week = datetime.datetime.strptime(night["date"], "%Y-%m-%d").strftime("%A")
            last_year_price = None

            if market_data:
                # Example: get 50th percentile price for the right bedroom category
                bedroom_key = str(listing.get("no_of_bedrooms", 1))
                try:
                    idx = market_data["Future Percentile Prices"]["Labels"].index("50th Percentile")
                    date_idx = market_data["Future Percentile Prices"]["Category"][bedroom_key]["X_values"].index(night["date"])
                    market_avg_price = market_data["Future Percentile Prices"]["Category"][bedroom_key]["Y_values"][idx][date_idx]
                except Exception:
                    pass
                try:
                    occ_idx = market_data["Future Occ/New/Canc"]["Labels"].index("Occupancy")
                    occ_date_idx = market_data["Future Occ/New/Canc"]["Category"][bedroom_key]["X_values"].index(night["date"])
                    market_occupancy = market_data["Future Occ/New/Canc"]["Category"][bedroom_key]["Y_values"][occ_idx][0][occ_date_idx]
                except Exception:
                    pass

            record = {
                "date": night["date"],
                "your_price": night.get("user_price") or night.get("price"),
                "market_avg_price": market_avg_price,
                "market_occupancy": market_occupancy,
                "booking_lead_time": booking_lead_time,
                "events": events,
                "day_of_week": day_of_week,
                "last_year_price": last_year_price,
                "listing_id": listing_id,
                "listing_name": name
            }
            all_nightly_records.append(record)

    return all_nightly_records

if __name__ == "__main__":
    records = build_nightly_records()
    with open("nightly_records.json", "w") as f:
        json.dump(records, f, indent=2)
    print("Exported nightly_records.json") 