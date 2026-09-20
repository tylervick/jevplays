"""Nothing importable without a ROM may drag in pyboy (and its SDL dependency).

Run in a subprocess: an earlier test in the same session may already have imported pyboy (any
ROM-backed test does), so importing in-process here could pass for the wrong reason.
"""

import subprocess
import sys


def test_no_pyboy_import_without_touching_the_emulator():
    code = (
        "import sys\n"
        "import jevplays.loop\n"
        "import jevplays.cli\n"
        "import jevplays.state.snapshot\n"
        "import jevplays.dashboard.server\n"
        "assert 'pyboy' not in sys.modules, sys.modules.keys()\n"
        "assert 'typesafe_sdk' not in sys.modules, sys.modules.keys()\n"
        "print('ok', end='')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok"
