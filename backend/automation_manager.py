from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, DefaultDict, Dict, List, Literal, Optional

import appium_tools
from automation_runner import (
    AutomationRunner,
    AutomationRunnerError,
    REPORTS_DIR,
    REPORTS_PUBLIC_URL,
)

RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
DeviceType = Literal["android", "ios"]
APP_MCP_DIR = (Path(__file__).resolve().parent / "appium-mcp").resolve()
# Fast polling for device screen viewer (real-time updates)
# Separate from screenshot gallery - this is just for live screen viewing
DEVICE_SCREEN_POLL_INTERVAL = float(os.getenv("AUTOMATION_DEVICE_SCREEN_INTERVAL", "0.5"))
# Screenshot gallery polling (disabled - screenshots only after meaningful steps)
SCREENSHOT_POLL_INTERVAL = float(os.getenv("AUTOMATION_SCREENSHOT_INTERVAL", "0"))


def _utc_now() -> datetime:
    return datetime.utcnow()


def _iso_now() -> str:
    return _utc_now().isoformat() + "Z"


@dataclass
class AutomationRun:
    id: str
    prompt: str
    status: RunStatus = "pending"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    device_type: Optional[DeviceType] = None
    report_path: Optional[str] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)
    screenshots: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat() + "Z"
        payload["updated_at"] = self.updated_at.isoformat() + "Z"
        return payload


