# How to Start the Servers

## Issue: 404 Error on `/tools/run`

The Python backend (`main.py`) requires the MCP HTTP server to be running first. The 404 error occurs because the Node.js Express server isn't running on port 8080.

## Solution: Start Both Servers

### Step 1: Start the MCP HTTP Server (Node.js)

Open a **new terminal/PowerShell window** and run:

```powershell
cd backend\appium-mcp
npm run start:http
```

**Expected output:**
```
MCP Appium HTTP Server running on http://127.0.0.1:8080
Available endpoints:
  GET  /health
  POST /tools/run - Universal tool endpoint (all tools available here)
  ...
```

**Keep this terminal open** - the server must stay running.

### Step 2: Verify the Server is Running

In another terminal, test the health endpoint:

```powershell
curl http://127.0.0.1:8080/health
```

Or open in browser: http://127.0.0.1:8080/health

You should see: `{"status":"ok","message":"MCP Appium Server is running"}`

### Step 3: Start the Automation API (FastAPI)

In another terminal:

```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
uvicorn api_server:app --reload
```

### Step 4: Start the Python Automation Backend

With the virtual environment active:

```powershell
cd backend
python main.py
```

## Quick Start Script (Optional)

You can create a batch file to start both servers:

**`start-mcp-server.bat`** (Windows):
```batch
@echo off
cd backend\appium-mcp
echo Starting MCP HTTP Server...
npm run start:http
```

**`start-automation.bat`** (Windows):
```batch
@echo off
cd backend
echo Starting Python Automation Backend...
python main.py
```

## Troubleshooting

### Port 8080 Already in Use

If you get an error that port 8080 is already in use:

1. Find what's using it:
   ```powershell
   netstat -ano | findstr :8080
   ```

2. Kill the process or change the port:
   - Set environment variable: `$env:PORT="8081"`
   - Update `MCP_SERVER_URL` in Python: `$env:MCP_SERVER_URL="http://127.0.0.1:8081"`

### Server Not Starting

1. Make sure Node.js is installed: `node --version`
2. Install dependencies: `cd backend\appium-mcp && npm install`
3. Build the TypeScript: `npm run build`
4. Check for errors in the terminal output

### Still Getting 404

1. Verify the MCP server is actually running on port 8080
2. Check firewall isn't blocking localhost:8080
3. Try accessing http://localhost:8080/health in a browser
4. Check the MCP server terminal for any error messages

