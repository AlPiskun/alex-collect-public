#!/bin/sh
# ===========================================================================
#  Alex Collect Control Panel - Linux installer (per-user, no root)
# ===========================================================================
#    ./install-linux.sh            install to ~/.local/share/AlexCollect
#    ./install-linux.sh --remove   remove the shortcuts (user data is kept)
#    ./install-linux.sh --purge    remove EVERYTHING including your data
#
#  Installs the app, a Start-menu/desktop entry ("Alex Collect") and the
#  icon for the current user. Needs python3 + tkinter at run time
#  (Debian/Ubuntu: sudo apt install python3 python3-tk).
# ===========================================================================
set -e
SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST="${HOME}/.local/share/AlexCollect"
APPS="${HOME}/.local/share/applications"
ICONS="${HOME}/.local/share/icons/hicolor/256x256/apps"

if [ "$1" = "--purge" ]; then
    rm -f "$APPS/alexcollect.desktop" "$ICONS/alexcollect.png"
    rm -rf "$DEST"
    echo "Alex Collect removed completely (including your data)."
    exit 0
fi
if [ "$1" = "--remove" ]; then
    rm -f "$APPS/alexcollect.desktop" "$ICONS/alexcollect.png"
    echo "Shortcuts removed."
    echo "Your data and the program stay in: $DEST"
    echo "(delete that folder too with:  $0 --purge)"
    exit 0
fi

for need in app/gui.py README.md; do
    if [ ! -f "$SRC/$need" ]; then
        echo "ERROR: run this script from the repo root (next to README.md)."
        exit 1
    fi
done

mkdir -p "$DEST" "$APPS" "$ICONS"
cp -R "$SRC/app"          "$DEST/"
cp -R "$SRC/docs"         "$DEST/" 2>/dev/null || true
cp -f "$SRC/README.md" "$SRC/LICENSE" "$SRC/requirements.txt" "$DEST/" 2>/dev/null || true
find "$DEST" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
chmod +x "$DEST/app/alexcollect.sh"

cp -f "$SRC/app/icon-256.png" "$ICONS/alexcollect.png"

cat > "$APPS/alexcollect.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=Alex Collect
Comment=Card seller's control panel - pipeline, sold checklist, photos
Exec=$DEST/app/alexcollect.sh %F
Icon=alexcollect
Terminal=false
Categories=Office;
StartupWMClass=Alex Collect
DESKTOP

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS" 2>/dev/null || true
fi

echo
echo "  Installed for $USER -> $DEST"
echo "  Look for 'Alex Collect' in your applications menu"
echo "  (you may need to log out/in once on some desktops)."
echo
echo "  Needs python3 + tkinter; check with:"
echo "      $DEST/app/alexcollect.sh"
echo
echo "  Remove later with:  $0 --remove   (keeps your data)"
