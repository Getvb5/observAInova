import subprocess
import sys


def test_application_imports_in_a_clean_python_process() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pci.main import app; assert app.title == 'ObservAInova'",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
