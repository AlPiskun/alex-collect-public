#!/bin/sh
# ===========================================================================
#  Alex Collect Control Panel - Linux launcher
# ===========================================================================
#  Double-click in a file manager, or:
#      ./alexcollect.sh                      open the Control Panel
#      ./alexcollect.sh front.png back.png   open the pipeline dialog with
#                                            the scans pre-filled
#  Needs python3 with tkinter (Debian/Ubuntu: sudo apt install python3-tk)
#  and Pillow for the image tools (python3 -m pip install --user Pillow).
# ===========================================================================
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    echo "ERROR: no python3 found. Install it (e.g. sudo apt install python3 python3-tk)."
    exit 1
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "ERROR: tkinter is missing (the window toolkit)."
    echo "  Debian/Ubuntu:  sudo apt install python3-tk"
    echo "  Fedora:         sudo dnf install python3-tkinter"
    exit 1
fi

if ! "$PY" -c "import PIL" >/dev/null 2>&1; then
    echo "NOTE: the image libraries are not installed yet."
    echo "      Installing now:  $PY -m pip install --user 'Pillow>=10' requests pandas openpyxl"
    "$PY" -m pip install --user "Pillow>=10" requests pandas openpyxl || \
        echo "  (could not install automatically - run the pip line above)"
fi

exec "$PY" -u "$DIR/gui.py" "$@"
