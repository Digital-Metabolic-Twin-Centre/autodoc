from utils.git_utils import fetch_repo_tree, detect_tech_stack, fetch_content_from_github, fetch_content_from_gitlab
from utils.code_block_extraction import GenericCodeBlockExtractor
from utils.docstring_validation import analyze_docstring_in_blocks
import pandas as pd

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
    files_missing_docstring = []
    file_present_docstring = []
    block_analysis_list = []

    # Fetch repo tree and detect tech stack
    file_list = fetch_repo_tree(repo_url, token, branch=branch, provider=provider.lower())
    tech = detect_tech_stack(file_list)

    # Determine file type key for provider
    file_type_key = "blob" if provider.lower() == "gitlab" else "file"

    for file in file_list:

        #To make sure item is a file not a directory
        if file.get('type', '') != file_type_key:
            continue
        file_name = file.get('name', '')
        #check the file type (tech stack)
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
            print(f"File {file_name} is not supported for docstring validation. Skipping...")
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
            print(f"Warning!! Empty file {file_name}. Cannot validate docstring.")
            continue

        # Create a code blocks in the file to analyze
        extractor = GenericCodeBlockExtractor(content, file_name)
        code_blocks = extractor.code_block_extractor()
        if not code_blocks:
            print(f"Warning!! No code blocks found in {file_name}. Cannot validate docstring.")
            continue
        print(f"Analyzing {file_name} with {len(code_blocks)} code blocks.")
        #print(code_blocks)
        # Analyze docstring in the code blocks
        block_analysis = analyze_docstring_in_blocks(code_blocks, file_name=file_name, file_path=file_path, language=language)
        block_analysis_list.append(block_analysis)
        """if block_analysis['blocks_with_docstring'] > 0:
            print(f"Analysis for {file_name}: {block_analysis}")
            file_present_docstring.append({
                'name': file_name,
                'path': file_path,
                'item': block_analysis['function_name'],
                'type': block_analysis['block_type'],
                'Description': block_analysis['docstring_content']
            })
        else:
            files_missing_docstring.append({
                'name': file_name,
                'path': file_path,
                'item': block_analysis['function_name'],
                'type': block_analysis['block_type'],
                'Description': "Missing docstring"
            })"""
            

    #save the missing docstring files in csv
    #if files_missing_docstring:
    #    df_missing = pd.DataFrame(files_missing_docstring, columns=['name', 'path', 'item', 'type', 'Description'])
    #    df_missing.to_csv("files_missing_docstring.csv", index=False)

    return block_analysis_list