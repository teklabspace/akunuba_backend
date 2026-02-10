@echo off
REM 2FA Installation Script for Windows
echo ========================================
echo 2FA Dependencies Installation
echo ========================================
echo.

echo Installing pyotp and qrcode libraries...
python -m pip install pyotp qrcode[pil]

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Installation failed!
    echo Please check the error messages above.
    pause
    exit /b 1
)

echo.
echo Verifying installation...
python verify_2fa_installation.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo [SUCCESS] Installation complete!
    echo ========================================
    echo.
    echo IMPORTANT: Restart your FastAPI server for changes to take effect!
    echo.
    echo To restart:
    echo   1. Stop the current server (Ctrl+C)
    echo   2. Start it again: uvicorn app.main:app --reload
    echo.
) else (
    echo.
    echo [ERROR] Verification failed!
    echo Please check the error messages above.
)

pause
