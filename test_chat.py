#!/usr/bin/env python3
"""
Simple test script for the new Pydantic AI chat functionality
"""
import requests
import json

def test_chat_endpoint():
    """Test the /chat endpoint with a simple message"""
    
    # Local server URL
    url = "http://127.0.0.1:8000/chat"
    
    # Hardcoded API credentials for testing
    print("🔑 Using hardcoded test credentials...")
    api_key = "kruUYOXh0NJEQnuh29jkZ11LmycXBJpLNsvCuG6j"
    listing_id = "21f49919-2f73-4b9e-88c1-f460a316a5bc"
    pms = "yourporter"
    
    # Ask if user wants to include property context for testing
    include_context = input("Include sample property context for testing? (y/n, default: n): ").strip().lower()
    
    # Test message with API credentials
    payload = {
        "message": "What are the next booking gaps?",
        "conversation_id": None,  # Let it create a new conversation
        "api_key": api_key,
        "listing_id": listing_id,
        "pms": pms
    }
    
    # Add sample property context if requested
    if include_context == 'y':
        payload["property_context"] = {
            "mainGuest": "Leisure",
            "specialFeature": ["Location", "Exceptional View"],
            "pricingGoal": ["Max Price"]
        }
        print("✅ Added sample property context: Leisure guests, Location + View, Max Price strategy")
    
    try:
        print("🧪 Testing Pydantic AI chat endpoint...")
        print(f"📤 Sending: {payload['message']}")
        print("⏳ Waiting for response...")
        
        response = requests.post(url, json=payload, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print("\n✅ SUCCESS!")
            print(f"🤖 AI Response: {data['response']}")
            print(f"🆔 Conversation ID: {data['conversation_id']}")
            return True
        else:
            print(f"\n❌ FAILED: {response.status_code}")
            print(f"Error: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("\n❌ CONNECTION ERROR: Server not running?")
        print("💡 Start the server first with: python test_chat.py --start-server")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return False

def start_server():
    """Start the FastAPI server"""
    import subprocess
    import sys
    
    print("🚀 Starting FastAPI server...")
    print("📍 Server will be available at: http://127.0.0.1:8000")
    print("📖 API docs at: http://127.0.0.1:8000/docs")
    print("🛑 Press Ctrl+C to stop\n")
    
    try:
        subprocess.run([sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000", "--reload"])
    except KeyboardInterrupt:
        print("\n🛑 Server stopped.")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--start-server":
        start_server()
    elif len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("🧪 mAIrble Pydantic AI Test Help")
        print("=" * 40)
        print("Usage:")
        print("  python test_chat.py --start-server    # Start the FastAPI server")
        print("  python test_chat.py                   # Run interactive test (asks for API keys)")
        print("  python test_chat.py --mock            # Run test with mock data (no real API)")
        print("  python test_chat.py --help            # Show this help")
    elif len(sys.argv) > 1 and sys.argv[1] == "--mock":
        print("🧪 Running mock test (no real API calls)...")
        print("💡 This tests the endpoint but uses placeholder API keys")
        print("⚠️  The tool will still try to call PriceLabs but will get API errors")
        
        # Test with mock data - will show the tool calling works even if API fails
        url = "http://127.0.0.1:8000/chat"
        payload = {
            "message": "Is July 27-29 available?",
            "conversation_id": None,
            "api_key": "fake_test_key_12345",
            "listing_id": "fake_test_listing_67890", 
            "pms": "airbnb",
            "property_context": {
                "mainGuest": "Business",
                "specialFeature": ["Location", "Luxury/Design"],
                "pricingGoal": ["Max Price", "Avoid Bad Guests"]
            }
        }
        
        try:
            print(f"📤 Sending test message with mock credentials...")
            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print("\n✅ SUCCESS! (Tool calling works even with mock data)")
                print(f"🤖 AI Response: {data['response']}")
                print(f"🆔 Conversation ID: {data['conversation_id']}")
            else:
                print(f"\n❌ FAILED: {response.status_code}")
                print(f"Error: {response.text}")
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
    else:
        print("=" * 50)
        print("🧪 mAIrble Pydantic AI Test")
        print("=" * 50)
        
        success = test_chat_endpoint()
        
        if not success:
            print("\n💡 To start the server, run:")
            print("   python test_chat.py --start-server")
            print("\n💡 Then in another terminal, run:")
            print("   python test_chat.py                    # Interactive test")
            print("   python test_chat.py --mock             # Quick mock test")
            print("   python test_chat.py --help             # Show help") 