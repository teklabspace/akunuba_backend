# 🚀 Quick Start Guide - Fix "Site Not Reached" Error

## ✅ The Server is Starting Successfully!

The app imports correctly and the server should be running. Follow these steps:

---

## 📋 Step-by-Step Instructions

### Step 1: Start the Server

**Option A: Double-click the batch file**
```
Double-click: start_server.bat
```

**Option B: Manual start (Command Prompt)**
1. Open **Command Prompt** (not PowerShell)
2. Type:
   ```cmd
   cd D:\Fiver\Fullego_Backend
   python run.py
   ```

**Option C: Manual start (PowerShell)**
1. Open **PowerShell**
2. Type:
   ```powershell
   cd D:\Fiver\Fullego_Backend
   python run.py
   ```

---

### Step 2: Wait for Server to Start

You should see output like:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**⚠️ IMPORTANT:** Keep this terminal window open! Closing it stops the server.

---

### Step 3: Open in Browser

**✅ CORRECT URLs to use:**
- `http://localhost:8000/`
- `http://127.0.0.1:8000/`
- `http://localhost:8000/health`
- `http://localhost:8000/docs`

**❌ WRONG URL (don't use this):**
- `http://0.0.0.0:8000/` ← This will NOT work in browsers!

---

## 🔍 Test if Server is Running

### Method 1: Check Port
Open a **new** terminal and run:
```cmd
netstat -ano | findstr :8000
```

If you see output, the server is running.

### Method 2: Test Health Endpoint
In your browser, go to:
```
http://localhost:8000/health
```

Should return: `{"status": "healthy", "version": "1.0.0"}`

---

## ❌ Common Issues & Solutions

### Issue 1: "Site Not Reached" or "Connection Refused"

**Cause:** Server is not running

**Solution:**
1. Make sure you started the server (Step 1)
2. Check the terminal window is still open
3. Look for error messages in the terminal

---

### Issue 2: Using Wrong URL

**Cause:** Trying to access `http://0.0.0.0:8000/`

**Solution:** Use `http://localhost:8000/` instead

---

### Issue 3: Port Already in Use

**Error:** `[Errno 10048] Only one usage of each socket address`

**Solution:**
1. Find the process:
   ```cmd
   netstat -ano | findstr :8000
   ```
2. Kill it:
   ```cmd
   taskkill /F /PID <PID_NUMBER>
   ```
3. Start server again

---

### Issue 4: Missing Environment Variables

**Error:** `Field required` or `ValidationError`

**Solution:**
1. Make sure `.env` file exists in `D:\Fiver\Fullego_Backend\`
2. Check `env.md` for required variables
3. Fill in all required values

---

## 🎯 Quick Test Checklist

- [ ] Server started with `python run.py`
- [ ] Terminal window shows "Uvicorn running on http://0.0.0.0:8000"
- [ ] Terminal window is still open (not closed)
- [ ] Using `http://localhost:8000/` (not `0.0.0.0`)
- [ ] Browser can access `http://localhost:8000/health`

---

## 📞 Still Not Working?

1. **Check the terminal output** - Look for red error messages
2. **Share the error** - Copy the full error message from the terminal
3. **Check Windows Firewall** - May be blocking port 8000
4. **Try a different port** - Edit `app/config.py` and change `PORT: int = 8001`

---

## ✅ Success Indicators

When everything is working, you should see:

1. **Terminal shows:**
   ```
   INFO:     Uvicorn running on http://0.0.0.0:8000
   INFO:     Application startup complete.
   ```

2. **Browser shows:**
   - `http://localhost:8000/` → `{"message": "Fullego Backend API", ...}`
   - `http://localhost:8000/health` → `{"status": "healthy", ...}`
   - `http://localhost:8000/docs` → Swagger UI documentation

---

**Remember:** Always use `localhost` or `127.0.0.1` in the browser, never `0.0.0.0`!
