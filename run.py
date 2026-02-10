#!/usr/bin/env python3
"""
Simple script to run the FastAPI development server.
Usage: python run.py
"""
import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,  # Enable auto-reload for development
    )
