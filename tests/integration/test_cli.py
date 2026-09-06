import subprocess
import sys


def test_help_and_invalid_configuration(tmp_path):
    help_result = subprocess.run(
        [sys.executable, "-m", "build_skills", "--help"], capture_output=True, text=True
    )
    assert help_result.returncode == 0
    result = subprocess.run(
        [sys.executable, "-m", "build_skills", "doctor", "--config", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
