# Sourced by the hooks: picks the project venv's Python when present.
# Falls back to the `py` launcher on Windows (never the Store alias stub), then to `python`.
if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v py >/dev/null 2>&1 && py -3 -c "import sys" >/dev/null 2>&1; then
    PY="py -3"
elif python -c "import sys" >/dev/null 2>&1; then
    PY="python"
else
    echo "hooks: no usable Python found; create .venv or install Python 3.13" >&2
    exit 1
fi