class AutomationManager:
    """Coordinates automation runs and streams events to subscribers."""

    def __init__(self) -> None:
        self._runs: Dict[str, AutomationRun] = {}
        self._subscribers: DefaultDict[str, List[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._runner = AutomationRunner()
        self._screenshot_pollers: Dict[str, asyncio.Task] = {}

    def has_run(self, run_id: str) -> bool:
        return run_id in self._runs

    async def create_run(self, prompt: str) -> AutomationRun:
        async with self._lock:
            run_id = uuid.uuid4().hex
            run = AutomationRun(id=run_id, prompt=prompt)
            self._runs[run_id] = run
            self._emit_event(run_id, {"type": "status", "status": "pending"})

        asyncio.create_task(self._run_automation(run_id, prompt))
        return run

    def get_run(self, run_id: str) -> AutomationRun:
        if run_id not in self._runs:
            raise KeyError(f"Run {run_id} not found")
        return self._runs[run_id]

    def list_runs(self) -> List[AutomationRun]:
        return sorted(self._runs.values(), key=lambda run: run.created_at, reverse=True)

    async def cancel_run(self, run_id: str) -> None:
        """Cancel a running automation run."""
        if run_id not in self._runs:
            raise KeyError(f"Run {run_id} not found")
        
        run = self._runs[run_id]
        if run.status not in {"pending", "running"}:
            return  # Already completed/failed/cancelled
        
        # Cancel screenshot poller if exists
        if run_id in self._screenshot_pollers:
            poller_task = self._screenshot_pollers[run_id]
            poller_task.cancel()
            del self._screenshot_pollers[run_id]
        
        # Cancel the automation runner task
        # The runner will check run.status and exit gracefully
        run.status = "cancelled"
        self._emit_event(run_id, {"type": "status", "status": "cancelled"})
        
        # Cancel the automation task if it exists
        # Note: The actual subprocess cancellation is handled by the runner

    async def event_stream(self, run_id: str) -> AsyncIterator[Dict[str, Any]]:
        if run_id not in self._runs:
            raise KeyError(f"Run {run_id} not found")

        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[run_id].append(queue)

        run = self._runs[run_id]
        try:
            for event in run.events:
                yield event

            while True:
                event = await queue.get()
                yield event
                if (
                    event["type"] == "status"
                    and event.get("status") in {"completed", "failed", "cancelled"}
                ):
                    break
        finally:
            subscribers = self._subscribers.get(run_id)
            if subscribers and queue in subscribers:
                subscribers.remove(queue)

    def _emit_event(self, run_id: str, event: Dict[str, Any]) -> None:
        if run_id not in self._runs:
            return

        run = self._runs[run_id]
        timestamp = event.get("timestamp") or _iso_now()
        payload = {**event, "runId": run_id, "timestamp": timestamp}
        run.events.append(payload)
        run.updated_at = _utc_now()

        event_type = payload.get("type")
        if event_type == "status":
            run.status = payload.get("status", run.status)
        elif event_type == "log":
            run.logs.append(payload)
        elif event_type == "screenshot":
            screenshot = payload.get("screenshot")
            if isinstance(screenshot, dict):
                run.screenshots.append(screenshot)
        elif event_type == "device":
            device_type = payload.get("deviceType")
            if device_type in {"android", "ios"}:
                run.device_type = device_type  # type: ignore[assignment]
        elif event_type == "report":
            report_path = payload.get("report", {}).get("path")
            if report_path:
                run.report_path = report_path

        for queue in self._subscribers.get(run_id, []):
            queue.put_nowait(payload)

    async def _run_automation(self, run_id: str, prompt: str) -> None:
        self._emit_event(run_id, {"type": "status", "status": "running"})
        
        # Fetch and emit full device information at the start of automation
        try:
            import subprocess
            import requests
            import os
            
            MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://127.0.0.1:8080')
            device_info = {"deviceType": "android", "deviceName": None, "isTablet": False}
            
            # Try to detect iOS devices first (macOS only)
            ios_device_detected = False
            try:
                # Check for iOS devices using idevice_id (requires libimobiledevice)
                idevice_result = subprocess.run(
                    ["idevice_id", "-l"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if idevice_result.returncode == 0 and idevice_result.stdout.strip():
                    device_ids = idevice_result.stdout.strip().split('\n')
                    if device_ids and device_ids[0]:
                        device_id = device_ids[0].strip()
                        # Get device name using ideviceinfo
                        try:
                            name_result = subprocess.run(
                                ["ideviceinfo", "-u", device_id, "-k", "DeviceName"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            device_name = name_result.stdout.strip() if name_result.returncode == 0 else None
                            
                            # Get device model to determine if it's iPad
                            try:
                                model_result = subprocess.run(
                                    ["ideviceinfo", "-u", device_id, "-k", "ProductType"],
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                product_type = model_result.stdout.strip() if model_result.returncode == 0 else ""
                                is_tablet = "iPad" in product_type or "ipad" in product_type.lower()
                            except:
                                is_tablet = False
                            
                            device_info = {
                                "deviceType": "ios",
                                "deviceName": device_name or device_id,
                                "isTablet": is_tablet
                            }
                            ios_device_detected = True
                        except:
                            device_info = {
                                "deviceType": "ios",
                                "deviceName": device_id,
                                "isTablet": False
                            }
                            ios_device_detected = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # idevice_id not available (not macOS or libimobiledevice not installed)
                pass
            except Exception:
                pass
            
            # If no iOS device found, try Android devices via ADB
            if not ios_device_detected:
                try:
                    result = subprocess.run(
                        ["adb", "devices"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')[1:]  # Skip header
                        for line in lines:
                            if line.strip() and '\tdevice' in line:
                                device_id = line.split('\t')[0].strip()
                                if not device_id:
                                    continue

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
                                except Exception:
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
                                except Exception:
                                    pass

                                # Get screen size to determine form factor
                                is_tablet = False
                                try:
                                    density_result = subprocess.run(
                                        ["adb", "-s", device_id, "shell", "wm", "size"],
                                        capture_output=True,
                                        text=True,
                                        timeout=2
                                    )
                                    if density_result.returncode == 0:
                                        size_output = density_result.stdout.strip()
                                        if "Physical size:" in size_output and "x" in size_output:
                                            try:
                                                size_part = size_output.split("Physical size:")[-1].strip()
                                                dims = size_part.split("x")
                                                if len(dims) == 2:
                                                    width = int(dims[0].strip())
                                                    height = int(dims[1].strip().split()[0] if " " in dims[1] else dims[1].strip())
                                                    short_side = min(width, height)
                                                    long_side = max(width, height)
                                                    aspect_ratio = (long_side / short_side) if short_side else 0
                                                    # Consider device a tablet if the short side is large (>= 1200)
                                                    # or the aspect ratio is closer to tablet ratios (<= 1.6)
                                                    if short_side >= 1200 or aspect_ratio <= 1.6:
                                                        is_tablet = True
                                            except (ValueError, IndexError):
                                                pass
                                except Exception:
                                    pass

                                full_name = f"{device_brand} {device_name}".strip() if device_brand and device_name else (device_name or device_id)
                                device_info = {
                                    "deviceType": "android",
                                    "deviceName": full_name,
                                    "isTablet": is_tablet
                                }
                                break
                except Exception:
                    pass
            
            # Emit device info event with full details
            self._emit_event(run_id, {
                "type": "device",
                "deviceType": device_info["deviceType"],
                "deviceName": device_info["deviceName"],
                "isTablet": device_info["isTablet"]
            })
        except Exception:
            # Fallback to default if device info fetch fails
            self._emit_event(run_id, {"type": "device", "deviceType": "android"})

        def forward(event: Dict[str, Any]) -> None:
            self._emit_event(run_id, event)

        poller_task: Optional[asyncio.Task] = None
        # Start fast polling for device screen viewer (real-time updates)
        if DEVICE_SCREEN_POLL_INTERVAL > 0:
            poller_task = asyncio.create_task(self._poll_live_screenshots(run_id, DEVICE_SCREEN_POLL_INTERVAL))
            self._screenshot_pollers[run_id] = poller_task

        try:
            # Check if run was cancelled before starting
            run = self._runs.get(run_id)
            if run and run.status == "cancelled":
                return
            
            await self._runner.run(prompt, forward)
            
            # Check again after run completes
            run = self._runs.get(run_id)
            if run and run.status == "cancelled":
                return
            self._emit_event(
                run_id,
                {
                    "type": "log",
                    "id": uuid.uuid4().hex,
                    "level": "success",
                    "message": "Automation completed successfully",
                },
            )
            self._emit_event(run_id, {"type": "status", "status": "completed"})
        except AutomationRunnerError as exc:
            self._emit_event(
                run_id,
                {
                    "type": "log",
                    "id": uuid.uuid4().hex,
                    "level": "error",
                    "message": "Automation runner reported an error",
                    "details": str(exc),
                },
            )
            self._emit_event(run_id, {"type": "status", "status": "failed"})
        except Exception as exc:  # pragma: no cover - defensive
            import traceback
            error_details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            self._emit_event(
                run_id,
                {
                    "type": "log",
                    "level": "error",
                    "message": f"Unexpected automation failure: {type(exc).__name__}",
                    "details": f"{str(exc)}\n\nTraceback:\n{error_details}",
                },
            )
            self._emit_event(run_id, {"type": "status", "status": "failed"})
        finally:
            poller = self._screenshot_pollers.pop(run_id, None)
            if poller:
                poller.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller

    async def _poll_live_screenshots(self, run_id: str, interval: float) -> None:
        """Poll for live device screen updates for real-time viewing."""
        interval = max(interval, 0.0)
        if interval <= 0:
            return

        await asyncio.sleep(0.2)  # Reduced initial delay for faster first update

        while True:
            run = self._runs.get(run_id)
            if not run or run.status in {"completed", "failed", "cancelled"}:
                break

            try:
                # Use ADB directly for faster screenshot capture (bypasses MCP server overhead)
                import subprocess
                device_id = None
                try:
                    # Get the first connected device
                    result = subprocess.run(
                        ["adb", "devices"],
                        capture_output=True,
                        text=True,
                        timeout=1
                    )
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')[1:]
                        for line in lines:
                            if line.strip() and '\tdevice' in line:
                                device_id = line.split('\t')[0].strip()
                                break
                except Exception:
                    pass
                
                if device_id:
                    # Use ADB screencap directly for faster capture
                    try:
                        # Capture screenshot to device (non-blocking)
                        subprocess.run(
                            ["adb", "-s", device_id, "shell", "screencap", "-p", "/sdcard/live_screen.png"],
                            capture_output=True,
                            timeout=1.5
                        )
                        # Pull screenshot to local temp file
                        temp_path = REPORTS_DIR / f"{run_id}_device_screen_temp.png"
                        temp_path.parent.mkdir(parents=True, exist_ok=True)
                        pull_result = subprocess.run(
                            ["adb", "-s", device_id, "pull", "/sdcard/live_screen.png", str(temp_path)],
                            capture_output=True,
                            timeout=1.5
                        )
                        if pull_result.returncode == 0 and temp_path.exists():
                            # Move to final location
                            dest_name = f"{run_id}_device_screen.png"
                            dest_path = (REPORTS_DIR / dest_name).resolve()
                            shutil.move(str(temp_path), str(dest_path))
                            
                            # Emit immediately with timestamp for cache busting
                            self._emit_event(
                                run_id,
                                {
                                    "type": "screenshot",
                                    "screenshot": {
                                        "id": f"{dest_path.stem}",
                                        "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}?t={int(time.time() * 1000)}",
                                        "timestamp": _iso_now(),
                                        "step": "Live Screen"
                                    }
                                }
                            )
                    except Exception:
                        # Fallback to MCP server method if ADB direct fails
                        try:
                            response = appium_tools.take_screenshot()
                            if isinstance(response, dict) and response.get("success"):
                                raw_path = response.get("screenshotPath") or response.get("path")
                                if raw_path:
                                    source_path = Path(raw_path)
                                    if not source_path.is_absolute():
                                        source_path = (APP_MCP_DIR / source_path).resolve()
                                    if source_path.exists():
                                        dest_name = f"{run_id}_device_screen.png"
                                        dest_path = (REPORTS_DIR / dest_name).resolve()
                                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copyfile(source_path, dest_path)
                                        self._emit_event(
                                            run_id,
                                            {
                                                "type": "screenshot",
                                                "screenshot": {
                                                    "id": f"{dest_path.stem}",
                                                    "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}?t={int(time.time() * 1000)}",
                                                    "timestamp": _iso_now(),
                                                    "step": "Live Screen"
                                                }
                                            }
                                        )
                        except Exception:
                            pass
                else:
                    # Fallback to MCP server method if no device found
                    try:
                        response = appium_tools.take_screenshot()
                        if isinstance(response, dict) and response.get("success"):
                            raw_path = response.get("screenshotPath") or response.get("path")
                            if raw_path:
                                source_path = Path(raw_path)
                                if not source_path.is_absolute():
                                    source_path = (APP_MCP_DIR / source_path).resolve()
                                if source_path.exists():
                                    dest_name = f"{run_id}_device_screen.png"
                                    dest_path = (REPORTS_DIR / dest_name).resolve()
                                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(source_path, dest_path)
                                    self._emit_event(
                                        run_id,
                                        {
                                            "type": "screenshot",
                                            "screenshot": {
                                                "id": f"{dest_path.stem}",
                                                "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}?t={int(time.time() * 1000)}",
                                                "timestamp": _iso_now(),
                                                "step": "Live Screen"
                                            }
                                        }
                                    )
                    except Exception:
                        pass
            except Exception:
                pass

            await asyncio.sleep(interval)


automation_manager = AutomationManager()

