#!/bin/sh
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP="$SCRIPT_DIR/ebl_stack_designer.py"

can_run_gui() {
  "$1" - <<'PY' >/dev/null 2>&1
import tkinter
PY
}

if [ -x /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 ] && can_run_gui /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; then
  exec /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 "$APP"
fi

if [ -x /opt/homebrew/bin/python3.13 ] && can_run_gui /opt/homebrew/bin/python3.13; then
  exec /opt/homebrew/bin/python3.13 "$APP"
fi

if [ -x /opt/homebrew/bin/python3.12 ] && can_run_gui /opt/homebrew/bin/python3.12; then
  exec /opt/homebrew/bin/python3.12 "$APP"
fi

if command -v python3 >/dev/null 2>&1 && can_run_gui python3; then
  exec python3 "$APP"
fi

echo "No Python with tkinter support was found."
echo "Working GUI interpreter detected on this Mac:"
echo "  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
echo
echo "If the app still does not start, run it directly:"
echo "  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \"$APP\""
exit 1
