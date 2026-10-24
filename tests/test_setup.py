
from pathlib import Path

def test_sdx_package_exists():
    assert Path("sdx/__init__.py").is_file()

def test_requirements_file_exists():
    assert Path("requirements.txt").is_file()
