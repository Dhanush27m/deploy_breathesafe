"""Claude Code PostToolUse hook: lint the file that was just written/edited.

- backend/**/*.py         -> ruff check --fix (auto-fixes, reports what remains)
- frontend/src/**/*.js(x) -> eslint --fix

If problems remain after auto-fix, they are fed back to Claude via
additionalContext so it can fix them immediately. Never blocks the edit.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def lint(file_path: str):
    p = Path(file_path)
    try:
        rel = p.resolve().relative_to(ROOT)
    except (ValueError, OSError):
        return None
    parts = rel.parts

    if p.suffix == ".py" and parts[0] == "backend":
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--fix", str(p)],
            capture_output=True, text=True, cwd=ROOT,
        )
        if r.returncode != 0:
            return (r.stdout + r.stderr).strip()

    elif p.suffix in (".js", ".jsx") and parts[:2] == ("frontend", "src"):
        eslint = ROOT / "frontend" / "node_modules" / "eslint" / "bin" / "eslint.js"
        if eslint.exists():
            r = subprocess.run(
                ["node", str(eslint), "--fix", str(p)],
                capture_output=True, text=True, cwd=ROOT / "frontend",
            )
            if r.returncode != 0:
                return (r.stdout + r.stderr).strip()
    return None


def main():
    try:
        # parse from the first "{": PowerShell pipes prepend BOM bytes that
        # Python may decode as junk chars, which json.loads rejects
        raw = sys.stdin.read()
        payload = json.loads(raw[raw.index("{"):])
    except Exception:
        return
    tool_input = payload.get("tool_input") or {}
    fp = tool_input.get("file_path")
    if not fp:
        return
    problems = lint(fp)
    if problems:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    "Lint found problems in the file you just edited - fix them now:\n"
                    + problems[-3000:]
                ),
            }
        }))


if __name__ == "__main__":
    main()
