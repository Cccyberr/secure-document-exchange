"""Print the environment details each member reports for Milestone 0.

Run with:  python check_setup.py
It changes nothing and creates no files.
"""

import platform
import sys
from importlib.metadata import PackageNotFoundError, version


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "NOT INSTALLED"


def main() -> None:
    in_venv = sys.prefix != sys.base_prefix
    print(f"Operating system : {platform.system()} {platform.release()}")
    print(f"Python           : {sys.version.split()[0]}")
    print(f"Virtual env      : {'yes' if in_venv else 'NO - activate .venv first'}")
    for name in ("flask", "cryptography", "pytest"):
        print(f"{name:<17}: {package_version(name)}")
    try:
        from cryptography.hazmat.backends.openssl.backend import backend

        print(f"OpenSSL (bundled): {backend.openssl_version_text()}")
    except Exception as exc:  # report, don't crash
        print(f"OpenSSL (bundled): could not read ({type(exc).__name__})")


if __name__ == "__main__":
    main()
