# Auto-Docs: Automated Documentation Generator

Auto-Docs is a FastAPI-based service designed to automate the process of analyzing code repositories, detecting missing docstrings, generating high-quality documentation using AI, and setting up Sphinx documentation with CI/CD integration. It supports Python, JavaScript, TypeScript, and MATLAB codebases, making it a versatile tool for modern development teams.

---

## Key Features

- **Repository Analysis:**
  - Scans remote repositories (GitHub/GitLab) for supported source files.
  - Detects missing or incomplete docstrings in code blocks and modules.

- **AI-Powered Docstring Generation:**
  - Uses OpenAI to generate concise, context-aware docstrings for code blocks.
  - Outputs suggested docstrings and analysis reports.

- **Sphinx Documentation Automation:**
  - Prepares and updates Sphinx configuration for the project.
  - Integrates with CI/CD pipelines (GitLab, GitHub Actions) for automated documentation builds.

- **Logging and Reporting:**
  - Centralized logging for all operations.
  - Generates CSV and text reports for docstring analysis and suggestions.

---

![Project Architecture](data/autodoc_architecture.png)

## Project Structure

```text
.
├── docker-compose.yaml
├── Dockerfile
├── README.md
├── pyproject.toml
├── log/
│   └── app_<timestamp>.log
├── src/
│   ├── main.py                # FastAPI app entry point
│   ├── config/
│   │   ├── config.py          # Sphinx and CI/CD configuration
│   │   └── log_config.py      # Logging configuration
│   ├── files/
│   │   ├── block_analysis.csv # Analysis report
│   │   └── suggested_docstring.txt # AI-generated docstrings
│   ├── models/
│   │   └── repo_request.py    # Request models
│   ├── router/
│   │   └── router.py          # API route definitions
│   ├── services/
│   │   ├── doc_services.py    # Docstring analysis and generation
│   │   └── sphinx_services.py # Sphinx setup and automation
├── tests/
│   └── ...                    # Automated tests
│   └── utils/
│       ├── code_block_extraction.py
│       ├── docstring_generation.py
│       ├── docstring_validation.py
│       ├── generate_yml_content.py
│       ├── git_utils.py
│       └── update_conf_content.py
```

---

## How It Works

1. **User submits a repository URL and access token via the API.**
2. **The service clones the repository and scans for supported source files.**
3. **Each file is analyzed for missing or incomplete docstrings.**
4. **OpenAI is used to generate suggested docstrings for undocumented code blocks.**
5. **Sphinx configuration and CI/CD pipeline files are generated or updated.**
6. **Results (suggested docstrings, analysis CSV, logs) are saved in the `files/` and `log/` directories.**

---

## Main Services & Modules

- **Docstring Analysis & Generation:**
  - `src/services/doc_services.py`, `src/utils/docstring_generation.py`, `src/utils/docstring_validation.py`
- **Sphinx Documentation Setup:**
  - `src/services/sphinx_services.py`, `src/utils/update_conf_content.py`
- **Repository & CI/CD Integration:**
  - `src/utils/git_utils.py`, `src/utils/generate_yml_content.py`
- **API Routing:**
  - `src/router/router.py`
- **Configuration & Logging:**
  - `src/config/config.py`, `src/config/log_config.py`

---

## Quick Start

### Prerequisites

- Python 3.11+
- OpenAI API Key
- (Optional) Docker

### Installation

```sh
# Clone the repository
git clone <your-repo-url>
cd auto-docs

# Create a virtual environment and sync local development dependencies
uv venv
source .venv/bin/activate
uv sync --group dev --no-install-project
```

### Environment Variables (.env Setup)

Create a `.env` file in the project root directory to securely store sensitive configuration values. At minimum, the following variables are required:

```env
OPENAI_API_KEY=your-openai-api-key
# (Optional) For CI/CD integration with GitLab:
CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token
# (Add any other required environment variables here)
```

**Note:** Never commit your `.env` file to version control. The application will automatically load these variables at startup.

### Running the Service

```sh
# Start the FastAPI server
uv run uvicorn main:app --app-dir src --reload
```

- The API will be available at: http://localhost:8000
- Interactive docs: http://localhost:8000/docs

### Using Docker

```sh
docker-compose up --build
```

### Local Checks

```sh
# Run tests
uv run pytest

# Run lint checks
uv run ruff check src tests

# Build docs
uv sync --group docs --no-install-project
uv run sphinx-build -W -b html docs/source docs/build/html
```

---

## API Usage

### `POST /generate`

Analyze a repository and set up documentation.

**Request Body Example:**

```json
{
  "provider": "github" | "gitlab",
  "repo_url": "<user/repo or group/project>",
  "token": "<access token>",
  "branch": "<branch name>"
}
```

**Response:**

- `status`: "success"
- `sphinx_setup_created`: true/false
- `Docstring_analysis`: List of files and blocks with/without docstrings

---

## Output Files

- `src/files/suggested_docstring.txt`: AI-generated docstrings
- `src/files/block_analysis.csv`: Analysis report
- `log/app_<timestamp>.log`: Log files

---

## Limitations

- **AI Docstring Quality:** Generated docstrings depend on the quality/context of the code and OpenAI's model; manual review is recommended.
- **Private Repositories:** Requires valid access tokens for private repositories; token permissions must allow cloning and reading.
- **GitHub Actions Integration:**
  - Currently, there is **no support for GitHub Actions**. The system does **not** generate, commit, or trigger any workflow files for GitHub repositories.
  - As a result, **automated Sphinx documentation setup is also missing for GitHub repositories**. Only GitLab CI/CD pipeline creation and Sphinx automation are implemented and supported at this time.

---

## Improvements

- **Web UI Dashboard:** Build a frontend for easier project management, visualization, and configuration.
- **Enhanced Sphinx Integration:** Support for custom Sphinx themes, plugins, and advanced configuration options.
- **Parallel Processing:** Optimize for faster analysis of large repositories using concurrency.
- **Pluggable AI Models:** Allow users to select or bring their own LLMs for docstring generation from Web UI.

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/foo`)
3. Commit your changes
4. Push to the branch
5. Open a pull request

---
