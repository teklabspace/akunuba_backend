@echo off
echo ========================================
echo FastAPI Server Restart
echo ========================================
echo.

echo Checking for running server on port 8000...
netstat -ano | findstr :8000 >nul
if %ERRORLEVEL% EQU 0 (
    echo Found server running on port 8000
    echo.
    echo Please stop the server manually (Ctrl+C in the terminal where it's running)
    echo Or kill the process using Task Manager
    echo.
    echo Then run this script again to start the server.
    pause
    exit /b 0
)

echo No server found on port 8000
echo.
echo Starting FastAPI server...
echo.

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause
