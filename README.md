# Appium Automation Suite

Full-stack workspace for running LLM-guided mobile automation and reviewing detailed execution telemetry. The backend (Python + FastAPI) talks to AWS Bedrock (Claude) and a local Appium MCP bridge, while the frontend (React + Vite + shadcn/ui) provides a dashboard for prompts, live device insights, and reports.

## Repository Layout
- `backend/` – Python orchestration layer plus the Appium MCP TypeScript server.
  - `main.py` – Bedrock orchestrator.
  - `api_server.py` – FastAPI service that exposes automation runs to the UI.
  - `appium-mcp/` – Node/TypeScript bridge that executes Appium commands over HTTP.
  - `reports/` – Generated JSON/PDF runs (ignored by git via `.gitignore`).
- `frontend/` – React/Vite dashboard sourced from `prompt-bot-suite-main/`.
- `frontend/requirements.txt` & `backend/requirements.txt` – Dependency manifests for both stacks.

## Prerequisites
- Python 3.12+
- Node.js 18+ and npm 10+ (or Bun 1.1+)  
- Appium server + ADB accessible on your machine
- AWS account with Bedrock access to Claude 3.5 Sonnet (or compatible model)

## Backend Setup
```powershell
cd backend
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Build and run the Appium MCP bridge (separate terminal):
```powershell
cd backend\appium-mcp
npm install
npm run build
npm run start:http   # serves MCP on http://127.0.0.1:8080
```

Start the FastAPI server for the dashboard:
```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
uvicorn api_server:app --reload --port 8000
```

Run the Claude/Appium orchestrator when you are ready to execute a prompt:
```powershell
cd backend
. .\.venv\Scripts\Activate.ps1
python main.py --prompt "Open YouTube and play the top result"
```

### Required Environment Variables
Set these before launching `main.py` or the API server:
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION`
- `BEDROCK_MODEL_ID` (default `anthropic.claude-3-5-sonnet-20240620-v1:0`)
- `MCP_SERVER_URL` (default `http://127.0.0.1:8080`)
- `AUTOMATION_PUBLIC_BASE_URL` (default `http://127.0.0.1:8000`, used for sharing report assets)

Keep secrets in a local `.env` (already ignored by git).

## Frontend Setup
```powershell
cd frontend\prompt-bot-suite-main
npm install
npm run dev        # http://localhost:5173
```

- Uses Vite, React 18, shadcn/ui, Tailwind CSS, and TanStack Query.
- Reads automation status and reports from the FastAPI backend (`http://127.0.0.1:8000` by default). Update the API base URL in `frontend/prompt-bot-suite-main/src/lib/api.ts` if you run the backend elsewhere.

## Working with Requirements
- Python dependencies live in `backend/requirements.txt`. Regenerate the virtual environment after updates.
- Frontend package list is mirrored in `frontend/requirements.txt`, but `package.json`/`package-lock.json` remain the source of truth for npm.

## Outputs
- JSON + PDF reports and screenshots are written under `backend/reports/` and `backend/appium-mcp/screenshots/`. These folders are ignored by git so you can safely generate artifacts locally without polluting commits.

## Git Hygiene
- `.env`, virtual environments, `node_modules`, build artifacts, and large generated reports are excluded via the root `.gitignore`.
- Keep backend and frontend dependencies in sync with their requirement files before pushing to GitHub.

## Helpful Commands
| Purpose | Command |
| --- | --- |
| Run API server | `uvicorn api_server:app --reload --port 8000` |
| Launch orchestrator | `python main.py --prompt "..."` |
| Tail reports directory | `Get-ChildItem backend\\reports` |
| Frontend dev server | `npm run dev -- --host` |
| Build frontend | `npm run build` |

## Troubleshooting
- **Cannot reach MCP server** – Ensure `npm run start:http` is active and `MCP_SERVER_URL` points to it.
- **Bedrock auth errors** – Double-check AWS credentials and region; the code fails fast if keys are missing.
- **Reports folder empty** – Orchestrator only writes reports after a full run; check `backend/reports/test_report_*.json/pdf`.
- **Frontend shows no runs** – API server must run on the URL baked into `src/lib/api.ts`; adjust if you deploy elsewhere.

You're ready to push the project to GitHub with clean dependency manifests and documentation users can follow end-to-end.

