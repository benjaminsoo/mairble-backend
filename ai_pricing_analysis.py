import os
import json
import time
from openai import OpenAI

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "YOUR_OPENAI_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

PROMPT_TEMPLATE = """
Here's the pricing and occupancy data for {date} for a {bedrooms}-bedroom STR in {market}. The host's current price is ${your_price}.
Market average price: ${market_avg_price}
Occupancy: {market_occupancy}%
It's a {day_of_week}{event_str}. Booking lead time for similar properties is {booking_lead_time} days. Last year, the host got ${last_year_price} for this date.

Please:
1. Recommend an ideal price.
2. Explain why.
3. Rate confidence from 0–100.
4. Include any contextual risks/opportunities.
"""

def format_prompt(record):
    event_str = f" with {', '.join(record['events'])}" if record['events'] else " with no major events"
    return PROMPT_TEMPLATE.format(
        date=record['date'],
        bedrooms=2,  # You can adjust this or pull from record if available
        market="Newport, RI",  # You can adjust this or pull from record if available
        your_price=record['your_price'],
        market_avg_price=record.get('market_avg_price', 'N/A'),
        market_occupancy=record.get('market_occupancy', 'N/A'),
        day_of_week=record['day_of_week'],
        event_str=event_str,
        booking_lead_time=record.get('booking_lead_time', 'N/A'),
        last_year_price=record.get('last_year_price', 'N/A')
    )

def analyze_night(record):
    prompt = format_prompt(record)
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"OpenAI API error: {e}")
        return None

def main():
    with open("nightly_records.json") as f:
        records = json.load(f)
    results = []
    for i, record in enumerate(records):
        print(f"Analyzing {record['date']} for {record['listing_name']}...")
        ai_output = analyze_night(record)
        record['ai_analysis'] = ai_output
        results.append(record)
        time.sleep(1.2)  # To avoid rate limits
    with open("nightly_records_with_ai.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Exported nightly_records_with_ai.json")

if __name__ == "__main__":
    main() 