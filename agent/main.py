"""
Bank Statement Extraction Agent
Streams MiMo-V2.5-Pro with reasoning_effort=high.
Investigates PDF, extracts transactions, exports XLSX, verifies output.
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

from .system_prompt import SYSTEM_PROMPT
from .tools.read_skills import read_skills_doc

# Load .env if it exists
load_dotenv(Path(__file__).parent.parent / ".env")


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_skills_doc",
            "description": (
                "Read a skills documentation file to learn how to use a library or pattern. "
                "skill='pdf'   → pdfplumber, pypdf, OCR, text extraction. "
                "skill='excel' → openpyxl formatting, colors, multi-sheet workbooks, "
                "                daily summaries, credit/debit breakdowns. "
                "Call with skill='excel' before writing any formatted XLSX output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "enum": ["pdf", "excel"],
                        "description": "Which skill doc to read: 'pdf' or 'excel'",
                    }
                },
                "required": ["skill"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Write and execute any Python script using the project venv. "
                "Available libraries: pdfplumber, pandas, openpyxl, pypdf. "
                "Working directory: /home/ubuntu/Bankstatement/. "
                "Use this to: inspect the PDF structure, extract text/tables, "
                "parse transactions, write the output XLSX file to the exact "
                "path given in the user message, and verify the results. "
                "Returns stdout, stderr, and exit_code. If exit_code != 0, read stderr "
                "and fix the error before retrying. Write complete, runnable scripts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Python script to execute",
                    },
                    "description": {
                        "type": "string",
                        "description": "One line describing what this script does",
                    },
                },
                "required": ["code", "description"],
            },
        },
    },
]

PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "xiaomi/mimo-v2.5-pro",
        "env_key": "OPENROUTER_API_KEY",
        # reasoning_effort via OpenRouter's extra_body
        "extra_body": {"reasoning": {"effort": "high"}},
    },
    "deepinfra": {
        "base_url": "https://api.deepinfra.com/v1/openai",
        "model": "XiaomiMiMo/MiMo-V2.5-Pro",
        "env_key": "DEEPINFRA_API_KEY",
        # DeepInfra passes reasoning_effort at top level
        "extra_body": {"reasoning_effort": "high"},
    },
    "xiaomi": {
        "base_url": "https://api.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "env_key": "XIAOMI_MIMO_API_KEY",
        # Xiaomi official uses chat_template_kwargs for vLLM
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
    },
    "xiaomi-tokenplan": {
        "base_url": os.environ.get("XIAOMI_MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
        "model": "mimo-v2.5-pro",
        "env_key": "XIAOMI_MIMO_API_KEY",
        # Xiaomi Token Plan API (reasoning_effort support)
        "extra_body": {"reasoning_effort": "high"},
    },
}


class BankStatementAgent:
    def __init__(
        self,
        api_key: str = None,
        provider: str = None,
        base_url: str = None,
        model: str = None,
    ):
        provider = provider or os.environ.get("MIMO_PROVIDER", "openrouter")
        preset = PROVIDERS.get(provider, PROVIDERS["openrouter"])

        resolved_key = (
            api_key
            or os.environ.get(preset["env_key"])
            or os.environ.get("MIMO_API_KEY")
        )
        self.client = OpenAI(
            api_key=resolved_key,
            base_url=base_url or preset["base_url"],
        )
        self.model = model or preset["model"]
        self.extra_body = preset.get("extra_body", {})
        self.max_turns = 15
        self.state = {
            "skills_loaded": False,
            "trace": [],
        }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract(self, pdf_path: str, output_path: str = None, status_callback=None) -> dict:
        pdf_path = str(Path(pdf_path).resolve())
        if output_path is None:
            output_path = str(Path(pdf_path).with_suffix(".xlsx"))
        xlsx_path = output_path

        print(f"\n[Agent] Starting for: {pdf_path}")
        print(f"[Agent] Model: {self.model}  (reasoning_effort=high, streaming)")
        print(f"[Agent] Excel output: {xlsx_path}")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Extract all transactions from this bank statement PDF "
                    f"and export to Excel.\n"
                    f"PDF: {pdf_path}\n"
                    f"Excel Output: {xlsx_path}"
                ),
            },
        ]

        stop_without_output = 0  # how many times agent stopped but produced no files

        for turn in range(self.max_turns):
            print(f"\n{'─'*60}")
            print(f"[Turn {turn + 1}]")

            finish_reason, full_content, tool_calls = self._stream_turn(messages, status_callback=status_callback)

            self.state["trace"].append(
                {"turn": turn + 1, "finish_reason": finish_reason}
            )

            # ── Tool calls ──────────────────────────────────────────────
            # Also handle finish_reason="length" when tool calls were already
            # complete before the content response hit the token limit.
            if tool_calls and finish_reason in ("tool_calls", "length"):
                assistant_msg = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in tool_calls.values()
                    ],
                }
                if full_content:
                    assistant_msg["content"] = full_content
                messages.append(assistant_msg)

                for tc in tool_calls.values():
                    print(f"\n  → Tool: {tc['name']}")
                    try:
                        inputs = json.loads(tc["arguments"] or "{}")
                    except json.JSONDecodeError:
                        inputs = {}
                    result = self._execute_tool(tc["name"], inputs)
                    if status_callback and tc["name"] == "run_python":
                        status_callback("tool", {
                            "tool": tc["name"],
                            "desc": inputs.get("description", ""),
                            "exit": result.get("exit_code", 0),
                            "preview": (result.get("stdout") or "")[:200],
                        })
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result),
                        }
                    )
                continue

            # ── Hit token limit mid-response — continue the loop ────────
            if finish_reason == "length" and not tool_calls:
                # Model was cut off while reasoning, no tool call was emitted.
                # Append partial response and prompt it to act.
                if full_content:
                    messages.append({"role": "assistant", "content": full_content})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your response was cut off. Write and run the Python script now — "
                        "stop planning, use run_python to execute the extraction."
                    ),
                })
                print("  [harness] response cut off (length) — prompting to continue")
                continue

            # ── End turn ────────────────────────────────────────────────
            if finish_reason in ("stop", "end_turn", "length"):
                outputs = self._check_outputs(xlsx_path)
                print(f"\n{'═'*60}")
                if outputs["xlsx_exists"]:
                    print(f"[Agent] ✅ Completed — {outputs['xlsx_rows']} transactions")
                    print(f"[Agent]    XLSX: {xlsx_path}")
                    return {
                        "status": "completed",
                        "xlsx_path": xlsx_path,
                        "xlsx_rows": outputs["xlsx_rows"],
                        "raw_response": full_content,
                        "trace": self.state["trace"],
                    }
                # Agent stopped but produced no file — give environmental feedback
                # and let it continue (Anthropic: ground truth from environment at each step)
                stop_without_output += 1
                if stop_without_output >= 2:
                    print("[Agent] ⚠️  Stopped twice without output — giving up.")
                    return {
                        "status": "completed_no_output",
                        "raw_response": full_content,
                        "trace": self.state["trace"],
                    }
                print(f"  [harness] no output found (attempt {stop_without_output}) — prompting to act")
                messages.append({"role": "assistant", "content": full_content or "..."})
                messages.append({
                    "role": "user",
                    "content": (
                        f"No Excel file was found at {xlsx_path}. "
                        "Use run_python to write the Excel file now. "
                        "Do not describe what you will do — call run_python immediately."
                    ),
                })
                continue

        outputs = self._check_outputs(xlsx_path)
        if outputs["xlsx_exists"]:
            print(f"\n[Agent] ✅ Max turns reached but XLSX exists — {outputs['xlsx_rows']} rows")
            return {
                "status": "completed",
                "xlsx_path": xlsx_path,
                "xlsx_rows": outputs["xlsx_rows"],
                "raw_response": "",
                "trace": self.state["trace"],
            }
        return {
            "status": "failed",
            "reason": "max_turns_reached",
            "trace": self.state["trace"],
        }

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    def _stream_turn(self, messages: list, status_callback=None) -> tuple[str, str, dict]:
        """
        Stream one API call.
        Returns (finish_reason, full_content, tool_calls_map).
        Prints thinking tokens in dim color and response text normally.
        """
        THINK_OPEN  = "\033[2m"   # dim  — thinking
        THINK_CLOSE = "\033[0m"   # reset
        RESP_COLOR  = "\033[0m"   # normal

        stream = self.client.chat.completions.create(
            model=self.model,
            max_tokens=32768,
            tools=TOOLS,
            tool_choice="auto",
            stream=True,
            extra_body=self.extra_body,
            messages=messages,
        )

        full_content = ""
        tool_calls: dict[int, dict] = {}  # index → {id, name, arguments}
        finish_reason = "stop"
        in_think_tag = False

        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta

            # ── Text content (may contain <think>...</think>) ───────────
            if delta.content:
                text = delta.content
                full_content += text
                if status_callback:
                    status_callback("token", {"text": text, "is_thinking": in_think_tag})

                # colorize <think> blocks inline as they stream
                while text:
                    if not in_think_tag:
                        tag_start = text.find("<think>")
                        if tag_start == -1:
                            sys.stdout.write(RESP_COLOR + text)
                            sys.stdout.flush()
                            text = ""
                        else:
                            # print everything before <think>
                            before = text[:tag_start]
                            if before:
                                sys.stdout.write(RESP_COLOR + before)
                            sys.stdout.write(THINK_OPEN + "<think>")
                            sys.stdout.flush()
                            in_think_tag = True
                            text = text[tag_start + len("<think>"):]
                    else:
                        tag_end = text.find("</think>")
                        if tag_end == -1:
                            sys.stdout.write(text)
                            sys.stdout.flush()
                            text = ""
                        else:
                            before = text[:tag_end]
                            if before:
                                sys.stdout.write(before)
                            sys.stdout.write("</think>" + THINK_CLOSE)
                            sys.stdout.flush()
                            in_think_tag = False
                            text = text[tag_end + len("</think>"):]

            # ── Reasoning tokens ──────────────────────────────────────
            # Xiaomi Token Plan returns reasoning_content
            # OpenRouter returns reasoning
            reasoning_text = None
            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                reasoning_text = delta.reasoning_content
            elif hasattr(delta, "reasoning") and delta.reasoning:
                reasoning_text = delta.reasoning

            if reasoning_text:
                sys.stdout.write(THINK_OPEN + reasoning_text + THINK_CLOSE)
                sys.stdout.flush()

            # ── Tool call deltas ────────────────────────────────────────
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.id:
                        tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function and tc_delta.function.name:
                        tool_calls[idx]["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        tool_calls[idx]["arguments"] += tc_delta.function.arguments

        if in_think_tag:
            sys.stdout.write(THINK_CLOSE)   # reset if stream ended mid-tag
        sys.stdout.write("\n")
        sys.stdout.flush()

        return finish_reason, full_content, tool_calls

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, inputs: dict) -> dict:
        if name == "read_skills_doc":
            skill = inputs.get("skill", "pdf")
            result = read_skills_doc(skill=skill)
            self.state["skills_loaded"] = result.get("ok", False)
            if result["ok"]:
                print(f"     Skill '{skill}' loaded ({result['size_chars']} chars)")
                return {
                    "ok": True,
                    "skill": skill,
                    "path": result["path"],
                    "size_chars": result["size_chars"],
                    "full_content": result["content"],
                }
            return result

        if name == "run_python":
            from .tools.run_python import run_python
            desc = inputs.get("description", "")
            code = inputs.get("code", "")
            print(f"     Running: {desc}")
            result = run_python(code=code, description=desc)
            status = "✅" if result["ok"] else "❌"
            stdout_preview = result["stdout"][:200].replace("\n", " ↵ ")
            print(f"     {status} exit={result['exit_code']}  out: {stdout_preview}")
            return result

        return {"ok": False, "error": f"Unknown tool: {name}"}

    # ------------------------------------------------------------------
    # Output verification
    # ------------------------------------------------------------------

    def _check_outputs(self, xlsx_path: str) -> dict:
        xlsx_p = Path(xlsx_path)
        xlsx_rows = 0
        if xlsx_p.exists() and xlsx_p.stat().st_size > 100:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(xlsx_p)
                ws = wb.active
                xlsx_rows = ws.max_row - 1  # subtract header
            except Exception:
                xlsx_rows = -1
        return {
            "xlsx_exists": xlsx_p.exists() and xlsx_p.stat().st_size > 100,
            "xlsx_rows": max(xlsx_rows, 0),
        }
