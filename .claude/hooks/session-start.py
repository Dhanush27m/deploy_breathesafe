"""Claude Code SessionStart hook: load this project's work log into context.

Reads .claude/WORKLOG.md and feeds it to Claude as additionalContext so a new
terminal continues from where the last session ended, instead of starting cold.

Deliberately scoped to this project only: the path is derived from this file's
location, so it can never pick up another project's notes. Fails silently --
a missing or unreadable log should never block a session from starting.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKLOG = ROOT / ".claude" / "WORKLOG.md"

# Keep startup context bounded -- the log grows over time, but only the most
# recent material is worth paying context for.
MAX_CHARS = 12000


def main():
    try:
        sys.stdin.read()  # drain payload; we don't need anything from it
    except Exception:
        pass

    try:
        text = WORKLOG.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return

    if not text:
        return

    if len(text) > MAX_CHARS:
        # newest entries are at the top, so keep the head and drop old tail
        text = text[:MAX_CHARS].rstrip() + "\n\n[... older entries truncated ...]"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Work log for this project (.claude/WORKLOG.md) -- this is the "
                "continuing context from previous sessions. Treat it as an "
                "ongoing conversation, not a fresh start. Update it as decisions "
                "are made.\n\n" + text
            ),
        }
    }))


if __name__ == "__main__":
    main()
