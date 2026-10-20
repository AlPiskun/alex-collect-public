#!/bin/sh
# ===========================================================================
#  START Alex Collect - open the Control Panel from the repo root (Linux)
# ===========================================================================
#  ./start-alexcollect.sh [scans...]   (scans pre-fill the pipeline dialog)
# ===========================================================================
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$DIR/app/alexcollect.sh" "$@"
