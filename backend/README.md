# Backend README

## Overview
- Orchestrates Android automation using:
  - `main.py` (Python): talks to AWS Bedrock (Claude), decides actions, calls MCP tools.
  - `appium-mcp` (Node/TypeScript): HTTP server exposing Appium tools at `/tools/run`.
  - Appium Server: connects to your device/emulator.
- Generates step-by-step JSON reports under `backend/reports`.

## Architecture
- `backend/main.py`: main loop (LLM → tool call → result → new screen → repeat), pruning, retries, reporting.
- `backend/appium_tools.py`: Python wrappers for MCP HTTP tools (`/tools/run`).
- `backend/llm_tools.py`: tool schemas exposed to Claude.
- `backend/prompts.py`: system prompt and app package suggestions.
- `backend/reports.py`: `TestReport` JSON creation and updates.
- `backend/appium-mcp/src/httpServer.ts`: MCP HTTP server; routes `tool` + `args` → Appium actions; robust `click`, `send_keys`, `launch_app`.

## Prerequisites
- Windows + PowerShell
- Python 3.12 + virtualenv
- Node.js 18+
- Appium Server (`appium`)
- ADB in PATH (`adb devices` lists your device)
- AWS Bedrock access to Claude model

## Setup
### Python environment
```powershell
cd backend
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Node dependencies and build
```powershell
cd backend\appium-mcp
npm install
npm run build
```

## Configuration (environment)
Set before running `main.py`:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION` (default `us-east-1`)
- `BEDROCK_MODEL_ID` (default `anthropic.claude-3-5-sonnet-20240620-v1:0`)
- `AUTOMATION_PUBLIC_BASE_URL` (default `http://127.0.0.1:8000`, used for screenshot URLs)
- `MCP_SERVER_URL` (default `http://127.0.0.1:8080`)

Example (PowerShell):
```powershell
$env:AWS_ACCESS_KEY_ID="..."
$env:AWS_SECRET_ACCESS_KEY="..."
$env:AWS_REGION="us-east-1"
$env:BEDROCK_MODEL_ID="anthropic.claude-3-5-sonnet-20240620-v1:0"
$env:AUTOMATION_PUBLIC_BASE_URL="http://127.0.0.1:8000"
$env:MCP_SERVER_URL="http://127.0.0.1:8080"
```

## Run
1) Start Appium Server (Terminal 1):
```powershell
appium
```
2) Start MCP HTTP server (Terminal 2):
```powershell
cd backend\appium-mcp
npm run start:http
```
3) Start Automation API (Terminal 3):
```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
uvicorn api_server:app --reload
```
4) Run Python orchestrator (Terminal 4):
```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
python .\main.py
```

## How it works
- Gets screen XML → sends to Claude with tools → receives a tool call.
- Calls `/tools/run` with `{ "tool": "<name>", "args": { ... } }`.
- Sends result + new screen back to Claude.
- Repeats until done. Maintains history with pruning and validates `tool_use`/`tool_result` pairs.

## MCP HTTP server (key endpoints)
- `POST /tools/run` (unified): all tools
- `POST /tools/initialize-appium`: start driver session
- Health/utility endpoints printed on startup.

Example:
```bash
curl -X POST http://127.0.0.1:8080/tools/run \
 -H "Content-Type: application/json" \
 -d '{"tool":"click","args":{"strategy":"id","value":"com.app:id/btn"}}'
```

## Tooling highlights
- `click`: For long `content-desc`, auto-switches to XPath contains with safe escaping and waits for visibility.
- `send_keys`: Focuses element, clears, tries `setValue`, falls back to `addValue`, retries; clear error on failure.
- `launch_app`: Tries `startActivity` (if activity provided), otherwise ADB `monkey` with LAUNCHER, fallback plain `monkey`, then session `launchApp()`.
- Plus: scroll, scroll_to_element, swipe, long_press, get/clear text, orientation, keyboard, lock/unlock, battery, contexts, notifications, etc.

## Reporting
- JSON reports auto-saved under `backend/reports/` during and after runs.
- Include user prompt, each step (args, result, success/failure), totals, status.

## Resilience
- Bedrock calls: exponential backoff retries for transient `ServiceUnavailable`/`Throttling`.
- Message history: XML truncation + pruning that preserves pairs; validation removes orphaned `tool_result` blocks.

## Troubleshooting
- Click 500 on long content-desc: use shorter stable text or id; server now uses contains for long content-desc.
- `send_keys success: false`: ensure target is an input (`EditText`), visible, focused; prefer accurate `resource-id`.
- `launch_app` fails: check `adb devices`, package installed, device unlocked; errors indicate which fallback failed.
- Bedrock `ValidationException`: fixed by improved prune + validation; run latest `main.py`.
- After TS edits: rebuild MCP (`npm run build`) and restart.

## Typical flow (YouTube example)
- Goal: “Open YouTube and play first English song”
- Steps: `launch_app(com.google.android.youtube)` → type search → scroll → click first result.
- After each action, `get_page_source` to observe state.

## Notes
- Always rebuild MCP after edits:
```powershell
cd backend\appium-mcp
npm run build
npm run start:http
```
- Verify device via `adb devices`.
- Use correct package names (e.g., YouTube: `com.google.android.youtube`).


