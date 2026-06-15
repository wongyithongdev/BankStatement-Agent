"""
run_python — Code Execution Tool (Docker sandbox).
Runs agent-written scripts in an isolated container with no network access.
Falls back to venv subprocess if Docker is not available.
"""

import os
import subprocess
import tempfile
from pathlib import Path

_WORK_DIR      = Path(__file__).parent.parent.parent
_VENV_PYTHON   = _WORK_DIR / "venv" / "bin" / "python"
_OUTPUT_DIR    = Path(os.getenv("OUTPUT_DIR", "/tmp/bankstatement/outputs"))
_STDOUT_CAP    = 8000
_STDERR_CAP    = 2000
_SANDBOX_IMAGE = os.getenv("SANDBOX_IMAGE", "bankstatement-sandbox:latest")
_USE_DOCKER    = os.getenv("USE_DOCKER_SANDBOX", "true").lower() == "true"

# Cached at first call — Docker availability doesn't change at runtime
_docker_ok: bool | None = None


def _docker_available() -> bool:
    global _docker_ok
    if _docker_ok is None:
        try:
            subprocess.run(["docker", "info"], capture_output=True, timeout=5, check=True)
            _docker_ok = True
        except Exception:
            _docker_ok = False
    return _docker_ok


def run_python(code: str, description: str = "") -> dict:
    """
    Execute a Python script in a Docker sandbox (or venv fallback).
    Returns {ok, exit_code, stdout, stderr, description}.
    """
    import shutil

    tmp = None
    tmp_dir = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as f:
            f.write(code)
            tmp = Path(f.name)

        tmp_dir = tempfile.mkdtemp(prefix="bsagent_")

        if _USE_DOCKER and _docker_available():
            # Place script at /sandbox/script.py inside the container.
            # Mount _OUTPUT_DIR at the same host path so agent scripts can write
            # xlsx files there without remapping the path they receive.
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            script_in_tmp = Path(tmp_dir) / "script.py"
            shutil.copy(tmp, script_in_tmp)

            cmd = [
                "docker", "run", "--rm",
                "--memory=512m",
                "--cpus=1",
                "--network=none",
                "-v", f"{_WORK_DIR}:/workspace:ro",
                "-v", f"{tmp_dir}:/sandbox:ro",          # script, read-only
                "-v", f"{_OUTPUT_DIR}:{_OUTPUT_DIR}",     # output dir, writable, same path
                _SANDBOX_IMAGE,
                "python", "/sandbox/script.py",
            ]
            timeout = 60
        else:
            cmd = [str(_VENV_PYTHON), str(tmp)]
            timeout = 30

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_WORK_DIR),
        )

        stdout = result.stdout
        stderr = result.stderr

        if len(stdout) > _STDOUT_CAP:
            stdout = stdout[:_STDOUT_CAP] + f"\n... [truncated, {len(result.stdout)} total chars]"
        if len(stderr) > _STDERR_CAP:
            stderr = stderr[:_STDERR_CAP] + "\n... [truncated]"

        return {
            "ok": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "description": description,
        }

    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": "Execution timed out.",
            "description": description,
        }
    except Exception as e:
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Error running script: {e}",
            "description": description,
        }
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
