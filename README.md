# AUTODOC

A FastAPI-based service that analyzes code repositories (GitHub/GitLab), detects missing docstrings in Python, JavaScript, TypeScript, and MATLAB files, generates suggested docstrings using OpenAI, and sets up Sphinx documentation with CI/CD integration.

---

## Features

- **Repository Analysis:**  
  Scans a remote repository for supported source files and analyzes each for missing docstrings.

- **Docstring Generation:**  
  Uses OpenAI to generate concise docstrings for code blocks or modules missing documentation.

- **Sphinx Documentation Setup:**  
  Automatically prepares Sphinx configuration and CI/CD pipeline files for documentation builds.

- **CI/CD Integration:**  
  Supports GitLab pipelines (and placeholder for GitHub Actions) to automate documentation builds.

- **Logging:**  
  Centralized logging with per-run log files in the `log/` directory.

---

## Project Structure

```
.
├── .gitlab
│   ├── ci
│       └── build.yml
│   ├── main.py
│   ├── router/
│   │   └── router.py
│   ├── services/
│   │   ├── doc_services.py
│   │   └── sphinx_services.py
│   ├── utils/
│   │   ├── code_block_extraction.py
│   │   ├── docstring_generation.py
│   │   ├── docstring_validation.py
│   │   ├── generate_yml_content.py
│   │   ├── git_utils.py
│   │   └── update_conf_content.py
│   ├── config/
│   │   ├── config.py
│   │   └── log_config.py
│   └── models/
│       └── repo_request.py
├── files/           # Output and suggested docstrings
├── log/             # Log files
├── requirements.txt
├── .gitlab-ci.yml
├── Dockerfile
├── docker-compose.yaml
└── README.md
```

---

## Setup

### Prerequisites

- Python 3.8+
- [OpenAI API Key](https://platform.openai.com/)
- (Optional) Docker

### Installation

1. **Clone the repository:**
   ```sh
   git clone <your-repo-url>
   cd auto-docs
   ```

2. **Install dependencies:**
   ```sh
   pip install -r requirements.txt
   ```

3. **Set environment variables:**
   - Create a `.env` file in the root directory:
     ```
     OPENAI_API_KEY=your-openai-key
     CI_TRIGGER_PIPELINE_TOKEN=your-gitlab-trigger-token
     ```
   - (Optional) Set other variables as needed.

---

## Usage

### Run Locally

```sh
python src/main.py
```

- The API will be available at [http://localhost:8000](http://localhost:8000)
- Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Docker

```sh
docker-compose up --build
```

---

## API Endpoints

### `POST /generate`

Analyze a repository and set up documentation.

**Request Body:**
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

## Output

- **Suggested docstrings:**  
  Written to [`files/suggested_docstring.txt`](files/suggested_docstring.txt)
- **Block analysis CSV:**  
  Written to [`files/block_analysis.csv`](files/block_analysis.csv)
- **Logs:**  
  Written to [`log/app_<timestamp>.log`](log/)

---

## Configuration

See [`src/config/config.py`](src/config/config.py) for Sphinx and CI/CD related constants.

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/foo`)
3. Commit your changes
4. Push to the branch
5. Open a pull request

---

## Authors

- SAKSHI GUPTA