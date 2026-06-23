# Server Connection Troubleshooting Guide

## ❌ Common Error: "Connection Failed" or "ERR_ADDRESS_INVALID"

### Problem 1: Using Wrong URL
**❌ WRONG:** `http://0.0.0.0:8000/`  
**✅ CORRECT:** `http://localhost:8000/` or `http://127.0.0.1:8000/`

`0.0.0.0` is a bind address (tells the server to listen on all network interfaces), but browsers cannot connect to it directly.

---

## 🔍 Step-by-Step Troubleshooting

### Step 1: Check if Server is Running

Open a **new terminal/command prompt** and run:

```cmd
netstat -ano | findstr :8000
```

**If you see output** → Server is running, go to Step 2  
**If no output** → Server is NOT running, go to Step 3

---

### Step 2: Server is Running but Can't Connect

If the server is running but you still get connection errors:

1. **Try different URLs:**
   - `http://localhost:8000/`
   - `http://127.0.0.1:8000/`
   - `http://localhost:8000/health`
   - `http://localhost:8000/docs`

2. **Check Windows Firewall:**
   - Windows might be blocking port 8000
   - Try temporarily disabling firewall to test

3. **Check if another application is using port 8000:**
   ```cmd
   netstat -ano | findstr :8000
   ```
   Note the PID (last number), then check in Task Manager what that process is.

---

### Step 3: Start the Server Manually

**Open a terminal/command prompt** and navigate to the project:

```cmd
cd D:\Fiver\Fullego_Backend
```

**Then start the server:**

```cmd
python run.py
```

**OR:**

```cmd
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

### Step 4: Check for Startup Errors

When you start the server, you should see output like:

```
INFO:     Will watch for changes in these directories: ['D:\\Fiver\\Fullego_Backend']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using WatchFiles
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**If you see errors instead**, common issues:

#### Error: Missing Environment Variables
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
SUPABASE_URL
  Field required
```

**Solution:** Create a `.env` file in `D:\Fiver\Fullego_Backend\` with required variables. See `env.md` for template.

#### Error: Database Connection Failed
```
asyncpg.exceptions.InvalidPasswordError: password authentication failed
```

**Solution:** Check your `DATABASE_URL` in `.env` file.

#### Error: Port Already in Use
```
ERROR:    [Errno 10048] Only one usage of each socket address is normally permitted
```

**Solution:** 
1. Find and kill the process using port 8000:
   ```cmd
   netstat -ano | findstr :8000
   ```
   Note the PID, then:
   ```cmd
   taskkill /F /PID <PID_NUMBER>
   ```
2. Or change the port in `app/config.py` (set `PORT: int = 8001`)

---

### Step 5: Verify Server is Working

Once the server starts successfully, test these URLs in your browser:

1. **Health Check:**
   ```
   http://localhost:8000/health
   ```
   Should return: `{"status": "healthy", "version": "1.0.0"}`

2. **API Documentation:**
   ```
   http://localhost:8000/docs
   ```
   Should show Swagger UI

3. **Root Endpoint:**
   ```
   http://localhost:8000/
   ```
   Should return: `{"message": "Fullego Backend API", "version": "1.0.0", "status": "running"}`

---

## 🚀 Quick Start Commands

### Windows (Command Prompt):
```cmd
cd D:\Fiver\Fullego_Backend
python run.py
```

### Windows (PowerShell):
```powershell
cd D:\Fiver\Fullego_Backend
python run.py
```

### Using the Restart Script:
```cmd
cd D:\Fiver\Fullego_Backend
restart_server.bat
```

---

## ⚠️ Important Notes

1. **Keep the terminal window open** - Closing it will stop the server
2. **Use `Ctrl+C`** to stop the server gracefully
3. **The server must be running** before you can access it in the browser
4. **Always use `localhost` or `127.0.0.1`** in the browser, never `0.0.0.0`

---

## 🔧 Still Having Issues?

1. **Check Python is installed:**
   ```cmd
   python --version
   ```

2. **Check required packages:**
   ```cmd
   pip list | findstr fastapi
   pip list | findstr uvicorn
   ```

3. **Check for .env file:**
   ```cmd
   dir .env
   ```

4. **View full error logs** - Look at the terminal output when starting the server

---

## 📞 Common Error Messages

| Error | Solution |
|-------|----------|
| `ERR_ADDRESS_INVALID` | Use `localhost` instead of `0.0.0.0` |
| `Connection refused` | Server is not running - start it with `python run.py` |
| `Port already in use` | Kill the process using port 8000 or change port |
| `Field required` | Create `.env` file with required variables |
| `Database connection failed` | Check `DATABASE_URL` in `.env` |

---

**Last Updated:** 2024-01-01
