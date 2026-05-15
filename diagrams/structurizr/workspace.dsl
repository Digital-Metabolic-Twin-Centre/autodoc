workspace "Auto Doc Architecture" "Structurizr DSL model for the Auto Doc project." {

    !identifiers hierarchical

    model {
        user = person "User" "Developer, reviewer, or automation client invoking the Auto Doc API."

        github = softwareSystem "GitHub" "Source repository hosting, branch/file APIs, pull requests, and Pages publishing." "External"
        gitlab = softwareSystem "GitLab" "Source repository hosting and pipeline execution for GitLab-backed repositories." "External"
        openai = softwareSystem "OpenAI API" "Generates missing docstring suggestions." "External"
        pages = softwareSystem "GitHub Pages" "Hosts published static documentation built from reviewed branches." "External"
        gitlabCi = softwareSystem "GitLab CI/CD" "Runs GitLab pipeline jobs for generated documentation workflows." "External,CI"
        repoCi = softwareSystem "GitHub Actions" "Builds, tests, lint-checks, and publishes documentation for this Auto Doc repository." "External,CI"

        autodoc = softwareSystem "Auto Doc" "FastAPI service that analyses remote repositories, generates docstring suggestions, scaffolds Sphinx documentation, and publishes reviewed HTML." {

            api = container "FastAPI API Service" "Application entry point exposing endpoints." "Python 3.11, FastAPI, Uvicorn" "API" {

                router = component "API Router" "Defines HTTP endpoints and dispatches requests." "FastAPI APIRouter" "Routing"
                models = component "Request Models" "Validates request payloads." "Pydantic" "Model"
                analysis = component "Doc Analysis Service" "analyses repositories and extracts code blocks." "doc_services.py" "Service"
                sphinx = component "Sphinx Service" "Creates docs scaffolding and publishes reviewed HTML to GitHub Pages." "sphinx_services.py" "Service"
                pr = component "Docstring PR Service" "Creates GitHub pull requests containing Python docstring suggestions." "docstring_pr_services.py" "Service"
                git = component "Git Utilities" "Handles GitHub/GitLab API operations." "git_utils.py" "Utility"
                extractor = component "Code Extractor" "Extracts functions/classes from code." "code_block_extraction.py" "Utility"
                validation = component "Docstring Validation" "Checks docstring coverage and enriches missing entries." "docstring_validation.py" "Utility"
                generation = component "Docstring Generator" "Generates docstrings via OpenAI." "docstring_generation.py" "Utility"
                output = component "Output Utilities" "Handles repo-scoped logs and artifacts." "output_paths.py" "Utility"
                confupdate = component "Sphinx Config Updater" "Updates generated Sphinx configuration content." "update_conf_content.py" "Utility"
            }

            logs = container "Run Logs and Artifacts" "Stores logs and generated artifacts." "Filesystem" "Storage"
            temp = container "Temporary Workspace" "Ephemeral build workspace." "Filesystem" "Storage"
            scaffold = container "Docs Scaffold Templates" "Reusable Sphinx scaffold templates used for generated repositories." "Sphinx template files" "Storage"
            docs = container "Project Documentation" "Sphinx docs for Auto Doc." "Sphinx" "Docs"
            tests = container "Test Suite" "Automated tests." "Pytest" "Testing"
        }

        // External interaction
        user -> autodoc.api "Calls REST API"

        // Component interactions
        autodoc.api.router -> autodoc.api.models "Validates request payloads"
        autodoc.api.router -> autodoc.api.analysis "Triggers analysis"
        autodoc.api.router -> autodoc.api.sphinx "Triggers documentation build"
        autodoc.api.router -> autodoc.api.pr "Triggers PR creation"

        autodoc.api.analysis -> autodoc.api.git "Fetches repository data"
        autodoc.api.analysis -> autodoc.api.extractor "Extracts code blocks"
        autodoc.api.analysis -> autodoc.api.validation "analyses documentation coverage"
        autodoc.api.analysis -> autodoc.api.output "Writes analysis results"

        autodoc.api.validation -> autodoc.api.generation "Requests docstrings"
        autodoc.api.validation -> autodoc.api.output "Stores suggestions"
        autodoc.api.generation -> openai "Calls OpenAI API"

        autodoc.api.sphinx -> autodoc.api.git "Commits documentation files and scaffold assets"
        autodoc.api.sphinx -> autodoc.api.confupdate "Updates config"
        autodoc.api.sphinx -> autodoc.temp "Builds documentation"
        autodoc.api.sphinx -> autodoc.scaffold "Copies scaffold templates"
        autodoc.api.sphinx -> autodoc.api.output "Writes reports"
        autodoc.api.sphinx -> pages "Publishes reviewed documentation (GitHub only)"
        autodoc.api.sphinx -> gitlabCi "Triggers pipeline (GitLab only)"

        autodoc.api.pr -> autodoc.api.git "Creates GitHub-only PR"
        autodoc.api.pr -> autodoc.api.output "Reads suggestions"

        autodoc.api.git -> github "Uses GitHub APIs"
        autodoc.api.git -> gitlab "Uses GitLab APIs"

        autodoc.api.output -> autodoc.logs "Stores logs"

        repoCi -> autodoc.tests "Runs tests"
        repoCi -> autodoc.docs "Builds docs"
        repoCi -> autodoc.api "Build-checks application"

        user -> autodoc.docs "Reads documentation"
    }

    views {

        systemContext autodoc {
            include *
            autoLayout lr
            title "Auto Doc - System Context"
        }

        container autodoc {
            include *
            autoLayout lr
            title "Auto Doc - Container View"
        }

        component autodoc.api {
            include *
            autoLayout lr
            title "Auto Doc API - Component View"
        }

        styles {
            element "Person" {
                shape person
                background #0f172a
                color #ffffff
            }

            element "Software System" {
                background #1d4ed8
                color #ffffff
            }

            element "Container" {
                background #0ea5e9
                color #ffffff
            }

            element "Component" {
                background #e2e8f0
                color #0f172a
            }

            element "External" {
                background #334155
                color #ffffff
                border Solid
            }

            element "API" {
                shape RoundedBox
                background #0369a1
                color #ffffff
            }

            element "Service" {
                background #bae6fd
                color #0f172a
            }

            element "Utility" {
                background #cbd5e1
                color #0f172a
            }

            element "Storage" {
                shape Cylinder
                background #f8fafc
                color #0f172a
            }

            element "Docs" {
                shape Folder
                background #dbeafe
                color #0f172a
            }

            element "Testing" {
                shape Hexagon
                background #d1fae5
                color #064e3b
            }

            element "CI" {
                shape Pipe
                background #1e293b
                color #ffffff
            }

            relationship "Relationship" {
                color #334155
                thickness 2
            }
        }
    }
}