# Secure Document Exchange System

Hybrid cryptography (AES-256-GCM + RSA-OAEP) and digital signatures (RSA-PSS)
in a local Flask prototype. Educational project, not production software.

Current stage: **Milestone 0 (setup only)**. No cryptography is implemented yet.

---

## 1. Requirements

- Python **3.10 or newer** (3.12 or 3.13 recommended; the team should agree on one)
- Git
- A GitHub account with access to this repository

## 2. Setup on macOS

```bash
# 1. Check Python and Git
python3 --version
git --version            # if missing: xcode-select --install

# 2. Clone and enter the project
git clone https://github.com/<OWNER>/secure-doc-exchange.git
cd secure-doc-exchange

# 3. Create and activate the virtual environment
python3 -m venv .venv
source .venv/bin/activate          # prompt now starts with (.venv)

# 4. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 5. Verify
python check_setup.py
python -m pytest
```

## 3. Setup on Windows (PowerShell)

```powershell
# 1. Check Python and Git
py --version
git --version

# 2. Clone and enter the project
git clone https://github.com/<OWNER>/secure-doc-exchange.git
cd secure-doc-exchange

# 3. Create and activate the virtual environment
py -m venv .venv
.\.venv\Scripts\Activate.ps1       # prompt now starts with (.venv)

# 4. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 5. Verify
python check_setup.py
python -m pytest
```

Using Command Prompt instead of PowerShell? Activate with `.venv\Scripts\activate.bat`.

Every new terminal window needs the activation step again. Leave with `deactivate`.

## 4. Pinning versions

`requirements.txt` starts with version ranges. After the first successful install,
Member A runs `python -m pip show flask cryptography pytest`, replaces each line with
the exact installed version (`flask==X.Y.Z`), and opens a PR. After it merges, everyone runs
`python -m pip install -r requirements.txt` again. Only the three direct dependencies are
pinned, because a full `pip freeze` differs between macOS and Windows.

## 5. What is committed vs. local

| Committed to GitHub | Stays on each laptop only |
| --- | --- |
| Source code (`sdx/`, `app.py`, `init_keys.py`), `tests/`, `templates/`, `static/` | `.venv/` |
| `requirements.txt`, `pytest.ini`, `.gitignore`, `.gitattributes`, `README.md` | `keys/` (all private and public keys) |
| `docs/` (diagrams, screenshots, recorded test results) | `trust_store.json` |
| | `*.pem`, `*.sdx.json`, `.env`, caches |

Each laptop generates its own keys (Milestone 1). Packages made on one laptop can only be
opened on the same laptop, because the other laptops have different keys.

## 6. Team Git workflow

`main` must always work. Nobody commits to `main` directly.

```bash
git switch main
git pull
git switch -c a/keys-signing          # <member letter>/<short-topic>
# ...edit files...
git add <files you changed>
git commit -m "Add RSA-PSS sign and verify"
git push -u origin a/keys-signing
```

Then on GitHub: open a Pull Request into `main`, ask one teammate to review, merge after
approval, delete the branch, and everyone runs `git switch main` and `git pull`.

Before every commit, run `git status` and check that nothing from `keys/` or `.venv/` is listed.
