"""
run_python — Code Execution Tool (Anthropic Code-First pattern)
Lets the agent write any Python script and execute it.
Returns stdout/stderr so the agent sees real output and can adapt.
"""

import subprocess
import tempfile
from pathlib import Path

_VENV_PYTHON = Path(__file__).parent.parent.parent / "venv" / "bin" / "python"
_WORK_DIR = Path(__file__).parent.parent.parent
_STDOUT_CAP = 8000
_STDERR_CAP = 2000


def run_python(code: str, description: str = "") -> dict:
    """
    Execute a Python script in the project venv.
    Returns {ok, exit_code, stdout, stderr, description}.
    """
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, dir="/tmp"
        ) as f:
            f.write(code)
            tmp = Path(f.name)

        result = subprocess.run(
            [str(_VENV_PYTHON), str(tmp)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_WORK_DIR),
        )

        stdout = result.stdout
        stderr = result.stderr

        # Cap to avoid flooding context
        truncated_stdout = len(stdout) > _STDOUT_CAP
        truncated_stderr = len(stderr) > _STDERR_CAP
        if truncated_stdout:
            stdout = stdout[:_STDOUT_CAP] + f"\n... [truncated, {len(result.stdout)} total chars]"
        if truncated_stderr:
            stderr = stderr[:_STDERR_CAP] + f"\n... [truncated]"

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
            "stderr": "Execution timed out after 30 seconds.",
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
