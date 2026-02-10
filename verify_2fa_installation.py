#!/usr/bin/env python3
"""
2FA Installation Verification Script

This script verifies that all 2FA dependencies are properly installed
and can be imported correctly.
"""

import sys

def check_import(module_name, package_name=None):
    """Check if a module can be imported"""
    try:
        __import__(module_name)
        print(f"[OK] {package_name or module_name} is installed")
        return True
    except ImportError as e:
        print(f"[FAIL] {package_name or module_name} is NOT installed: {e}")
        return False

def main():
    print("=" * 60)
    print("2FA Installation Verification")
    print("=" * 60)
    print()
    
    all_ok = True
    
    # Check pyotp
    print("Checking pyotp...")
    pyotp_ok = check_import("pyotp", "pyotp")
    if pyotp_ok:
        try:
            import pyotp
            # Test basic functionality
            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            uri = totp.provisioning_uri("test@example.com", issuer_name="Test")
            print(f"   [OK] pyotp functionality test passed")
            print(f"   [OK] Generated secret: {secret[:10]}...")
        except Exception as e:
            print(f"   [WARN] pyotp test failed: {e}")
            all_ok = False
    else:
        all_ok = False
    
    print()
    
    # Check qrcode
    print("Checking qrcode...")
    qrcode_ok = check_import("qrcode", "qrcode[pil]")
    if qrcode_ok:
        try:
            import qrcode
            from PIL import Image
            # Test basic functionality
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data("test")
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            print(f"   [OK] qrcode functionality test passed")
            print(f"   [OK] QR code generation works")
        except Exception as e:
            print(f"   [WARN] qrcode test failed: {e}")
            all_ok = False
    else:
        all_ok = False
    
    print()
    
    # Check PIL/Pillow
    print("Checking Pillow (PIL)...")
    pillow_ok = check_import("PIL", "Pillow")
    if not pillow_ok:
        all_ok = False
    
    print()
    print("=" * 60)
    
    if all_ok:
        print("[SUCCESS] All 2FA dependencies are installed and working!")
        print()
        print("Next steps:")
        print("1. Restart your FastAPI server to load the libraries")
        print("2. Test 2FA setup endpoint: POST /api/v1/users/two-factor-auth/setup")
        return 0
    else:
        print("[ERROR] Some dependencies are missing!")
        print()
        print("Install missing dependencies:")
        print("  python -m pip install pyotp qrcode[pil]")
        print()
        print("Or install from requirements.txt:")
        print("  python -m pip install -r requirements.txt")
        return 1

if __name__ == "__main__":
    sys.exit(main())
