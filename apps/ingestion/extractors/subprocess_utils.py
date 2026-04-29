"""Subprocess utilities with guaranteed child-process cleanup.

Provides a drop-in replacement for subprocess.run that kills the entire
process group on timeout or error, preventing zombie Chromium processes
from Playwright extractions.
"""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


class SubprocessError(subprocess.CalledProcessError):
    """Wraps subprocess failures with consistent interface."""

    def __init__(
        self,
        returncode: int,
        cmd: list[str],
        output: str | None = None,
        stderr: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.timeout = timeout
        self.output = output
        self.stderr = stderr
        super().__init__(returncode, cmd, output=output, stderr=stderr)


class SubprocessTimeoutError(SubprocessError):
    """Raised when the subprocess times out and its process group is killed."""

    def __init__(
        self,
        cmd: list[str],
        timeout: float,
        output: str | None = None,
        stderr: str | None = None,
    ) -> None:
        self.timeout = timeout
        super().__init__(-1, cmd, output=output, stderr=stderr, timeout=timeout)


def _kill_process_group(pid: int) -> None:
    """Send SIGKILL to an entire process group.

    On Linux, os.killpg sends the signal to the process group. We try
    SIGTERM first for graceful shutdown, then SIGKILL after a short wait.
    """
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return

    # Brief grace period for Chromium to flush
    import time

    time.sleep(0.5)

    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def run_subprocess(
    cmd: list[str],
    *,
    timeout: float | None = None,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess | Any:
    """Run a subprocess with guaranteed child-process cleanup on timeout.

    Drop-in replacement for subprocess.run that uses start_new_session to
    create a new process group. On timeout, the entire process group is
    killed, preventing orphaned Chromium/Playwright processes.

    Args:
        cmd: Command and arguments (list of strings).
        timeout: Maximum execution time in seconds.
        check: Raise SubprocessError on non-zero return code.
        capture_output: Capture stdout and stderr.
        text: Return stdout/stderr as strings.
        **kwargs: Additional args passed to subprocess.Popen.

    Returns:
        subprocess.CompletedProcess-like object with returncode, stdout, stderr.

    Raises:
        SubprocessTimeoutError: On timeout (after killing process group).
        SubprocessError: On non-zero return code (if check=True).
    """
    # Merge kwargs with our required settings
    popen_kwargs: dict[str, Any] = {
        "start_new_session": True,
    }
    popen_kwargs.update(kwargs)

    if capture_output:
        popen_kwargs["stdout"] = subprocess.PIPE
        popen_kwargs["stderr"] = subprocess.PIPE

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            _kill_process_group(proc.pid)
            stdout_bytes, stderr_bytes = proc.communicate()

            if text:
                out_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
                err_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
            else:
                out_str = stdout_bytes
                err_str = stderr_bytes

            raise SubprocessTimeoutError(
                cmd,
                timeout or 0,
                output=out_str,
                stderr=err_str,
            ) from None

        returncode = proc.returncode

        if text:
            out_str = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
            err_str = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        else:
            out_str = stdout_bytes
            err_str = stderr_bytes

        if check and returncode != 0:
            raise SubprocessError(
                returncode,
                cmd,
                output=out_str,
                stderr=err_str,
            )

        # Build a CompletedProcess-like result for backward compatibility
        # We use a simple namespace so existing .stdout/.stderr/.returncode work
        result: Any = type(
            "CompletedProcess",
            (),
            {
                "returncode": returncode,
                "stdout": out_str,
                "stderr": err_str,
                "args": cmd,
            },
        )()
        return result

    except Exception:
        # Ensure process is dead on any unexpected error
        if "proc" in locals() and proc.poll() is None:
            _kill_process_group(proc.pid)
        raise
