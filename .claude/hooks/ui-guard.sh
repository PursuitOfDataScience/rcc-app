#!/usr/bin/env bash
# Say something the moment an edit repaints the app.
#
# `tests/test_palette.py` catches a repaint at `pytest` time, and CI catches it at
# review time. Both are after the fact: the change is written, the reasoning that
# produced it is gone, and what comes back is a failing assertion rather than "you
# just turned the send button pink." This runs the same check the instant one of the
# three files that decide how the app looks is edited, and hands the drift straight
# back to whoever made the edit, while they still know why they made it.
#
# Wired up in .claude/settings.json as a PostToolUse hook on Edit/Write/MultiEdit.
# Exit 2 is the code that feeds stderr back to the model rather than to a log.
#
# On the interpreter: `python3` on this cluster is 3.6.8 and has no `tomllib`, and
# there is no `jq`. A hook written the obvious way would exit non-zero on its own
# plumbing, be wrapped in `|| true` to quieten it, and then pass forever. So the
# interpreter is searched for, and NOT finding one is reported rather than swallowed —
# a guard that silently turns itself off is worse than no guard, which is the whole
# lesson this file exists to encode.
set -uo pipefail

payload=$(cat)
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)

find_python() {
    local candidate
    for candidate in \
        "${CONDA_PREFIX:-}/bin/python" \
        "/software/python-miniforge-25.3.0-el8-x86_64/envs/AI/bin/python" \
        "$(command -v python3 2>/dev/null || true)" \
        "$(command -v python 2>/dev/null || true)"
    do
        [ -n "$candidate" ] && [ -x "$candidate" ] || continue
        if "$candidate" -c 'import tomllib' 2>/dev/null; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

python_bin=$(find_python) || python_bin=""

# Any python parses the payload; only the check itself needs tomllib.
reader=${python_bin:-$(command -v python3 2>/dev/null || true)}
[ -n "$reader" ] || exit 0

edited=$(printf '%s' "$payload" | "$reader" -c '
import json, sys
try:
    event = json.load(sys.stdin)
except Exception:
    sys.exit(0)
data = event.get("tool_input") or {}
response = event.get("tool_response") or {}
path = data.get("file_path") or (response.get("filePath") if isinstance(response, dict) else "")
print(path or "")
' 2>/dev/null) || exit 0

case "$edited" in
    */static/app.css|*/static/app.js|*/.streamlit/config.toml) ;;
    *) exit 0 ;;
esac

if [ -z "$python_bin" ]; then
    echo "ui-guard: edited $edited, but found no Python with tomllib, so the palette" >&2
    echo "check did NOT run. Activate the env and run it by hand before trusting this" >&2
    echo "edit:  source /software/python-miniforge-25.3.0-el8-x86_64/bin/activate AI" >&2
    echo "       python tools/palette_check.py" >&2
    exit 2
fi

drift=$("$python_bin" "$repo/tools/palette_check.py" 2>&1) && exit 0

{
    echo "ui-guard: that edit changed how the app looks."
    echo
    printf '%s\n' "$drift"
    echo
    echo "If the change was asked for, accept it deliberately:"
    echo "  python tools/palette_check.py --update"
    echo "and commit tools/palette_baseline.json with the change. If it was not asked"
    echo "for, say so and put it back — do not update the baseline to silence this."
} >&2
exit 2
