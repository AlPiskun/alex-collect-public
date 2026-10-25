"""Small process-launching helpers shared by the GUI and its tools.

On Windows the control panel is started with ``pythonw`` so that it has no
console of its own. Every tool it runs is a console program, and Windows gives
such a child a brand-new console window when the parent has none - which shows
up as a stray DOS prompt sitting on the desktop until the tool finishes. The
tool's output still arrives through the pipe the GUI reads, so the window is
never needed.

Passing ``CREATE_NO_WINDOW`` keeps those children invisible. Nothing here has
any effect off Windows, where the flag does not exist.
"""
import os
import subprocess

# Python exposes this only on Windows; the value is fixed by the Win32 API.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def no_window_kwargs():
    """Extra ``Popen`` keyword arguments that hide a child console window.

    Returns ``{}`` on every platform that has no such windows to hide, so it is
    always safe to splat into ``subprocess.Popen(...)``.
    """
    if os.name == "nt":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}
