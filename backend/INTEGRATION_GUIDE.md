# Frontend-Backend Integration Guide

## ✅ Connection Status

The frontend and backend are **fully connected** and ready to work together. Here's how everything is wired:

### Architecture Overview

```
Frontend (React/Vite)          Backend (FastAPI)
Port: 5173                     Port: 8000
     │                              │
     ├─ POST /api/runs ────────────► Create automation run
     ├─ GET /api/runs/{id}/events ─► SSE stream (real-time logs)
     ├─ GET /api/runs/{id} ────────► Get run status
     └─ GET /reports/{file} ───────► Download reports/screenshots
```

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/runs` | POST | Create new automation run |
| `/api/runs` | GET | List all runs |
| `/api/runs/{id}` | GET | Get run details |
| `/api/runs/{id}/events` | GET | SSE stream for real-time events (logs, screenshots, device status) |
| `/api/runs/{id}/logs` | GET | Get run logs |
| `/api/runs/{id}/screenshots` | GET | Get run screenshots |
| `/api/runs/{id}/report` | GET | Get run report |
| `/reports/{filename}` | GET | Static file serving for reports/screenshots |

### Event Types Streamed

The SSE stream (`/api/runs/{id}/events`) emits these event types:

1. **Status Events**: `{"type": "status", "status": "pending|running|completed|failed"}`
2. **Log Events**: `{"type": "log", "level": "info|success|error|action", "message": "...", "id": "..."}`
3. **Screenshot Events**: `{"type": "screenshot", "screenshot": {"id": "...", "url": "...", "timestamp": "...", "step": "..."}}`
4. **Device Events**: `{"type": "device", "deviceType": "android|ios"}`
5. **Report Events**: `{"type": "report", "report": {...}}`

## 🚀 Startup Sequence

### Step 1: Start Appium Server
```powershell
appium
```
**Expected**: Server running on `http://127.0.0.1:4723`

### Step 2: Start MCP HTTP Server
```powershell
cd backend\appium-mcp
npm run start:http
```
**Expected**: Server running on `http://0.0.0.0:8080`

### Step 3: Start FastAPI Backend
```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
# Set AWS credentials
$env:AWS_ACCESS_KEY_ID="your-key"
$env:AWS_SECRET_ACCESS_KEY="your-secret"
$env:AWS_REGION="us-east-1"
# Start server
uvicorn api_server:app --reload --host 127.0.0.1 --port 8000
```
**Expected**: API server running on `http://127.0.0.1:8000`

### Step 4: Start Frontend
```powershell
cd frontend\prompt-bot-suite-main
npm install  # if not already done
npm run dev
```
**Expected**: Frontend running on `http://localhost:5173`

## 🔍 Verification Steps

### 1. Check Backend Health
Open browser: `http://127.0.0.1:8000/health`
**Expected**: `{"status": "ok"}`

### 2. Check Frontend Connection
Open browser DevTools → Network tab → Submit a prompt
**Expected**: 
- POST request to `http://127.0.0.1:8000/api/runs` returns 201
- GET request to `http://127.0.0.1:8000/api/runs/{id}/events` opens SSE connection

### 3. Check Real-Time Events
In the frontend Live Console, you should see:
- "Spawning automation runner" (info log)
- Real-time logs from `main.py` execution
- Screenshots appearing as they're captured
- Final report when automation completes

## 🐛 Troubleshooting

### Frontend can't connect to backend

**Symptom**: Network errors in browser console, "Failed to start automation"

**Solutions**:
1. Verify FastAPI server is running: `curl http://127.0.0.1:8000/health`
2. Check CORS: Backend has `allow_origins=["*"]` - should work
3. Check firewall: Ensure port 8000 is not blocked
4. Verify API URL: Frontend defaults to `http://127.0.0.1:8000`

### SSE events not streaming

**Symptom**: Automation starts but no logs appear in Live Console

**Solutions**:
1. Check browser DevTools → Network → Events tab
2. Verify SSE connection is open (should show "EventStream" type)
3. Check backend logs for errors
4. Verify `automation_manager.event_stream()` is working

### Automation fails immediately

**Symptom**: "Unexpected automation failure" error appears

**Solutions**:
1. Check Live Console for detailed error message (now includes traceback)
2. Verify AWS credentials are set in the environment where FastAPI runs
3. Verify MCP server is running on port 8080
4. Verify Appium server is running on port 4723
5. Check that Python dependencies are installed: `pip install -r requirements.txt`

### Screenshots not appearing

**Symptom**: Automation completes but no screenshots in gallery

**Solutions**:
1. Verify reports are being generated in `backend/reports/`
2. Check screenshot paths in report JSON files
3. Verify `/reports` static file mount is working: `http://127.0.0.1:8000/reports/`
4. Check `AUTOMATION_PUBLIC_BASE_URL` environment variable if using custom domain

## 📝 Environment Variables

### Backend (FastAPI)
- `AWS_ACCESS_KEY_ID` - Required for Bedrock
- `AWS_SECRET_ACCESS_KEY` - Required for Bedrock
- `AWS_REGION` - Default: `us-east-1`
- `MCP_SERVER_URL` - Default: `http://127.0.0.1:8080`
- `AUTOMATION_PUBLIC_BASE_URL` - Default: `http://127.0.0.1:8000` (for screenshot URLs)

### Frontend (Vite)
- `VITE_AUTOMATION_API_URL` - Default: `http://127.0.0.1:8000`

## ✅ Connection Checklist

Before running automation, verify:

- [ ] Appium server running on port 4723
- [ ] MCP HTTP server running on port 8080
- [ ] FastAPI backend running on port 8000 (streams **live screenshots** to the UI)
- [ ] Frontend dev server running on port 5173
- [ ] AWS credentials set in FastAPI environment
- [ ] Android device/emulator connected (`adb devices`)
- [ ] Health check passes: `http://127.0.0.1:8000/health`

## 🎯 Expected Flow

1. **User submits prompt** → Frontend calls `POST /api/runs`
2. **Backend creates run** → Returns run ID, starts automation in background
3. **Frontend opens SSE** → Connects to `/api/runs/{id}/events`
4. **Automation executes** → `main.py` runs, emits events via `AutomationRunner`
5. **Events stream** → Logs, screenshots, status updates appear in real-time
6. **Automation completes** → Final report emitted, SSE connection closes
7. **Frontend updates** → Report appears in Reports Panel, screenshots in gallery

## 🔗 Key Files

- **Frontend API Client**: `frontend/prompt-bot-suite-main/src/lib/api.ts`
- **Frontend Dashboard**: `frontend/prompt-bot-suite-main/src/pages/Dashboard.tsx`
- **Backend API Server**: `backend/api_server.py`
- **Automation Manager**: `backend/automation_manager.py`
- **Automation Runner**: `backend/automation_runner.py`
- **Main Orchestrator**: `backend/main.py`

