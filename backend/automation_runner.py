from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import signal
import subprocess
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
        self._current_process: Optional[Any] = None  # Store reference to current subprocess
        self._should_stop = False  # Flag to signal stop request

    def stop(self) -> None:
        """Stop the currently running automation subprocess."""
        self._should_stop = True
        if self._current_process is not None:
            try:
                import platform
                is_windows = platform.system() == "Windows"
                
                # Check if process is still running
                is_running = False
                if hasattr(self._current_process, 'poll'):
                    # subprocess.Popen (Windows)
                    is_running = self._current_process.poll() is None
                elif hasattr(self._current_process, 'returncode'):
                    # asyncio subprocess (Unix)
                    is_running = self._current_process.returncode is None
                else:
                    is_running = True  # Assume running if we can't check
                
                if not is_running:
                    return  # Process already finished
                
                # On Windows, use kill() directly for more reliable termination
                # On Unix, try terminate() first, then kill() if needed
                if is_windows:
                    # Windows: Use kill() directly (more reliable than terminate)
                    try:
                        if hasattr(self._current_process, 'kill'):
                            self._current_process.kill()
                        elif hasattr(self._current_process, 'terminate'):
                            self._current_process.terminate()
                            # Wait briefly, then force kill
                            import time
                            time.sleep(0.5)
                            if self._current_process.poll() is None:
                                self._current_process.kill()
                    except Exception as e:
                        print(f"[WARN] Error killing process on Windows: {e}")
                        # Try alternative method
                        try:
                            import os
                            if hasattr(self._current_process, 'pid'):
                                os.kill(self._current_process.pid, 9)  # SIGKILL equivalent
                        except Exception:
                            pass
                else:
                    # Unix: Try terminate first, then kill
                    try:
                        if hasattr(self._current_process, 'terminate'):
                            self._current_process.terminate()
                        elif hasattr(self._current_process, 'kill'):
                            self._current_process.kill()
                        
                        # Wait briefly for graceful shutdown
                        import time
                        time.sleep(1)
                        
                        # Force kill if still running
                        if hasattr(self._current_process, 'poll'):
                            if self._current_process.poll() is None:
                                self._current_process.kill()
                        elif hasattr(self._current_process, 'returncode'):
                            if self._current_process.returncode is None:
                                self._current_process.kill()
                    except Exception as e:
                        print(f"[WARN] Error terminating process on Unix: {e}")
                        # Force kill as last resort
                        try:
                            if hasattr(self._current_process, 'kill'):
                                self._current_process.kill()
                        except Exception:
                            pass
            except Exception as e:
                print(f"[WARN] Error in stop(): {e}")
                # Last resort: try to kill by PID if available
                try:
                    if hasattr(self._current_process, 'pid'):
                        import os
                        import platform
                        if platform.system() == "Windows":
                            os.kill(self._current_process.pid, 9)
                        else:
                            os.kill(self._current_process.pid, signal.SIGKILL)
                except Exception:
                    pass

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
                "message": "Automation initiated",
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
            self._current_process = process  # Store process reference for cancellation
            
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
                    # Check if stop was requested
                    if self._should_stop:
                        break
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
                        # Hide debug information about LLM input size
                        if ("[DEBUG] LLM Input Size" in message or
                            "System Prompt:" in message or
                            "Messages (" in message and "messages):" in message or
                            "Tools (" in message and "tools):" in message or
                            "TOTAL:" in message and "chars" in message and "tokens" in message or
                            "XML Limit:" in message):
                            continue
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
            
            # Wait for process to complete, checking for stop request
            def wait_process():
                while process.poll() is None:
                    if self._should_stop:
                        # Stop was requested - kill the process immediately
                        try:
                            # On Windows, kill() is more reliable than terminate()
                            if platform.system() == "Windows":
                                process.kill()
                            else:
                                # On Unix, try terminate first, then kill
                                process.terminate()
                                # Wait briefly for graceful shutdown
                                try:
                                    process.wait(timeout=1)
                                except subprocess.TimeoutExpired:
                                    # Force kill if it doesn't terminate quickly
                                    process.kill()
                        except Exception as e:
                            # If terminate/kill fails, try alternative methods
                            try:
                                if process.poll() is None:
                                    process.kill()
                            except Exception:
                                # Last resort: kill by PID
                                try:
                                    if hasattr(process, 'pid'):
                                        os.kill(process.pid, signal.SIGKILL if platform.system() != "Windows" else 9)
                                except Exception:
                                    pass
                        break
                    time.sleep(0.05)  # Check every 50ms (faster response)
                return process.poll()
            
            return_code = await loop.run_in_executor(executor, wait_process)
            await message_task
            executor.shutdown(wait=False)
            
            # Clear process reference after completion
            self._current_process = None
            self._should_stop = False
            
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
            self._current_process = process  # Store process reference for cancellation

            stderr_lines = []
            
            async def _stream(reader: asyncio.StreamReader, level: str) -> None:
                # Check for stop request periodically
                if self._should_stop:
                    return
                while True:
                    # Check for stop request
                    if self._should_stop:
                        break
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
                        # Validation detection messages - hide from users
                        ("Detected" in message and "validation requirement" in message.lower()) or
                        "Validate:" in message or
                        "- Validate:" in message or
                        "   - Validate:" in message or
                        # Technical tool management messages - hide from users
                        "Removing orphaned tool_use" in message or
                        "Removing orphaned tool_result" in message or
                        "tool_use_id:" in message or
                        "no tool_result found" in message.lower() or
                        "no previous assistant message" in message.lower() or
                        # LLM decision technical details - hide from users
                        "LLM Decision: Call" in message and "args:" in message or
                        "LLM Decision:" in message or
                        # End turn messages - hide from users
                        "LLM returned end_turn" in message or
                        "end_turn but not all planned steps" in message.lower() or
                        # Page detection technical messages - hide from users
                        "[NAV]" in message or
                        "Page Detected:" in message or
                        "AUTOMATIC PAGE DETECTION" in message or
                        "Page Identified:" in message or
                        # Bedrock API error technical details - hide from users
                        "Non-retryable Bedrock error" in message or
                        "Bedrock API Error" in message and "ValidationException" in message or
                        "ValidationException" in message or
                        "Input is too long" in message or
                        # Interrupt and error messages - hide from users
                        "Interrupted by user" in message or
                        "KeyboardInterrupt" in message or
                        # Python traceback and stack traces - hide from users
                        "Traceback (most recent call last)" in message or
                        ("File \"" in message or "File " in message) and ("line" in message.lower() or "site-packages" in message or ".py" in message) or
                        "  File " in message or
                        (message.startswith("    ") and len(message) > 4 and any(x in message for x in ["File ", "return ", "raise ", "self.", "http", "response", "request", "invoke", "api_call"])) or
                        "site-packages" in message or
                        "botocore" in message.lower() or
                        "urllib3" in message.lower() or
                        "socket.py" in message or
                        "ssl.py" in message or
                        ".py\", line" in message or
                        "in " in message and ("File " in message or ".py" in message) or
                        # Exit codes and error reporting - hide from users
                        "Automation runner exited with code" in message or
                        "Automation runner reported an error" in message or
                        "exited with code" in message.lower() or
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
                    
                    # Remove technical prefixes
                    simplified_message = simplified_message.replace("--- ", "")
                    simplified_message = simplified_message.replace("[OK] ", "")
                    simplified_message = simplified_message.replace("[ERROR] ", "")
                    simplified_message = simplified_message.replace("[WARN] ", "")
                    simplified_message = simplified_message.replace("[BOT] ", "")
                    simplified_message = simplified_message.replace("[THINK] ", "")
                    simplified_message = simplified_message.replace("[INFO] ", "")
                    
                    # Transform "LLM is thinking" messages
                    if "THINK:" in simplified_message or "Asking LLM" in simplified_message or "LLM Decision" in simplified_message:
                        simplified_message = "LLM is thinking..."
                        log_level = "info"
                    
                    # Transform step messages
                    elif "Step" in simplified_message and ":" in simplified_message:
                        parts = simplified_message.split(":", 1)
                        if len(parts) > 1:
                            step_desc = parts[1].strip()
                            # Extract action name from step description
                            if "Click" in step_desc or "click" in step_desc:
                                # Try to extract element name
                                # Look for common patterns like "Click on Login" or "Click Login button"
                                match = re.search(r'(?:Click|click)\s+(?:on\s+)?([A-Z][a-zA-Z\s]+?)(?:\s+button|\s+element|$)', step_desc)
                                if match:
                                    element_name = match.group(1).strip()
                                    simplified_message = f"Click on {element_name}"
                                else:
                                    simplified_message = "Clicking element"
                            elif "Type" in step_desc or "Enter" in step_desc or "type" in step_desc or "enter" in step_desc:
                                # Try to extract text being typed
                                match = re.search(r'(?:Type|Enter|type|enter).*?["\']([^"\']+)["\']', step_desc)
                                if match:
                                    text_value = match.group(1)
                                    simplified_message = f"Typing: {text_value}"
                                else:
                                    simplified_message = "Typing text"
                            elif "Wait" in step_desc or "wait" in step_desc:
                                simplified_message = "Waiting..."
                            elif "Swipe" in step_desc or "swipe" in step_desc:
                                simplified_message = "Swiping"
                            elif "Scroll" in step_desc or "scroll" in step_desc:
                                simplified_message = "Scrolling"
                            else:
                                simplified_message = step_desc
                        log_level = "action"
                    
                    # Transform success messages
                    elif "[SUCCESS]" in simplified_message:
                        # Extract success message after [SUCCESS]
                        success_text = simplified_message.split("[SUCCESS]")[-1].strip()
                        simplified_message = f"✓ {success_text}"
                        log_level = "success"
                    # Transform action results
                    elif "Result: Pass" in simplified_message or "completed successfully" in simplified_message.lower():
                        simplified_message = "✓ Action completed successfully"
                        log_level = "success"
                    elif "Result: Fail" in simplified_message or "failed" in simplified_message.lower():
                        if "Error:" in simplified_message:
                            error_part = simplified_message.split("Error:")[-1].strip()
                            # Simplify technical error messages
                            if "page source" in error_part.lower() or "session" in error_part.lower() or "driver" in error_part.lower():
                                simplified_message = "⚠ Action encountered an issue, continuing..."
                            elif "not found" in error_part.lower() or "element" in error_part.lower():
                                simplified_message = "⚠ Element not found, trying alternative approach..."
                            else:
                                # Truncate long error messages
                                if len(error_part) > 80:
                                    error_part = error_part[:80] + "..."
                                simplified_message = f"⚠ Issue: {error_part}"
                        else:
                            simplified_message = "⚠ Action had an issue, continuing..."
                        log_level = "error"
                    
                    # Transform action messages
                    elif "Action: click" in simplified_message or "Call click" in simplified_message:
                        # Try to extract element name/value
                        match = re.search(r"['\"]value['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                        if match:
                            item = match.group(1)
                            simplified_message = f"Click on {item}"
                        else:
                            simplified_message = "Clicking element"
                        log_level = "action"
                    elif "Action: send_keys" in simplified_message or "Action: ensure_focus_and_type" in simplified_message or "Call send_keys" in simplified_message or "Call ensure_focus_and_type" in simplified_message:
                        # Try to extract text being typed
                        match = re.search(r"['\"]text['\"]:\s*['\"]([^'\"]+)['\"]", simplified_message)
                        if match:
                            text = match.group(1)
                            simplified_message = f"Typing: {text}"
                        else:
                            simplified_message = "Typing text"
                        log_level = "action"
                    elif "Action:" in simplified_message or "Call " in simplified_message:
                        # Extract action name
                        action_match = re.search(r"(?:Action:\s*|Call\s+)(\w+)", simplified_message)
                        if action_match:
                            action_name = action_match.group(1)
                            if action_name == "wait_for_text_ocr":
                                simplified_message = "Waiting for text to appear..."
                            elif action_name == "swipe":
                                simplified_message = "Swiping"
                            elif action_name == "scroll":
                                simplified_message = "Scrolling"
                            elif action_name == "long_press":
                                simplified_message = "Long pressing"
                            else:
                                simplified_message = f"Performing {action_name}..."
                        else:
                            simplified_message = simplified_message.replace("Action: ", "").replace("Call ", "").strip()
                        if not simplified_message:
                            continue
                        log_level = "action"
                    
                    # Transform report/statistics messages
                    elif "[REPORT]" in simplified_message or "[STATS]" in simplified_message:
                        if "Report:" in simplified_message:
                            simplified_message = "✓ Automation completed - Report generated"
                        elif "STATS" in simplified_message:
                            # Extract stats
                            stats_match = re.search(r'(\d+)\s+steps.*?✅\s+(\d+).*?❌\s+(\d+)', simplified_message)
                            if stats_match:
                                total, success, failed = stats_match.groups()
                                simplified_message = f"✓ Completed: {success} successful, {failed} failed out of {total} steps"
                            else:
                                simplified_message = "✓ Automation completed"
                        log_level = "success"
                    
                    # Transform error messages to be less technical
                    elif "Error:" in simplified_message or "ERROR" in simplified_message:
                        error_text = simplified_message.split("Error:")[-1].strip() if "Error:" in simplified_message else simplified_message
                        # Simplify common technical errors
                        if "page source" in error_text.lower():
                            simplified_message = "⚠ Checking screen status..."
                        elif "session" in error_text.lower() or "driver" in error_text.lower() or "expired" in error_text.lower():
                            simplified_message = "⚠ Connection issue detected, retrying..."
                        elif "not found" in error_text.lower() or "element" in error_text.lower():
                            simplified_message = "⚠ Element not found, trying different approach..."
                        elif "timeout" in error_text.lower():
                            simplified_message = "⚠ Taking longer than expected, continuing..."
                        else:
                            # Keep error but simplify
                            if len(error_text) > 100:
                                error_text = error_text[:100] + "..."
                            simplified_message = f"⚠ {error_text}"
                        log_level = "error"
                    
                    # Default: clean up any remaining technical prefixes
                    else:
                        # Remove any remaining technical markers
                        simplified_message = re.sub(r'\[.*?\]', '', simplified_message).strip()
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

            # Check for stop request periodically while waiting
            while process.returncode is None:
                if self._should_stop:
                    # Stop was requested - kill the process immediately
                    try:
                        # On Windows, kill() is more reliable than terminate()
                        if platform.system() == "Windows":
                            process.kill()
                        else:
                            # On Unix, try terminate first, then kill
                            process.terminate()
                            # Wait briefly for graceful shutdown
                            try:
                                await asyncio.wait_for(process.wait(), timeout=1.0)
                            except asyncio.TimeoutError:
                                # Force kill if it doesn't terminate quickly
                                process.kill()
                    except Exception as e:
                        # If terminate/kill fails, try alternative methods
                        try:
                            if process.returncode is None:
                                process.kill()
                        except Exception:
                            # Last resort: kill by PID
                            try:
                                if hasattr(process, 'pid'):
                                    if platform.system() == "Windows":
                                        os.kill(process.pid, 9)
                                    else:
                                        os.kill(process.pid, signal.SIGKILL)
                            except Exception:
                                pass
                    break
                await asyncio.sleep(0.05)  # Check every 50ms (faster response)
            
            return_code = process.returncode if process.returncode is not None else await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            
            # Clear process reference after completion
            self._current_process = None
            self._should_stop = False

        if return_code != 0:
            # Don't emit technical error messages to frontend - they're already filtered
            # Only show user-friendly message if automation was interrupted (Ctrl+C)
            if return_code in (3221225786, -1073741510, 130, 2):  # Windows Ctrl+C, Unix Ctrl+C, KeyboardInterrupt
                emit(
                    {
                        "type": "log",
                        "id": uuid.uuid4().hex,
                        "level": "info",
                        "message": "Automation stopped by user",
                    }
                )
            # For other errors, don't emit technical details - they're already in logs if needed
            error_summary = "\n".join(stderr_lines[-10:]) if stderr_lines else "No error details captured"
            raise AutomationRunnerError(
                f"Automation runner failed with code {return_code}. "
                f"Error details: {error_summary[:500]}"
            )

        # Wait a bit for the report file to be written to disk
        # Sometimes there's a small delay between when main.py prints [REPORT] and when the file is actually written
        report_path = None
        for attempt in range(5):  # Try up to 5 times with delays
            report_path = self._find_newest_report(existing_reports, started_at)
            if report_path:
                break
            if attempt < 4:  # Don't wait on last attempt
                await asyncio.sleep(0.5)  # Wait 500ms between attempts
        
        # If still not found, try looking in the current working directory's reports folder
        # (main.py might save to a relative "reports" directory)
        if not report_path:
            # Check if main.py is running from BASE_DIR and saving to relative "reports"
            possible_reports_dir = BASE_DIR / "reports"
            if possible_reports_dir.exists() and possible_reports_dir != self.reports_dir:
                # Look in the BASE_DIR/reports directory
                candidates = [
                    path
                    for path in possible_reports_dir.glob("*.json")
                    if path not in existing_reports and path.stat().st_mtime >= started_at
                ]
                if candidates:
                    report_path = max(candidates, key=lambda p: p.stat().st_mtime)
        
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
                print(f"Warning: Failed to generate PDF report: {e}", file=sys.stderr)
            
            # Emit report event to frontend
            try:
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
            except Exception as e:
                print(f"Warning: Failed to emit report event: {e}", file=sys.stderr)
        else:
            # Report not found - log for debugging but don't show to user
            print(f"[DEBUG] Report not found. Searched in: {self.reports_dir}", file=sys.stderr)
            if BASE_DIR / "reports" != self.reports_dir:
                print(f"[DEBUG] Also checked: {BASE_DIR / 'reports'}", file=sys.stderr)

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

