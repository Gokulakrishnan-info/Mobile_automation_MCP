"""
Logging utilities for capturing console output to a file.

The automation stack currently relies heavily on print statements for runtime
telemetry.  This module introduces a lightweight tee-style stream wrapper that
duplicates everything written to stdout/stderr into a timestamped log file so
developers can inspect a full transcript after a run.
"""

import atexit
import os
import sys
import threading
import time
from typing import Optional, TextIO

# Globals tracking the active log file/streams so setup happens only once.
_LOG_FILE_HANDLE: Optional[TextIO] = None
_LOG_FILE_PATH: Optional[str] = None
_STDOUT_ORIG: Optional[TextIO] = None
_STDERR_ORIG: Optional[TextIO] = None


class _TeeStream:
    """Stream wrapper that writes to both the original stream and the log file."""

    def __init__(self, original: TextIO, logfile: TextIO):
        self._original = original
        self._logfile = logfile
        self._lock = threading.Lock()
        # Preserve common attributes
        self.encoding = getattr(original, "encoding", "utf-8")
        self.errors = getattr(original, "errors", "replace")

    def write(self, data: str) -> int:
        with self._lock:
            written = self._original.write(data)
            self._logfile.write(data)
            return written

    def flush(self) -> None:
        with self._lock:
            self._original.flush()
            self._logfile.flush()

    def isatty(self) -> bool:
        return self._original.isatty()

    def __getattr__(self, name):
        return getattr(self._original, name)


def _close_log_file() -> None:
    global _LOG_FILE_HANDLE, _LOG_FILE_PATH, _STDOUT_ORIG, _STDERR_ORIG
    if _LOG_FILE_HANDLE:
        try:
            _LOG_FILE_HANDLE.flush()
            _LOG_FILE_HANDLE.close()
        except Exception:
            pass
    if _STDOUT_ORIG is not None:
        sys.stdout = _STDOUT_ORIG
    if _STDERR_ORIG is not None:
        sys.stderr = _STDERR_ORIG
    _LOG_FILE_HANDLE = None
    _STDOUT_ORIG = None
    _STDERR_ORIG = None


def get_log_file_path() -> Optional[str]:
    """Return the current log file path if logging has been initialized."""
    return _LOG_FILE_PATH


def setup_log_capture(
    log_dir: Optional[str] = None,
    filename_prefix: str = "automation_run"
) -> Optional[str]:
    """
    Mirror stdout/stderr to a timestamped log file so prints are persisted.

    Args:
        log_dir: Directory to store logs (defaults to backend/logs).
        filename_prefix: Prefix for the generated log filename.

    Returns:
        The absolute path to the log file, or None if setup failed.
    """
    global _LOG_FILE_HANDLE, _LOG_FILE_PATH, _STDOUT_ORIG, _STDERR_ORIG

    if _LOG_FILE_HANDLE:
        return _LOG_FILE_PATH

    base_dir = log_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(base_dir, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    log_filename = f"{filename_prefix}_{timestamp}.log"
    log_path = os.path.join(base_dir, log_filename)

    try:
        logfile = open(log_path, "w", encoding="utf-8", buffering=1)
    except OSError:
        return None

    _LOG_FILE_HANDLE = logfile
    _LOG_FILE_PATH = log_path
    _STDOUT_ORIG = sys.stdout
    _STDERR_ORIG = sys.stderr

    sys.stdout = _TeeStream(sys.stdout, logfile)
    sys.stderr = _TeeStream(sys.stderr, logfile)

    atexit.register(_close_log_file)
    return _LOG_FILE_PATH


