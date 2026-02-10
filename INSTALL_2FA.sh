#!/bin/bash
# 2FA Installation Script for Linux/Mac

echo "========================================"
echo "2FA Dependencies Installation"
echo "========================================"
echo ""

echo "Installing pyotp and qrcode libraries..."
python3 -m pip install pyotp qrcode[pil]

if [ $? -ne 0 ]; then
    echo ""
    echo "[ERROR] Installation failed!"
    echo "Please check the error messages above."
    exit 1
fi

echo ""
echo "Verifying installation..."
python3 verify_2fa_installation.py

if [ $? -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "[SUCCESS] Installation complete!"
    echo "========================================"
    echo ""
    echo "IMPORTANT: Restart your FastAPI server for changes to take effect!"
    echo ""
    echo "To restart:"
    echo "  1. Stop the current server (Ctrl+C)"
    echo "  2. Start it again: uvicorn app.main:app --reload"
    echo ""
else
    echo ""
    echo "[ERROR] Verification failed!"
    echo "Please check the error messages above."
    exit 1
fi
