import os
import tempfile
from pathlib import Path

# kigit's app data (sessions.json, 3D build times, logs) goes to a throwaway
# folder, never the real one: <tmp>/state/log, so its parent is <tmp>/state.
os.environ["KIGIT_LOG_DIR"] = str(Path(tempfile.mkdtemp(prefix="kigit-test-")) / "state" / "log")
# No real KiCad in the GUI tests (3D models and board pictures are faked
# where a test needs them): fast, and the same with or without KiCad.
os.environ["KIGIT_KEYRING"] = "off"  # never the real keyring
os.environ["KIGIT_LCSC"] = "off"  # no downloads from jlcparts
os.environ["KIGIT_KICAD_CLI"] = str(Path(tempfile.gettempdir()) / "no-kicad-cli-in-tests")

pytest_plugins = ["nicegui.testing.user_plugin"]
