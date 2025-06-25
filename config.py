"""
Production-ready configuration management for mAIrble Backend
Uses environment variables with fallbacks for development
"""
import os
from typing import Optional

class Settings:
    """Application settings with environment variable support"""
    
    # API Keys - Set via environment variables in production
    PRICELABS_API_KEY: str = os.getenv("PRICELABS_API_KEY", "your_pricelabs_api_key_here")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "your_openai_api_key_here")
    
    # Property Configuration
    LISTING_ID: str = os.getenv("LISTING_ID", "21f49919-2f73-4b9e-88c1-f460a316a5bc")
    PMS: str = os.getenv("PMS", "yourporter")
    
    # Server Configuration
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    
    # CORS Configuration
    ALLOWED_ORIGINS: list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://*.netlify.app",
        "https://*.vercel.app",
        "exp://",  # Expo development
        "http://localhost:19000",  # Expo web
        "http://localhost:19006",  # Expo web alternative
    ]
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"

# Global settings instance
settings = Settings()

def get_settings() -> Settings:
    """Get application settings"""
    return settings 