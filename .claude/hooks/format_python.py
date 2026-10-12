"""PostToolUse hook: format Python files Claude edits, so lint never fails on formatting."""

import json
import subprocess
import sys

payload = json.load(sys.stdin)
path = (payload.get("tool_input") or {}).get("file_path", "")
if path.endswith(".py"):
    subprocess.run(["uv", "run", "ruff", "format", "--quiet", path], check=False)
