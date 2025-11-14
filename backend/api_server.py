from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from automation_manager import AutomationRun, automation_manager


class RunCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)


class LogEntry(BaseModel):
    id: str
    level: str
    message: str
    timestamp: datetime
    details: Optional[str] = None


class ScreenshotEntry(BaseModel):
    id: str
    url: str
    timestamp: datetime
    step: Optional[str] = None


class ReportEntry(BaseModel):
    id: str
    name: str
    path: Optional[str] = None
    pdfPath: Optional[str] = None
    status: Optional[str] = None
    prompt: Optional[str] = None
    createdAt: Optional[datetime] = None


class RunResponse(BaseModel):
    id: str
    prompt: str
    status: str
    createdAt: datetime
    updatedAt: datetime
    deviceType: Optional[str] = None
    reportPath: Optional[str] = None
    logs: List[Dict[str, Any]] = Field(default_factory=list)
    screenshots: List[Dict[str, Any]] = Field(default_factory=list)


def _serialize_run(run: AutomationRun) -> Dict[str, Any]:
    payload = run.to_dict()
    payload["createdAt"] = payload.pop("created_at")
    payload["updatedAt"] = payload.pop("updated_at")
    payload["deviceType"] = payload.pop("device_type")
    payload["reportPath"] = payload.pop("report_path")
    payload["logs"] = run.logs
    payload["screenshots"] = run.screenshots
    payload.pop("events", None)
    return payload


app = FastAPI(
    title="Automation Control API",
    version="0.1.0",
    description="API surface for orchestrating MCP/Appium automation runs.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_reports_path = Path(__file__).resolve().parent / "reports"
_reports_path.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(_reports_path)), name="reports")


@app.get("/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/runs", response_model=List[RunResponse])
def list_runs() -> List[Dict[str, Any]]:
    return [_serialize_run(run) for run in automation_manager.list_runs()]


