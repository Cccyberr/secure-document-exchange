"""Milestone 0 setup checks.

These tests confirm the environment is ready. They do NOT test any
project cryptography (none exists yet). Run with:  python -m pytest
"""

import sys
from importlib.metadata import version
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_python_version_is_supported():
    assert sys.version_info >= (3, 10), (
        f"Python 3.10+ required, found {sys.version.split()[0]}"
    )


def test_running_inside_virtual_environment():
    assert sys.prefix != sys.base_prefix, (
        "Not inside a virtual environment. Activate .venv first."
    )


def test_dependencies_are_installed():
    for package in ("flask", "cryptography", "pytest"):
        assert version(package), f"{package} is not installed"


def test_cryptography_modules_import():
    # Import only. No keys are generated and nothing is encrypted.
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
    from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: F401
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401


def test_flask_serves_a_request():
    from flask import Flask

    app = Flask("setup_check")

    @app.get("/ping")
    def ping():
        return "ok"

    response = app.test_client().get("/ping")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_project_package_is_importable():
    import sdx  # noqa: F401


def test_gitignore_keeps_keys_out_of_git():
    lines = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for required in ("keys/", "*.pem", ".venv/", "trust_store.json"):
        assert required in lines, f".gitignore is missing '{required}'"
