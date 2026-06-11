"""
Audit Document Generator Prototype: Software Architecture
=========================================================
Scans the OptArrow source code, extracts docstrings and structure, 
and uses an LLM to generate an ISO 33061-compliant Architecture Overview.

Usage:
    C:/Users/oladi/.local/bin/uv.exe run python prototype_audit_generator.py
"""

import os # 
import sys
from pathlib import Path
import openai
import json

# -- Path setup: make sure AutoDoc's src is importable ----------------------
AUTODOC_SRC = Path(__file__).parent / "src"
sys.path.insert(0, str(AUTODOC_SRC))

# -- Configure the .env so the OpenAI key is loaded -------------------------
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# -- AutoDoc internal utilities ----------------------------------------------
from utils.code_block_extraction import GenericCodeBlockExtractor

# -- Configuration -----------------------------------------------------------
OPTARROW_ROOT = Path(r"c:\Users\oladi\Desktop\optArrow-main_2\optArrow-main")
OUTPUT_DIR = Path(r"C:\Users\oladi\Desktop\Thesis\Auto_Doc_GIT_V6\Update the code")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARCH_DOC_FILE = OUTPUT_DIR / "Architecture_Overview_ISO33061.md"
MISSING_EVIDENCE_FILE = OUTPUT_DIR / "Missing_Evidence_ISO33061.md"

SUPPORTED_EXTENSIONS = {".py": "python"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "tests", "scripts"}

def collect_source_files(root: Path) -> list[Path]:
    """Walk the OptArrow repo and collect core source files."""
    files = []
    src_dir = root / "src"
    if not src_dir.exists():
        src_dir = root
        
    for path in src_dir.rglob("*"):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.is_file() and path.suffix in SUPPORTED_EXTENSIONS:
            files.append(path)
    return files


def generate_architecture_doc(codebase_summary: str) -> dict:
    """Send the codebase summary to OpenAI to generate ISO 33061 docs."""
    prompt = f"""
You are an expert Software Architect and Quality Assurance Auditor.
I am providing you with a high-level summary of a Python codebase (OptArrow).

Your task is to generate TWO outputs compliant with ISO/IEC TS 33061 "Architecture Definition Process".
IMPORTANT: The "Architecture Overview" must be formatted as a Formal Narrative Report, similar to a comprehensive technical document (not just bullet points). It should flow with prose paragraphs, an introduction, high-level architecture section, component descriptions, data flow/interactions, etc.

Within this narrative structure, you MUST weave in the ISO 33061 Architecture Requirements:
1. Identify system elements and components explicitly.
2. Discuss external and internal interfaces (e.g., API interfaces like FastAPI, RPC, Solvers).
3. Discuss the allocation of functional requirements to these architectural elements.
4. Describe dynamic behaviors and interactions between components in the Data Flow section.

The Architecture Overview MUST include the following image right after the Introduction section:
![OptArrow Architecture](OptArrow_Architecture.png)

Identify Missing Evidence: 
Specify what required architecture documentation is missing in the code (e.g., lack of documented interface protocols, security configurations, deployment definitions).

Return a JSON object with two keys:
"architecture_overview": The full markdown string for the Architecture Overview (Formal Narrative).
"missing_evidence": The full markdown string for the Missing Evidence.

Codebase Summary:
-----------------
{codebase_summary}
-----------------

Return strictly valid JSON.
"""
    print("  [>] Sending request to OpenAI (this may take a minute)...")
    
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": "You are a senior software architect. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    
    return json.loads(response.choices[0].message.content.strip())


def run_prototype():
    print("\n" + "="*60)
    print("  AutoDoc Prototype - ISO 33061 Architecture Generator")
    print("="*60)

    source_files = collect_source_files(OPTARROW_ROOT)
    print(f"\n[OK] Found {len(source_files)} core source files in OptArrow\n")

    print("  [>] Extracting structural context from files...")
    codebase_summary_lines = []
    
    for file_path in source_files:
        relative_path = file_path.relative_to(OPTARROW_ROOT)
        codebase_summary_lines.append(f"\n### File: {relative_path}")
        
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        extractor = GenericCodeBlockExtractor(content, file_path.name)
        code_blocks = extractor.code_block_extractor()

        if code_blocks:
            for block in code_blocks:
                lines = block.strip().split("\n")
                signature = "Unknown function"
                if len(lines) > 1:
                    signature = lines[1].strip()
                codebase_summary_lines.append(f"- Block: {signature}")
        else:
            codebase_summary_lines.append("- (No specific classes/functions found)")

    full_summary = "\n".join(codebase_summary_lines)
    
    # Send to OpenAI
    outputs = generate_architecture_doc(full_summary)
    
    # Save outputs
    with open(ARCH_DOC_FILE, "w", encoding="utf-8") as f:
        f.write(outputs.get("architecture_overview", "Error generating Architecture Overview."))
        
    with open(MISSING_EVIDENCE_FILE, "w", encoding="utf-8") as f:
        f.write(outputs.get("missing_evidence", "Error generating Missing Evidence."))

    print("\n" + "="*60)
    print("  Generation Complete")
    print("="*60)
    print(f"  [OK] Architecture Document saved to: {ARCH_DOC_FILE}")
    print(f"  [OK] Missing Evidence Document saved to: {MISSING_EVIDENCE_FILE}")
    print("="*60 + "\n")


if __name__ == "__main__":
    run_prototype()