@app.get("/api/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> Dict[str, Any]:
    if not automation_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run = automation_manager.get_run(run_id)
    return _serialize_run(run)


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> Dict[str, str]:
    """Cancel a running automation run."""
    try:
        if not automation_manager.has_run(run_id):
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        await automation_manager.cancel_run(run_id)
        return {"status": "cancelled", "message": f"Run {run_id} has been cancelled"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel run: {str(e)}")


@app.post("/api/runs", response_model=RunResponse, status_code=201)
async def create_run(payload: RunCreateRequest) -> Dict[str, Any]:
    run = await automation_manager.create_run(payload.prompt)
    return _serialize_run(run)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> EventSourceResponse:
    if not automation_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in automation_manager.event_stream(run_id):
            yield {"event": event.get("type", "message"), "data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@app.get("/api/runs/{run_id}/screenshots", response_model=List[ScreenshotEntry])
def list_run_screenshots(run_id: str) -> List[Dict[str, Any]]:
    if not automation_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return automation_manager.get_run(run_id).screenshots


@app.get("/api/runs/{run_id}/logs", response_model=List[LogEntry])
def list_run_logs(run_id: str) -> List[Dict[str, Any]]:
    if not automation_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return automation_manager.get_run(run_id).logs


@app.get("/api/runs/{run_id}/report", response_model=Optional[ReportEntry])
def get_run_report(run_id: str) -> Optional[Dict[str, Any]]:
    if not automation_manager.has_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    run = automation_manager.get_run(run_id)
    if not run.report_path:
        return None
    reports = [
        event.get("report")
        for event in run.events
        if event.get("type") == "report" and event.get("report")
    ]
    return reports[-1] if reports else None


@app.get("/api/device/info")
def get_device_info() -> Dict[str, Any]:
    """Get connected device information."""
    try:
        import requests
        import subprocess
        
        MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://127.0.0.1:8080')
        
        # Try to detect iOS devices first (macOS only)
        ios_devices = []
        try:
            idevice_result = subprocess.run(
                ["idevice_id", "-l"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if idevice_result.returncode == 0 and idevice_result.stdout.strip():
                device_ids = idevice_result.stdout.strip().split('\n')
                for device_id in device_ids:
                    if device_id.strip():
                        device_id = device_id.strip()
                        device_name = None
                        is_tablet = False
                        try:
                            name_result = subprocess.run(
                                ["ideviceinfo", "-u", device_id, "-k", "DeviceName"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            if name_result.returncode == 0:
                                device_name = name_result.stdout.strip()
                            
                            # Check if iPad
                            model_result = subprocess.run(
                                ["ideviceinfo", "-u", device_id, "-k", "ProductType"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            if model_result.returncode == 0:
                                product_type = model_result.stdout.strip()
                                is_tablet = "iPad" in product_type or "ipad" in product_type.lower()
                        except:
                            pass
                        
                        ios_devices.append({
                            "id": device_id,
                            "name": device_name or device_id,
                            "isTablet": is_tablet
                        })
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # idevice_id not available
            pass
        except Exception:
            pass
        
        # Try to get Android devices via ADB
        android_devices = []
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                devices = []
                for line in lines:
                    if line.strip() and '\tdevice' in line:
                        device_id = line.split('\t')[0].strip()
                        if device_id:
                            # Get device model/name
                            device_name = None
                            try:
                                name_result = subprocess.run(
                                    ["adb", "-s", device_id, "shell", "getprop", "ro.product.model"],
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                if name_result.returncode == 0:
                                    device_name = name_result.stdout.strip()
                            except:
                                pass
                            
                            # Get device brand
                            device_brand = None
                            try:
                                brand_result = subprocess.run(
                                    ["adb", "-s", device_id, "shell", "getprop", "ro.product.brand"],
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                if brand_result.returncode == 0:
                                    device_brand = brand_result.stdout.strip()
                            except:
                                pass
                            
                            # Get screen size to determine form factor
                            screen_size = None
                            is_tablet = False
                            try:
                                # Get screen density and size
                                density_result = subprocess.run(
                                    ["adb", "-s", device_id, "shell", "wm", "size"],
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                if density_result.returncode == 0:
                                    size_output = density_result.stdout.strip()
                                    # Parse screen size (e.g., "Physical size: 1080x2340")
                                    if "Physical size:" in size_output:
                                        size_part = size_output.split("Physical size:")[-1].strip()
                                        if "x" in size_part:
                                            try:
                                                # Extract dimensions (e.g., "1080x2340" or "1080 x 2340")
                                                dims = size_part.split("x")
                                                if len(dims) == 2:
                                                    width = int(dims[0].strip())
                                                    height = int(dims[1].strip().split()[0] if " " in dims[1] else dims[1].strip())
                                                    short_side = min(width, height)
                                                    long_side = max(width, height)
                                                    aspect_ratio = (long_side / short_side) if short_side else 0
                                                    # Consider device a tablet if the short side is large (>= 1200)
                                                    # or the aspect ratio indicates a more square/tablet display (<= 1.6)
                                                    if short_side >= 1200 or aspect_ratio <= 1.6:
                                                        is_tablet = True
                                            except (ValueError, IndexError):
                                                pass
                            except:
                                pass
                            
                            full_name = f"{device_brand} {device_name}".strip() if device_brand and device_name else (device_name or device_id)
                            android_devices.append({
                                "id": device_id,
                                "name": full_name,
                                "model": device_name,
                                "brand": device_brand,
                                "isTablet": is_tablet
                            })
        except Exception as adb_error:
            pass
        
        # Combine iOS and Android devices
        all_devices = ios_devices + android_devices
        
        if all_devices:
            return {
                "connected": True,
                "deviceId": all_devices[0]["id"],
                "deviceName": all_devices[0]["name"],
                "deviceCount": len(all_devices),
                "devices": all_devices
            }
        
        # Fallback: check MCP server
        try:
            response = requests.get(f"{MCP_SERVER_URL}/health", timeout=2)
            if response.status_code == 200:
                return {
                    "connected": False,
                    "deviceId": None,
                    "deviceName": "No device connected",
                    "deviceCount": 0,
                    "devices": [],
                    "message": "No Android device detected. Please connect a device via USB and enable USB debugging."
                }
        except:
            pass
        
        return {
            "connected": False,
            "deviceId": None,
            "deviceName": "Unknown",
            "deviceCount": 0,
            "devices": [],
            "message": "Unable to check device status. Make sure ADB is installed and MCP server is running."
        }
    except Exception as e:
        return {
            "connected": False,
            "deviceId": None,
            "deviceName": "Error",
            "deviceCount": 0,
            "devices": [],
            "error": str(e),
            "message": f"Error checking device: {str(e)}"
        }


def create_app() -> FastAPI:
    return app


__all__ = ["app", "create_app"]

