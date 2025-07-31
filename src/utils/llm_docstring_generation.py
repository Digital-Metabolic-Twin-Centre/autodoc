import google.ai.generativelanguage as glm
import google.generativeai as genai
from google.generativeai import types
import json
import time
import os
from typing import Optional
from tqdm import tqdm
from dotenv import load_dotenv

load_dotenv()

def configure_gemini(api_key: str = None):
    """
    Configure Gemini API with the provided API key.
    
    Args:
        api_key (str, optional): Gemini API key. If None, reads from environment.
    """
    if api_key is None:
        api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        raise ValueError("Gemini API key not provided. Set GEMINI_API_KEY environment variable or pass api_key parameter.")
    
    genai.configure(api_key=api_key)

def create_docstring_prompt(code: str, language: str = "python") -> str:
    """
    Create a prompt for Gemini to generate a concise docstring.
    
    Args:
        code (str): The code block to analyze.
        language (str): Programming language of the code.
    
    Returns:
        str: Formatted prompt for docstring generation.
    """
    prompt = f"""
Generate a concise docstring for the following {language} code. The docstring should be 4-5 lines maximum and include:

1. A brief description (1-2 lines maximum)
2. Args section with parameter types and descriptions
3. Returns section with return type and description

Follow {language} docstring conventions. Be concise and clear.

Return the response as a JSON object with this structure:
{{
    "docstring": "the generated docstring content"
}}

Code to analyze:
```{language}
{code}
```

Generate only the JSON response without any additional text or markdown formatting.
"""
    return prompt

def _clean_json_block(response_text: str) -> str:
    """
    Clean JSON response from Gemini API.
    
    Args:
        response_text (str): Raw response text from API.
    
    Returns:
        str: Cleaned JSON string.
    """
    # Remove markdown code blocks if present
    if "```json" in response_text:
        start = response_text.find("```json") + 7
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()
    elif "```" in response_text:
        start = response_text.find("```") + 3
        end = response_text.find("```", start)
        response_text = response_text[start:end].strip()
    
    return response_text.strip()

def generate_docstring_with_gemini(code: str, language: str = "python", api_key: str = None) -> Optional[str]:
    """
    Generate a concise docstring for the given code using Gemini API.
    
    Args:
        code (str): The code block for which to generate docstring.
        language (str): Programming language of the code (default: "python").
        api_key (str, optional): Gemini API key.
    
    Returns:
        str: Generated docstring or None if generation fails.
    """
    try:
        # Configure Gemini if not already configured
        configure_gemini(api_key)
        
        # Create the client
        client = genai.GenerativeModel("gemini-2.0-flash-lite")
        
        # Create the annotation prompt
        prompt = create_docstring_prompt(code, language)
        
        # Generate content
        response = client.generate_content(
            contents=[prompt],
            generation_config=types.GenerationConfig(
                temperature=0.0
            )
        )
        
        if response and response.text:
            # Clean and parse the JSON response
            response_text = _clean_json_block(response.text.strip())
            response_json = json.loads(response_text)
            return response_json.get('docstring', '')
        else:
            print("No response from Gemini API")
            return None
            
    except Exception as e:
        print(f"Error generating docstring with Gemini: {e}")
        return None

def generate_docstrings_for_code_blocks(code_blocks_data: list, language: str = "python") -> list:
    """
    Generate docstrings for multiple code blocks using Gemini API.
    
    Args:
        code_blocks_data (list): List of dictionaries containing code block information.
        language (str): Programming language of the code blocks.
    
    Returns:
        list: Updated list with generated docstrings.
    """
    # Initialize the docstring field
    for block in code_blocks_data:
        block['generated_docstring'] = 'N/A'
    
    for i in tqdm(range(len(code_blocks_data)), desc="Generating docstrings"):
        code_block = code_blocks_data[i].get('code', '')
        function_name = code_blocks_data[i].get('function_name', f'Block_{i}')
        
        if not code_block.strip():
            print(f"Skipping empty code block for {function_name}")
            continue
        
        try:
            # Generate docstring
            docstring = generate_docstring_with_gemini(code_block, language)
            
            if docstring:
                code_blocks_data[i]['generated_docstring'] = docstring
            else:
                code_blocks_data[i]['generated_docstring'] = 'Failed to generate'
            
            # Sleep to avoid rate limiting
            time.sleep(1.5)
            
        except Exception as e:
            print(f"Error processing code block {i}: {function_name}")
            print(f"Exception: {e}")
            code_blocks_data[i]['generated_docstring'] = f'Error: {str(e)}'
    
    return code_blocks_data

def format_docstring_for_language(docstring: str, language: str) -> str:
    """
    Format the generated docstring according to language conventions.
    
    Args:
        docstring (str): Raw docstring content.
        language (str): Programming language.
    
    Returns:
        str: Formatted docstring.
    """
    if not docstring or docstring == 'N/A':
        return docstring
    
    if language.lower() == "python":
        # Python triple-quote format
        lines = docstring.split('\n')
        indented_lines = ['    ' + line if line.strip() else '' for line in lines]
        return f'    """\n{chr(10).join(indented_lines)}\n    """'
    
    elif language.lower() in ["javascript", "typescript"]:
        # JSDoc format
        lines = docstring.split('\n')
        formatted_lines = ["    /**"] + [f"     * {line}" for line in lines] + ["     */"]
        return '\n'.join(formatted_lines)
    
    elif language.lower() == "matlab":
        # MATLAB comment format
        lines = docstring.split('\n')
        formatted_lines = [f"% {line}" for line in lines]
        return '\n'.join(formatted_lines)
    
    else:
        return docstring