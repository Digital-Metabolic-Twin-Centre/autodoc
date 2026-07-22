# AutoDoc: Audit-Ready Documentation Feature Requirements

## What a Finished Tool Looks Like
A finished, AI-driven, audit-ready process documentation tool will:

- **Build on AutoDoc's Foundation:** Leverage AutoDoc's existing code analysis and string summarization capabilities.
- **Automate Repository Analysis:** Automate the analysis of multi-language repositories (e.g., parsing Python and Julia files).
- **Extract Contextual Evidence:** Based on the unique process being documented, contextually extract evidence from the GitHub repository and summarize the information.
- **Utilize Prompt Templates:** Use AI prompt templates to write a process report that directly answers the base practice questions for each specific process.
- **Produce Structured Reports:** Generate a highly structured report based on the extracted and summarized evidence.
- **Support Native Export:** Output a Markdown (`.md`) file that can be easily reviewed by humans and, upon meeting satisfactory quality levels, automatically converted into formal PDF format.

---

# Requirement Description

## Requirement 1: Path Configuration
**Description:** The tool must not rely on hardcoded local directories. It must accept dynamic input arguments for the target repository path and the output directory.
**Objective:** Ensure the tool can scan any codebase on any developer's environment seamlessly.

## Requirement 2: Decoupled LLM Provider Interface
**Description:** The tool must not hardcode `openai` or specific models like `gpt-4o`. It must utilize AutoDoc's existing LLM abstraction layer, allowing users to configure their preferred AI provider (e.g., OpenAI, Anthropic, or local open-source models).
**Objective:** Maintain architectural consistency with the core AutoDoc framework and provide flexibility for end-users.

## Requirement 3: Intelligent Context Extraction
**Description:** Instead of feeding raw code to the LLM (which exceeds context windows), the tool must utilize the existing `GenericCodeBlockExtractor` to parse Abstract Syntax Trees (AST). It must generate a lightweight, structural blueprint containing only file paths, class definitions, and function signatures.
**Objective:** Optimize token usage and provide the LLM with a clear, high-level map of the software architecture.

## Requirement 4: Configuration-Driven Prompt Templating
**Description:** The tool must not hardcode specific audit standards (like ISO 33061) into the code. It must implement a prompt templating system (e.g., using YAML or Jinja) where users can define their target audit standard framework, the specific persona, and the required document structure.
**Objective:** Allow the tool to generate documentation for *any* standard (ISO 33061, SOC 2, HIPAA, etc.) purely based on user configuration, facilitating seamless integration into the official AutoDoc repository.

## Requirement 5: Enforced Structured JSON Output
**Description:** The tool must mandate that the LLM returns its findings in a strict JSON format (e.g., `{"architecture_overview": "...", "missing_evidence": "..."}`). 
**Objective:** Ensure the output is machine-readable so it can be reliably parsed and routed to different output files without manual intervention.

## Requirement 6: Automated Document Export Pipeline
**Description:** The tool must include an export pipeline capable of taking the parsed JSON data and converting it into formal, audit-ready artefacts. It must support Markdown generation, and ideally provide hooks or utilities to convert that Markdown into formal `.docx` or `.pdf` formats.
**Objective:** Provide end-users with polished, professional documents that are immediately ready for audit submission.
