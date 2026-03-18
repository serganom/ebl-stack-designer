#!/bin/sh
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP="$SCRIPT_DIR/ebl_stack_designer.py"

if [ -x /opt/homebrew/bin/python3.13 ]; then
  exec /opt/homebrew/bin/python3.13 "$APP"
fi

if [ -x /opt/homebrew/bin/python3.12 ]; then
  exec /opt/homebrew/bin/python3.12 "$APP"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 "$APP"
fi

echo "Python 3 not found."
echo "Install Python with tkinter support, then run:"
echo "  python3 \"$APP\""
exit 1

