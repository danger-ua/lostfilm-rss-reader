---
trigger: always_on
---

# 🐍 Python Project Governance & Workflow

## 📦 Dependency Management

* **Exclusive Provider:** Use the **`uv`** package manager for all operations. Do not use `pip`, `pipenv`, or `poetry`.
* **No Global Installations:** * Package installation to the global/system Python environment is **strictly prohibited**.
* Never use the `--system` flag with `uv` commands.


* **Lockfile Authority:** The `uv.lock` file is the single source of truth. It must be committed to version control and updated whenever dependencies change.

## 💻 Virtual Environment (VENV)

* **Mandatory Isolation:** All tests, applications, and scripts must execute within a project-specific virtual environment located at `.venv/`.
* **Contextual Execution:** Use `uv run <command>` to ensure the environment is automatically respected without requiring manual activation/deactivation cycles.
* **Dependency Addition:** * **Production:** `uv add <package>`
* **Development:** `uv add --dev <package>`



## 🛠 Quality & Standards

* **Linting & Formatting:** Use **Ruff** for fast, Rust-based linting and code formatting.
* `uv run ruff check .`
* `uv run ruff format .`


* **Static Analysis:** All code must be type-hinted and verified using `mypy` or `pyright`.
* **Test-Driven Execution:** Run the test suite exclusively via `uv run pytest`.

## 📂 Project Structure

Maintain a **`src/` layout** to ensure the package is properly built and tested in isolation:

```text
.
├── pyproject.toml      # Project metadata & uv config
├── uv.lock             # Deterministic lockfile
├── .python-version     # Target Python version for uv
├── src/                # Source code directory
│   └── my_project/     # Actual package
└── tests/              # Test suite

```

## 🚀 Common Command Reference

| Action | Command |
| --- | --- |
| **Initialize Project** | `uv init` |
| **Install All Dependencies** | `uv sync` |
| **Add Production Package** | `uv add <package>` |
| **Add Dev Tooling** | `uv add --dev <package>` |
| **Run Application** | `uv run python -m my_project` |
| **Run Unit Tests** | `uv run pytest` |

---

Would you like me to generate a **`pyproject.toml`** file that pre-configures these `uv` and `ruff` settings for your project?