from utils.git_utils import fetch_repo_tree, fetch_content_from_github, fetch_content_from_gitlab
from utils.code_block_extraction import GenericCodeBlockExtractor
from utils.docstring_generation import generate_docstring_with_openai, format_docstring_for_language
from utils.docstring_validation import analyze_docstring_in_blocks, analyze_docstring_in_module
import pandas as pd
import os
from config.log_config import get_logger

logger = get_logger(__name__)

def analyze_repo(provider, repo_url, token, branch):
    """
    Analyze a repository for Python files missing docstring.

    Description:
        This function fetches the repository tree, detects the tech stack, and checks each file
        for missing or present docstring. It returns lists of files and items missing docstring and those with docstring.

    Args:
        provider (str): The git provider name (e.g., 'github', 'gitlab').
        repo_url (str): The URL of the repository.
        token (str): The authentication token for accessing the repository.
        branch (str): The branch name to analyze.

    Returns:
        tuple: 
            - files_missing_docstring (list): List of dicts for files/items missing docstring.
            - file_present_docstring (list): List of dicts for files/items with docstring.
    """
    block_analysis_list = []
    logger.info(f"Analyzing repo: provider={provider}, url={repo_url}, branch={branch}")
    # delete the suggested docstring file and block analysis file if it exists
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'files')
    os.makedirs(output_dir, exist_ok=True)
    suggested_file = os.path.join(output_dir, "suggested_docstring.txt")
    block_analysis_file = os.path.join(output_dir, "block_analysis.csv")
    if os.path.exists(suggested_file):
        os.remove(suggested_file)
        logger.debug(f"Deleted {suggested_file}")
    if os.path.exists(block_analysis_file):
        os.remove(block_analysis_file)
        logger.debug(f"Deleted {block_analysis_file}")

    # Fetch repo tree
    try:
        file_list = fetch_repo_tree(repo_url, token, branch=branch, provider=provider.lower())
        logger.info(f"Fetched repo tree, {len(file_list)} files found.")
    except Exception as e:
        logger.error(f"Error fetching repo tree: {e}")
        raise
    #tech = detect_tech_stack(file_list)

    # Determine file type key for provider
    file_type_key = "blob" if provider.lower() == "gitlab" else "file"

    for file in file_list:

        #To make sure item is a file not a directory
        if file.get('type', '') != file_type_key:
            continue
        file_name = file.get('name', '')
        language = None
        if file_name.endswith(('.py', '.pyw')):
            language = 'python'
        elif file_name.endswith(('.js', '.jsx')):
            language = 'javascript'
        elif file_name.endswith(('.ts', '.tsx')):
            language = 'typescript'
        elif file_name.endswith(('.m', '.mat')):
            language = 'matlab'
        # File type not supported
        else:
            logger.warning(f"File {file_name} is not supported for docstring validation. Skipping...")
            continue
        file_path = file.get('path', '')

        #fetch content based on provider
        if provider.lower() == "github":
            content = fetch_content_from_github(repo_url, branch, file_path, token)
        elif provider.lower() == "gitlab":
            content = fetch_content_from_gitlab(repo_url, branch, file_path, token)
        else:
            content = ""
        if content is None or content == "":
            logger.warning(f"Empty file {file_name}. Cannot validate docstring.")
            continue

        # Create a code blocks in the file to analyze
        extractor = GenericCodeBlockExtractor(content, file_name)
        code_blocks = extractor.code_block_extractor()
        # If no code blocks found, check for module-level docstring
        if not code_blocks:
            logger.warning(f"No code blocks found in {file_name}. Checking for module-level docstring...")
            module_docstring = analyze_docstring_in_module(content, language)
            if module_docstring:
                block_analysis = {
                    'file_name': file_name,
                    'file_path': file_path,
                    'total_blocks': 1,
                    'blocks_with_docstring': 1,
                    'blocks_without_docstring': 0,
                    'docstring_analysis': [{
                        'function_name': f"Module: {file_name}",
                        'block_type': 'module',
                        'docstring_content': module_docstring,
                        'missing_docstring': False,
                        'block_number': 1,
                        'language': language,
                        'line_number': 1
                    }]
                }
            else:
                # No module docstring found either
                block_analysis = {
                    'file_name': file_name,
                    'file_path': file_path,
                    'total_blocks': 1,
                    'blocks_with_docstring': 0,
                    'blocks_without_docstring': 1,
                    'docstring_analysis': [{
                        'function_name': f"Module: {file_name}",
                        'block_type': 'module',
                        'docstring_content': None,
                        'missing_docstring': True,
                        'block_number': 1,
                        'language': language,
                        'line_number': 1
                    }]
                }
                generated_docstring = generate_docstring_with_openai(content, language)

                if generated_docstring:
                    logger.info("Generated Docstring:")
                    logger.info(format_docstring_for_language(generated_docstring, language))
                    suggested_file = os.path.join(output_dir, "suggested_docstring.txt")
                    with open(suggested_file, 'a') as f:
                        f.write(f"\n# File: {file_name}, Path: {file_path}, Function: {block_analysis['docstring_analysis'][0]['function_name']}, Line: {block_analysis['docstring_analysis'][0]['line_number']}\n")
                        f.write(f"{format_docstring_for_language(generated_docstring, language)}\n")
                        f.write(f"{'-'*100}\n")
                else:
                    logger.warning("Docstring generation failed.")

            block_analysis_list.append(block_analysis)
            continue

        logger.info(f"Analyzing {file_name} with {len(code_blocks)} code blocks.")
        block_analysis = analyze_docstring_in_blocks(code_blocks, file_name=file_name, file_path=file_path, language=language)
        block_analysis_list.append(block_analysis)

    #save details in csv
    if block_analysis_list:

        #save details in csv
        flattened_data = []
        
        for block_analysis in block_analysis_list:
            # Extract main keys
            file_name = block_analysis.get('file_name', '')
            file_path = block_analysis.get('file_path', '')
            
            # Extract nested dictionary data from docstring_analysis
            docstring_analysis = block_analysis.get('docstring_analysis', [])
            for analysis in docstring_analysis:
                row = {
                    'file_name': file_name,
                    'file_path': file_path,
                    'function_name': analysis.get('function_name', ''),
                    'block_type': analysis.get('block_type', ''),
                    'missing_docstring': analysis.get('missing_docstring', True),
                    'language': analysis.get('language', ''),
                    'line_number': analysis.get('line_number', 0)
                }
                flattened_data.append(row)
        
        # Create DataFrame with flattened data
        df = pd.DataFrame(flattened_data)
        output_path = os.path.join(output_dir, "block_analysis.csv")
        df.to_csv(output_path, index=False)

    if not block_analysis_list:
        logger.warning("No files with docstring analysis found.")
        return output_path, None
    return output_path, block_analysis_list