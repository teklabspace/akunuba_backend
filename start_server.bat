@echo off
echo ========================================
echo Starting Fullego Backend Server
echo ========================================
echo.
echo Checking Python...
python --version
echo.
echo Starting server on http://localhost:8000
echo.
echo IMPORTANT: Keep this window open!
echo To stop the server, press Ctrl+C
echo.
echo ========================================
echo.

python run.py

pause
