# mAIrble Backend

AI-powered pricing analysis backend for Short Term Rental hosts using PriceLabs data and OpenAI GPT-4.

## Environment Setup

### 1. Create Environment File

Copy the example configuration file and add your API keys:

```bash
cp config.example.env .env
```

### 2. Add Your API Keys

Edit the `.env` file and add your actual API keys:

```bash
# PriceLabs API Key
# Get this from your PriceLabs account dashboard
PRICELABS_API_KEY=your_actual_pricelabs_api_key_here

# OpenAI API Key  
# Get this from https://platform.openai.com/account/api-keys
OPENAI_API_KEY=your_actual_openai_api_key_here

# Server Configuration
HOST=127.0.0.1
PORT=8000
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Server

```bash
# Load environment variables and start the server
source .env && uvicorn app:app --host $HOST --port $PORT --reload
```

Or manually:

```bash
OPENAI_API_KEY="your_key" PRICELABS_API_KEY="your_key" uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

## Security Notes

- **Never commit `.env` files** - they contain sensitive API keys
- **Use environment variables** for all sensitive configuration
- **Rotate API keys regularly** for security
- **Use HTTPS in production** for secure API communication

## API Endpoints

- `POST /fetch-pricing-data` - Fetch pricing data from PriceLabs
- `POST /analyze-pricing` - Analyze pricing with OpenAI GPT-4

## Getting API Keys

### PriceLabs API Key
1. Log into your PriceLabs account
2. Go to Account Settings > API
3. Generate a new API key
4. Copy the key to your `.env` file

### OpenAI API Key
1. Go to https://platform.openai.com/account/api-keys
2. Create a new secret key
3. Copy the key to your `.env` file

## Development

The server will automatically reload when you make changes to the code. Make sure to set the environment variables before starting the server.

## Production Deployment

For production deployment:
1. Use a proper secret management system
2. Set environment variables at the system level
3. Use HTTPS for all API communications
4. Implement proper logging and monitoring 