#!/bin/sh
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

exec "$SCRIPT_DIR/run_ebl_stack_designer.sh"
