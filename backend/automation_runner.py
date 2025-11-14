from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

AutomationEventCallback = Callable[[Dict[str, Any]], None]

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
APP_MCP_DIR = (BASE_DIR / "appium-mcp").resolve()
AUTOMATION_PUBLIC_BASE_URL = os.getenv(
    "AUTOMATION_PUBLIC_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")
REPORTS_PUBLIC_URL = f"{AUTOMATION_PUBLIC_BASE_URL}/reports"


class AutomationRunnerError(Exception):
    """Raised when the automation runner fails."""


class AutomationRunner:
    """Runs the existing main.py orchestrator in a subprocess and streams events."""

    def __init__(self, reports_dir: Path = REPORTS_DIR) -> None:
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        prompt: str,
        emit: AutomationEventCallback,
    ) -> None:
        """
        Execute the automation workflow for the provided prompt.

        Args:
            prompt: Natural language goal to execute.
            emit: Callback invoked with automation events (log/screenshot/report/status).
        """
        existing_reports = set(self._iter_report_files())
        started_at = time.time()

        emit(
            {
                "type": "log",
                "id": uuid.uuid4().hex,
                "level": "info",
                "message": "Spawning automation runner",
                "details": json.dumps({"prompt": prompt}, indent=2),
            }
        )

        # Ensure environment variables are passed through
        env = os.environ.copy()
        
        # On Windows, we need to use ProactorEventLoop for subprocess support
        # or use a thread-based approach. Let's use a thread executor for cross-platform compatibility.
        if platform.system() == "Windows":
            # Use thread executor for Windows compatibility
            import subprocess
            from concurrent.futures import ThreadPoolExecutor
            
            # Ensure UTF-8 encoding for subprocess on Windows
            env['PYTHONIOENCODING'] = 'utf-8'
            # Ensure unbuffered output for real-time logs
            env['PYTHONUNBUFFERED'] = '1'
            
            def run_subprocess():
                process = subprocess.Popen(
                    [sys.executable, str(BASE_DIR / "main.py"), "--prompt", prompt],
                    cwd=str(BASE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=False,  # Use bytes mode
                    bufsize=0,  # Unbuffered for real-time output
                )
                return process
            
            # Run subprocess creation in thread pool
            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=3)
            process = await loop.run_in_executor(executor, run_subprocess)
            
            stderr_lines = []
            message_queue = asyncio.Queue()
            
            def read_pipe(pipe, level: str):
                """Read from pipe in thread and put messages in queue."""
                try:
                    for line in iter(pipe.readline, b''):
                        if not line:
                            break
                        try:
                            message = line.decode("utf-8", errors="replace").rstrip()
                        except Exception:
                            message = line.decode("latin-1", errors="replace").rstrip()
                        if message:
                            # Put message in queue for async processing
                            asyncio.run_coroutine_threadsafe(
                                message_queue.put((level, message)), loop
                            )
                except Exception as e:
                    asyncio.run_coroutine_threadsafe(
                        message_queue.put(("error", f"Error reading {level}: {str(e)}")), loop
                    )
            
            # Start reading pipes in threads
            loop.run_in_executor(executor, read_pipe, process.stdout, "stdout")
            loop.run_in_executor(executor, read_pipe, process.stderr, "stderr")
            
            # Process messages from queue
            async def process_messages():
                while True:
                    try:
                        level, message = await asyncio.wait_for(message_queue.get(), timeout=0.1)
                        # Collect stderr messages for error reporting
                        if level == "stderr":
                            stderr_lines.append(message)
                        
                        # Check for screenshot message and emit immediately
                        if "[SCREENSHOT] Captured after:" in message and "| PATH:" in message:
                            try:
                                # Extract screenshot path from message
                                # Format: "[SCREENSHOT] Captured after: {step} | PATH: {path}"
                                path_part = message.split("| PATH:")[-1].strip()
                                if path_part:
                                    screenshot_path = Path(path_part)
                                    # Resolve relative paths relative to APP_MCP_DIR
                                    if not screenshot_path.is_absolute():
                                        screenshot_path = (APP_MCP_DIR / screenshot_path).resolve()
                                    # Copy screenshot to reports directory for frontend access
                                    if screenshot_path.exists():
                                        # Get run_id from context (we need to pass it or get it from somewhere)
                                        # For now, use a timestamp-based name
                                        screenshot_name = f"screenshot_{int(time.time() * 1000)}.png"
                                        dest_path = (self.reports_dir / screenshot_name).resolve()
                                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.copyfile(screenshot_path, dest_path)
                                        
                                        # Extract step description
                                        step_desc = message.split("Captured after:")[-1].split("| PATH:")[0].strip()
                                        
                                        # Emit screenshot event immediately
                                        emit({
                                            "type": "screenshot",
                                            "screenshot": {
                                                "id": dest_path.stem,
                                                "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}",
                                                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                "step": step_desc or "Automation step",
                                            },
                                        })
                                    else:
                                        # Log warning if screenshot path doesn't exist
                                        print(f"[WARN] Screenshot path does not exist: {screenshot_path}", file=sys.stderr)
                            except Exception as screenshot_error:
                                # Log error for debugging
                                print(f"[ERROR] Failed to process screenshot: {screenshot_error}", file=sys.stderr)
                                import traceback
                                traceback.print_exc()
                        
                        # Filter out verbose internal logs - only show essential user-facing messages
                        # Hide all connection, MCP, Appium, and technical setup messages
                        should_skip = (
                            "[THINK]" in message or
                            "[CHECK]" in message or
                            "[TOOL]" in message or
                            "[INFO]" in message or
                            "[LIST]" in message or
                            "[SCREENSHOT]" in message or
                            "ACT:" in message or
                            "RESULT:" in message or
                            "OBSERVE:" in message or
                            "THINK:" in message or
                            "=" * 60 in message or  # Skip separator lines
                            "Getting page source" in message or
                            "Using cached page source" in message or
                            "Asking LLM" in message or
                            "Auto-hiding keyboard" in message or
                            "Keyboard hidden" in message or
                            "Auto-injected" in message or
                            "Warning: No session ID" in message or
                            "Auto-detected" in message or
                            "Found EditText" in message or
                            "may be a container" in message or
                            "Element found using" in message or
                            "/tools/run endpoint" in message or
                            "Session initialized" in message or
                            "Stored session ID" in message or
                            "Attempting to initialize" in message or
                            "[RETRY]" in message or
                            "[FALLBACK]" in message or
                            "[SUCCESS]" in message or
                            "[FAILED]" in message or
                            "Attempt" in message and "/" in message and ":" in message or  # Skip retry attempts
                            "Trying fallback" in message or
                            "Scrolling to element" in message or
                            "Waiting for element with longer timeout" in message or
                            "Pressing back button" in message or
                            "Retrying" in message or
                            "Trying alternate" in message or
                            "Action succeeded on attempt" in message or
                            "Action failed after" in message or
                            "Spawning automation runner" in message or
                            "What is your goal?" in message or
                            # Connection and setup messages - hide from users
                            "Connecting to" in message or
                            "MCP Server" in message or
                            "MCP server" in message or
                            "Appium" in message or
                            "appium" in message or
                            "driver initialized" in message.lower() or
                            "session ID" in message.lower() or
                            "session id" in message.lower() or
                            "active appium session" in message.lower() or
                            "checking for active" in message.lower() or
                            "device detected" in message.lower() or
                            "device type" in message.lower() or
                            "initialized successfully" in message.lower() or
                            "running and accessible" in message.lower()
                        )
                        
                        if should_skip:
                            continue
                        
                        # Parse log level from message prefixes
                        log_level = "info"
                        if level in ("stderr", "error"):
                            log_level = "error"
                        elif "Result: Pass" in message or "completed successfully" in message.lower():
                            log_level = "success"
                        elif "Result: Fail" in message or "Error:" in message or "failed" in message.lower() and "step" in message.lower():
                            log_level = "error"
                        elif "Step" in message and ":" in message:
                            log_level = "action"
                        elif "[REPORT]" in message or "[STATS]" in message or "Test Report:" in message:
                            log_level = "success"
                        
                        # Simplify message text - make it user-friendly
                        simplified_message = message
                        # Remove verbose prefixes
                        simplified_message = simplified_message.replace("--- ", "")
                        simplified_message = simplified_message.replace("[OK] ", "")
                        simplified_message = simplified_message.replace("[ERROR] ", "")
                        simplified_message = simplified_message.replace("[WARN] ", "")
                        simplified_message = simplified_message.replace("[BOT] ", "")
                        
                        # Simplify step messages - extract just the action
                        if "Step" in simplified_message and ":" in simplified_message:
                            parts = simplified_message.split(":", 1)
                            if len(parts) > 1:
                                simplified_message = parts[1].strip()
                        
                        # Simplify "Result: Pass/Fail" messages - make them very clear
                        if "Result: Pass" in simplified_message:
                            simplified_message = "✓ Pass"
                        elif "Result: Fail" in simplified_message:
                            # Extract error message if available, but keep it brief
                            if "Error:" in simplified_message:
                                error_part = simplified_message.split("Error:")[-1].strip()
                                # Truncate long error messages
                                if len(error_part) > 100:
                                    error_part = error_part[:100] + "..."
                                simplified_message = f"✗ Fail: {error_part}"
                            else:
                                simplified_message = "✗ Fail"
                        
                        # Clean up action messages - make them user-friendly and concise
                        if "Action: click" in simplified_message:
                            # Extract what we're clicking on
                            if "value':" in simplified_message or "'value':" in simplified_message:
                                try:
                                    import re
                                    match = re.search(r"['\"]value['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                    if match:
                                        item = match.group(1)
                                        # Clean up item name (remove IDs, keep readable text)
                                        if item.startswith("test-"):
                                            item = item.replace("test-", "").replace("-", " ").title()
                                        simplified_message = f"Click on {item}"
                                    else:
                                        simplified_message = "Click element"
                                except:
                                    simplified_message = "Click element"
                            else:
                                simplified_message = "Click element"
                        elif "Action: send_keys" in simplified_message or "Action: ensure_focus_and_type" in simplified_message:
                            # Extract what we're typing
                            if "text':" in simplified_message or "'text':" in simplified_message:
                                try:
                                    import re
                                    match = re.search(r"['\"]text['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                    if match:
                                        text = match.group(1)
                                        simplified_message = f"Type: {text}"
                                    else:
                                        simplified_message = "Type text"
                                except:
                                    simplified_message = "Type text"
                            else:
                                simplified_message = "Type text"
                        elif "Action: scroll_to_element" in simplified_message:
                            simplified_message = "Scroll to element"
                        elif "Action:" in simplified_message:
                            # Generic action cleanup - remove "Action:" prefix
                            simplified_message = simplified_message.replace("Action: ", "").strip()
                            # Capitalize first letter for readability
                            if simplified_message:
                                simplified_message = simplified_message[0].upper() + simplified_message[1:] if len(simplified_message) > 1 else simplified_message.upper()
                            if not simplified_message:
                                continue
                        
                        emit({
                            "type": "log",
                            "id": uuid.uuid4().hex,
                            "level": log_level,
                            "message": simplified_message,
                        })
                    except asyncio.TimeoutError:
                        # Check if process is still running
                        if process.poll() is not None:
                            # Process finished, drain remaining messages
                            while not message_queue.empty():
                                try:
                                    level, message = message_queue.get_nowait()
                                    if level == "stderr":
                                        stderr_lines.append(message)
                                    
                                    # Check for screenshot message and emit immediately (same as above)
                                    if "[SCREENSHOT] Captured after:" in message and "| PATH:" in message:
                                        try:
                                            path_part = message.split("| PATH:")[-1].strip()
                                            if path_part:
                                                screenshot_path = Path(path_part)
                                                # Resolve relative paths relative to APP_MCP_DIR
                                                if not screenshot_path.is_absolute():
                                                    screenshot_path = (APP_MCP_DIR / screenshot_path).resolve()
                                                if screenshot_path.exists():
                                                    screenshot_name = f"screenshot_{int(time.time() * 1000)}.png"
                                                    dest_path = (self.reports_dir / screenshot_name).resolve()
                                                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                                                    shutil.copyfile(screenshot_path, dest_path)
                                                    
                                                    step_desc = message.split("Captured after:")[-1].split("| PATH:")[0].strip()
                                                    
                                                    emit({
                                                        "type": "screenshot",
                                                        "screenshot": {
                                                            "id": dest_path.stem,
                                                            "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}",
                                                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                                            "step": step_desc or "Automation step",
                                                        },
                                                    })
                                        except Exception:
                                            pass
                                    
                                    # Filter out verbose internal logs - only show essential user-facing messages
                                    # Hide all connection, MCP, Appium, and technical setup messages
                                    should_skip = (
                                        "[THINK]" in message or
                                        "[CHECK]" in message or
                                        "[TOOL]" in message or
                                        "[INFO]" in message or
                                        "[LIST]" in message or
                                        "[SCREENSHOT]" in message or
                                        "ACT:" in message or
                                        "RESULT:" in message or
                                        "OBSERVE:" in message or
                                        "THINK:" in message or
                                        "=" * 60 in message or
                                        "Getting page source" in message or
                                        "Using cached page source" in message or
                                        "Asking LLM" in message or
                                        "Auto-hiding keyboard" in message or
                                        "Keyboard hidden" in message or
                                        "Auto-injected" in message or
                                        "Warning: No session ID" in message or
                                        "Auto-detected" in message or
                                        "Found EditText" in message or
                                        "may be a container" in message or
                                        "Element found using" in message or
                                        "/tools/run endpoint" in message or
                                        "Session initialized" in message or
                                        "Stored session ID" in message or
                                        "Attempting to initialize" in message or
                                        "[RETRY]" in message or
                                        "[FALLBACK]" in message or
                                        "[SUCCESS]" in message or
                                        "[FAILED]" in message or
                                        "Attempt" in message and "/" in message and ":" in message or
                                        "Trying fallback" in message or
                                        "Scrolling to element" in message or
                                        "Waiting for element with longer timeout" in message or
                                        "Pressing back button" in message or
                                        "Retrying" in message or
                                        "Trying alternate" in message or
                                        "Action succeeded on attempt" in message or
                                        "Action failed after" in message or
                                        "Spawning automation runner" in message or
                                        "What is your goal?" in message or
                                        # Connection and setup messages - hide from users
                                        "Connecting to" in message or
                                        "MCP Server" in message or
                                        "MCP server" in message or
                                        "Appium" in message or
                                        "appium" in message or
                                        "driver initialized" in message.lower() or
                                        "session ID" in message.lower() or
                                        "session id" in message.lower() or
                                        "active appium session" in message.lower() or
                                        "checking for active" in message.lower() or
                                        "device detected" in message.lower() or
                                        "device type" in message.lower() or
                                        "initialized successfully" in message.lower() or
                                        "running and accessible" in message.lower()
                                    )
                                    
                                    if should_skip:
                                        continue
                                    
                                    # Parse log level from message prefixes
                                    log_level = "info"
                                    if level in ("stderr", "error"):
                                        log_level = "error"
                                    elif "Result: Pass" in message or "completed successfully" in message.lower():
                                        log_level = "success"
                                    elif "Result: Fail" in message or "Error:" in message or "failed" in message.lower() and "step" in message.lower():
                                        log_level = "error"
                                    elif "Step" in message and ":" in message:
                                        log_level = "action"
                                    elif "[REPORT]" in message or "[STATS]" in message or "Test Report:" in message:
                                        log_level = "success"
                                    
                                    # Simplify message text - make it user-friendly
                                    simplified_message = message
                                    simplified_message = simplified_message.replace("--- ", "")
                                    simplified_message = simplified_message.replace("[OK] ", "")
                                    simplified_message = simplified_message.replace("[ERROR] ", "")
                                    simplified_message = simplified_message.replace("[WARN] ", "")
                                    simplified_message = simplified_message.replace("[BOT] ", "")
                                    
                                    if "Step" in simplified_message and ":" in simplified_message:
                                        parts = simplified_message.split(":", 1)
                                        if len(parts) > 1:
                                            simplified_message = parts[1].strip()
                                    
                                    if "Result: Pass" in simplified_message:
                                        simplified_message = "✓ Pass"
                                    elif "Result: Fail" in simplified_message:
                                        if "Error:" in simplified_message:
                                            error_part = simplified_message.split("Error:")[-1].strip()
                                            # Truncate long error messages
                                            if len(error_part) > 100:
                                                error_part = error_part[:100] + "..."
                                            simplified_message = f"✗ Fail: {error_part}"
                                        else:
                                            simplified_message = "✗ Fail"
                                    
                                    if "Action: click" in simplified_message:
                                        if "value':" in simplified_message or "'value':" in simplified_message:
                                            try:
                                                import re
                                                match = re.search(r"['\"]value['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                                if match:
                                                    item = match.group(1)
                                                    simplified_message = f"Clicking on {item}"
                                                else:
                                                    simplified_message = "Clicking element"
                                            except:
                                                simplified_message = "Clicking element"
                                        else:
                                            simplified_message = "Clicking element"
                                    elif "Action: send_keys" in simplified_message or "Action: ensure_focus_and_type" in simplified_message:
                                        if "text':" in simplified_message or "'text':" in simplified_message:
                                            try:
                                                import re
                                                match = re.search(r"['\"]text['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                                if match:
                                                    text = match.group(1)
                                                    simplified_message = f"Typing: {text}"
                                                else:
                                                    simplified_message = "Typing text"
                                            except:
                                                simplified_message = "Typing text"
                                        else:
                                            simplified_message = "Typing text"
                                    elif "Action:" in simplified_message:
                                        simplified_message = simplified_message.replace("Action: ", "").strip()
                                        if not simplified_message:
                                            continue
                                    
                                    emit({
                                        "type": "log",
                                        "id": uuid.uuid4().hex,
                                        "level": log_level,
                                        "message": simplified_message,
                                    })
                                except asyncio.QueueEmpty:
                                    break
                            break
                    except Exception:
                        break
            
            message_task = asyncio.create_task(process_messages())
            
            # Wait for process to complete
            def wait_process():
                return process.wait()
            
            return_code = await loop.run_in_executor(executor, wait_process)
            await message_task
            executor.shutdown(wait=False)
            
        else:
            # Use native asyncio subprocess for Unix-like systems
            # Ensure unbuffered output for real-time logs
            env['PYTHONUNBUFFERED'] = '1'
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(BASE_DIR / "main.py"),
                "--prompt",
                prompt,
                cwd=str(BASE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            stderr_lines = []
            
            async def _stream(reader: asyncio.StreamReader, level: str) -> None:
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    try:
                        message = line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        message = line.decode("latin-1", errors="replace").rstrip()
                    if not message:
                        continue
                    if level == "stderr":
                        stderr_lines.append(message)
                    
                    # Check for screenshot message and emit immediately (same as above)
                    if "[SCREENSHOT] Captured after:" in message and "| PATH:" in message:
                        try:
                            path_part = message.split("| PATH:")[-1].strip()
                            if path_part:
                                screenshot_path = Path(path_part)
                                # Resolve relative paths relative to APP_MCP_DIR
                                if not screenshot_path.is_absolute():
                                    screenshot_path = (APP_MCP_DIR / screenshot_path).resolve()
                                if screenshot_path.exists():
                                    screenshot_name = f"screenshot_{int(time.time() * 1000)}.png"
                                    dest_path = (self.reports_dir / screenshot_name).resolve()
                                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copyfile(screenshot_path, dest_path)
                                    
                                    step_desc = message.split("Captured after:")[-1].split("| PATH:")[0].strip()
                                    
                                    emit({
                                        "type": "screenshot",
                                        "screenshot": {
                                            "id": dest_path.stem,
                                            "url": f"{REPORTS_PUBLIC_URL}/{dest_path.name}",
                                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            "step": step_desc or "Automation step",
                                        },
                                    })
                        except Exception:
                            pass
                    
                    # Filter out verbose internal logs - only show essential user-facing messages
                    # Hide all connection, MCP, Appium, and technical setup messages
                    should_skip = (
                        "[THINK]" in message or
                        "[CHECK]" in message or
                        "[TOOL]" in message or
                        "[INFO]" in message or
                        "[LIST]" in message or
                        "[SCREENSHOT]" in message or
                        "ACT:" in message or
                        "RESULT:" in message or
                        "OBSERVE:" in message or
                        "THINK:" in message or
                        "=" * 60 in message or
                        "Getting page source" in message or
                        "Using cached page source" in message or
                        "Asking LLM" in message or
                        "Auto-hiding keyboard" in message or
                        "Keyboard hidden" in message or
                        "Auto-injected" in message or
                        "Warning: No session ID" in message or
                        "Auto-detected" in message or
                        "Found EditText" in message or
                        "may be a container" in message or
                        "Element found using" in message or
                        "/tools/run endpoint" in message or
                        "Session initialized" in message or
                        "Stored session ID" in message or
                        "Attempting to initialize" in message or
                        "[RETRY]" in message or
                        "[FALLBACK]" in message or
                        "[SUCCESS]" in message or
                        "[FAILED]" in message or
                        "Attempt" in message and "/" in message and ":" in message or
                        "Trying fallback" in message or
                        "Scrolling to element" in message or
                        "Waiting for element with longer timeout" in message or
                        "Pressing back button" in message or
                        "Retrying" in message or
                        "Trying alternate" in message or
                        "Action succeeded on attempt" in message or
                        "Action failed after" in message or
                        "Spawning automation runner" in message or
                        "What is your goal?" in message or
                        # Connection and setup messages - hide from users
                        "Connecting to" in message or
                        "MCP Server" in message or
                        "MCP server" in message or
                        "Appium" in message or
                        "appium" in message or
                        "driver initialized" in message.lower() or
                        "session ID" in message.lower() or
                        "session id" in message.lower() or
                        "active appium session" in message.lower() or
                        "checking for active" in message.lower() or
                        "device detected" in message.lower() or
                        "device type" in message.lower() or
                        "initialized successfully" in message.lower() or
                        "running and accessible" in message.lower()
                    )
                    
                    if should_skip:
                        continue
                    
                    # Parse log level from message prefixes
                    log_level = "info"
                    if level in ("stderr", "error"):
                        log_level = "error"
                    elif "Result: Pass" in message or "completed successfully" in message.lower():
                        log_level = "success"
                    elif "Result: Fail" in message or "Error:" in message or "failed" in message.lower() and "step" in message.lower():
                        log_level = "error"
                    elif "Step" in message and ":" in message:
                        log_level = "action"
                    elif "[REPORT]" in message or "[STATS]" in message or "Test Report:" in message:
                        log_level = "success"
                    
                    # Simplify message text - make it user-friendly
                    simplified_message = message
                    simplified_message = simplified_message.replace("--- ", "")
                    simplified_message = simplified_message.replace("[OK] ", "")
                    simplified_message = simplified_message.replace("[ERROR] ", "")
                    simplified_message = simplified_message.replace("[WARN] ", "")
                    simplified_message = simplified_message.replace("[BOT] ", "")
                    
                    if "Step" in simplified_message and ":" in simplified_message:
                        parts = simplified_message.split(":", 1)
                        if len(parts) > 1:
                            simplified_message = parts[1].strip()
                    
                    if "Result: Pass" in simplified_message:
                        simplified_message = "✓ Pass"
                    elif "Result: Fail" in simplified_message:
                        if "Error:" in simplified_message:
                            error_part = simplified_message.split("Error:")[-1].strip()
                            # Truncate long error messages
                            if len(error_part) > 100:
                                error_part = error_part[:100] + "..."
                            simplified_message = f"✗ Fail: {error_part}"
                        else:
                            simplified_message = "✗ Fail"
                    
                    if "Action: click" in simplified_message:
                        if "value':" in simplified_message or "'value':" in simplified_message:
                            try:
                                import re
                                match = re.search(r"['\"]value['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                if match:
                                    item = match.group(1)
                                    simplified_message = f"Clicking on {item}"
                                else:
                                    simplified_message = "Clicking element"
                            except:
                                simplified_message = "Clicking element"
                        else:
                            simplified_message = "Clicking element"
                    elif "Action: send_keys" in simplified_message or "Action: ensure_focus_and_type" in simplified_message:
                        if "text':" in simplified_message or "'text':" in simplified_message:
                            try:
                                import re
                                match = re.search(r"['\"]text['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                                if match:
                                    text = match.group(1)
                                    simplified_message = f"Typing: {text}"
                                else:
                                    simplified_message = "Typing text"
                            except:
                                simplified_message = "Typing text"
                        else:
                            simplified_message = "Typing text"
                    elif "Action:" in simplified_message:
                        simplified_message = simplified_message.replace("Action: ", "").strip()
                        if not simplified_message:
                            continue
                    
                    emit(
                        {
                            "type": "log",
                            "id": uuid.uuid4().hex,
                            "level": log_level,
                            "message": simplified_message,
                        }
                    )

            stdout_task = asyncio.create_task(_stream(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(_stream(process.stderr, "stderr"))

            return_code = await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        if return_code != 0:
            error_summary = "\n".join(stderr_lines[-10:]) if stderr_lines else "No error details captured"
            emit(
                {
                    "type": "log",
                    "id": uuid.uuid4().hex,
                    "level": "error",
                    "message": f"Automation runner exited with code {return_code}",
                    "details": f"Last stderr lines:\n{error_summary}",
                }
            )
            raise AutomationRunnerError(
                f"Automation runner failed with code {return_code}. "
                f"Error details: {error_summary[:500]}"
            )

        report_path = self._find_newest_report(existing_reports, started_at)
        if report_path:
            # Generate PDF report
            pdf_path = None
            try:
                from pdf_generator import PDFReportGenerator
                pdf_generator = PDFReportGenerator(reports_dir=str(self.reports_dir))
                pdf_path = pdf_generator.generate_pdf(report_path)
            except ImportError:
                # reportlab not installed, skip PDF generation
                pass
            except Exception as e:
                print(f"Warning: Failed to generate PDF report: {e}")
            
            emit(
                {
                    "type": "report",
                    "report": {
                        "id": report_path.stem,
                        "name": report_path.name,
                        "path": str(report_path),
                        "pdfPath": str(pdf_path) if pdf_path else None,
                        "status": "success",
                        "createdAt": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(report_path.stat().st_mtime)
                        ),
                        "prompt": prompt,
                    },
                }
            )
            self._emit_screenshots_from_report(report_path, emit)

    def _iter_report_files(self) -> Iterable[Path]:
        return self.reports_dir.glob("*.json")

    def _find_newest_report(
        self, existing_reports: set[Path], started_at: float
    ) -> Optional[Path]:
        candidates = [
            path
            for path in self._iter_report_files()
            if path not in existing_reports and path.stat().st_mtime >= started_at
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def _emit_screenshots_from_report(
        self, report_path: Path, emit: AutomationEventCallback
    ) -> None:
        try:
            with report_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (json.JSONDecodeError, OSError) as exc:
            emit(
                {
                    "type": "log",
                    "id": uuid.uuid4().hex,
                    "level": "error",
                    "message": "Failed to parse report for screenshots",
                    "details": str(exc),
                }
            )
            return

        steps = data.get("steps", []) if isinstance(data, dict) else []
        for step in steps:
            if not isinstance(step, dict):
                continue
            # Only emit after_screenshot_path (meaningful screenshots after actions)
            # Skip before_screenshot_path and OCR screenshots
            raw_path = step.get("after_screenshot_path")
            if not raw_path:
                continue
            
            # Filter out OCR screenshots
            path_str = str(raw_path).lower()
            if "ocr_search" in path_str or "perception_" in path_str:
                continue
                
            screenshot_file = Path(raw_path)
            if not screenshot_file.is_absolute():
                # Try resolving relative to APP_MCP_DIR first (where screenshots are saved)
                temp_path = (APP_MCP_DIR / screenshot_file).resolve()
                if temp_path.exists():
                    screenshot_file = temp_path
                else:
                    # Fallback to reports_dir
                    screenshot_file = (self.reports_dir / screenshot_file).resolve()
            if not screenshot_file.exists():
                continue
            emit(
                {
                    "type": "screenshot",
                    "screenshot": {
                        "id": screenshot_file.stem,
                        "url": f"{REPORTS_PUBLIC_URL}/{screenshot_file.name}",
                        "timestamp": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(screenshot_file.stat().st_mtime),
                        ),
                        "step": step.get("description") or step.get("action") or "Screenshot",
                    },
                }
            )


__all__ = [
    "AutomationRunner",
    "AutomationRunnerError",
    "REPORTS_DIR",
    "REPORTS_PUBLIC_URL",
]

