"""Start server without blocking operations"""
import uvicorn
import sys
import os

# Set environment to skip scheduler if needed
os.environ.setdefault("APP_ENV", "development")

if __name__ == "__main__":
    print("Starting Fullego Backend Server...")
    print("Press Ctrl+C to stop")
    print("-" * 60)
    
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"\nError starting server: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

