# How to Restart Your Server

## 🚨 Important: Manual Restart Required

The server needs to be restarted manually to load the 2FA libraries.

---

## 📋 Step-by-Step Instructions

### Option 1: If Server is Running in a Terminal Window

1. **Find the terminal/command prompt where the server is running**
2. **Press `Ctrl+C`** to stop the server
3. **Wait 2-3 seconds** for it to fully stop
4. **Start it again**:
   ```bash
   python run.py
   ```
   Or:
   ```bash
   python -m uvicorn app.main:app --reload
   ```

### Option 2: Kill Process and Restart

#### Windows:
```cmd
REM 1. Find and kill the process
taskkill /F /PID 10564

REM 2. Wait a moment
timeout /t 2

REM 3. Start server
python run.py
```

#### Linux/Mac:
```bash
# 1. Find and kill the process
pkill -f "uvicorn app.main:app"
# or
kill 10564

# 2. Wait a moment
sleep 2

# 3. Start server
python run.py
```

### Option 3: Use the Restart Script

#### Windows:
```cmd
restart_server.bat
```

#### Linux/Mac:
```bash
chmod +x restart_server.sh
./restart_server.sh
```

---

## ✅ After Restart - Verify

### 1. Check Server Logs

After restarting, look for this message in the server console:
```
✅ 2FA libraries (pyotp, qrcode) are available
```

### 2. Test the Endpoint

Visit: `http://localhost:8000/docs`

Navigate to: `POST /api/v1/users/two-factor-auth/setup`

Click "Try it out" and test. It should return a QR code (not an error).

### 3. Check Health

Visit: `http://localhost:8000/health`

Should return: `{"status": "healthy", "version": "..."}`

---

## 🔍 Current Server Status

**Server is running on port 8000**

To restart:
1. Stop the current server (Ctrl+C in its terminal)
2. Start it again with: `python run.py`

---

## ⚠️ Important Notes

- **The server MUST be restarted** for 2FA libraries to be loaded
- Libraries are installed and verified ✅
- Code is updated ✅
- **Only restart is needed** ⚠️

---

## 🎯 Quick Restart Command

**Windows**:
```cmd
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *uvicorn*" 2>nul & timeout /t 2 >nul & python run.py
```

**Linux/Mac**:
```bash
pkill -f "uvicorn" && sleep 2 && python3 run.py
```

---

**After restart, 2FA will work!** 🚀
