import ast
import re
from typing import Optional, Tuple, List, Dict

def analyze_docstring_in_blocks(code_blocks: list, file_name: str = "unknown", file_path: str = "unknown", language: str = None) -> dict:
    """
    Analyzes code blocks to find docstring and identify missing ones.
    Supports multiple programming languages including Python, JavaScript/TypeScript and MATLAB.

    Args:
        code_blocks (list): List of code blocks extracted from a file
        file_name (str): Name of the file being analyzed
        language (str): Programming language of the code blocks

    Returns:
        dict: Analysis results with docstring information
    """
    
    results = {
        'file_name': file_name,
        'file_path': file_path,
        'total_blocks': len(code_blocks),
        'blocks_with_docstring': 0,
        'blocks_without_docstring': 0,
        'Docstring analysis': []
    }
    
    def analyze_python_block(clean_code: str) -> dict:
        """Analyze Python code block for docstring"""
        analysis = {
            'has_docstring': False,
            'function_name': 'unknown',
            'block_type': 'unknown',
            'docstring_content': None,
            'missing_docstring': True,
        }
        
        try:
            tree = ast.parse(clean_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    analysis['function_name'] = node.name
                    analysis['block_type'] = 'function'
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis['has_docstring'] = True
                        analysis['docstring_content'] = docstring
                        analysis['missing_docstring'] = False
                    break
                elif isinstance(node, ast.AsyncFunctionDef):
                    analysis['function_name'] = node.name
                    analysis['block_type'] = 'async_function'
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis['has_docstring'] = True
                        analysis['docstring_content'] = docstring
                        analysis['missing_docstring'] = False
                    break
                elif isinstance(node, ast.ClassDef):
                    analysis['function_name'] = node.name
                    analysis['block_type'] = 'class'
                    docstring = ast.get_docstring(node)
                    if docstring:
                        analysis['has_docstring'] = True
                        analysis['docstring_content'] = docstring
                        analysis['missing_docstring'] = False
                    break
        except SyntaxError:
            # Fallback to regex
            return analyze_with_regex(clean_code, 'python')
            
        return analysis
    
    def analyze_with_regex(clean_code: str, language: str) -> dict:
        """Analyze code block using regex patterns for different languages"""
        analysis = {
            'has_docstring': False,
            'function_name': 'unknown',
            'block_type': 'unknown',
            'docstring_content': None,
            'missing_docstring': True
        }
        
        # Language-specific patterns
        patterns = {
            'python': {
                'function': r'def\s+(\w+)\s*\(',
                'class': r'class\s+(\w+)\s*[\(:]',
                'docstring': [r'"""(.*?)"""', r"'''(.*?)'''"]
            },
            'javascript': {
                'function': r'function\s+(\w+)\s*\(|(\w+)\s*=\s*function\s*\(|(\w+)\s*:\s*function\s*\(',
                'class': r'class\s+(\w+)\s*{',
                'docstring': [r'/\*\*(.*?)\*/', r'//\s*(.*?)$']
            },
            'typescript': {
                'function': r'function\s+(\w+)\s*\(|(\w+)\s*=\s*function\s*\(|(\w+)\s*:\s*function\s*\(',
                'class': r'class\s+(\w+)\s*{',
                'docstring': [r'/\*\*(.*?)\*/', r'//\s*(.*?)$']
            },
            'matlab': {
                'function': r'function\s+(?:.*=\s*)?(\w+)\s*\(',
                'class': r'classdef\s+(\w+)',
                'docstring': [r'%\s+(.*?)(?=\n\s*(?:%|\w))', r'%{(.*?)%}']
            }
        }
        
        if language not in patterns:
            return analysis
        
        lang_patterns = patterns[language]
        
        # Find function/class name
        func_match = re.search(lang_patterns['function'], clean_code, re.MULTILINE)
        class_match = re.search(lang_patterns['class'], clean_code, re.MULTILINE)
        
        if func_match:
            # Extract the actual function name from groups
            groups = func_match.groups()
            analysis['function_name'] = next((g for g in groups if g), 'unknown')
            analysis['block_type'] = 'function'
        elif class_match:
            groups = class_match.groups()
            analysis['function_name'] = next((g for g in groups if g), 'unknown')
            analysis['block_type'] = 'class'
        
        # Look for docstring
        for docstring_pattern in lang_patterns['docstring']:
            docstring_match = re.search(docstring_pattern, clean_code, re.DOTALL | re.MULTILINE)
            if docstring_match:
                analysis['has_docstring'] = True
                analysis['docstring_content'] = docstring_match.group(1).strip()
                analysis['missing_docstring'] = False
                break
        
        return analysis
    
    # Analyze each code block
    for i, block in enumerate(code_blocks, 1):
        # Extract the actual code (remove header/footer comments)
        lines = block.split('\n')
        start_line_number = None
        code_lines = []
        
        for line in lines:
            if not line.strip().startswith('# --- Code Block'):
                code_lines.append(line)
            if '--- Code Block starts at line' in line:
                match = re.search(r'starts at line (\d+)', line)
                if match:
                    start_line_number = int(match.group(1))
                else:
                    start_line_number = 0
            
        clean_code = '\n'.join(code_lines)
        #language = detect_language(clean_code, file_name)
        
        # Analyze based on detected language
        if language == 'python':
            block_analysis = analyze_python_block(clean_code)
        else:
            block_analysis = analyze_with_regex(clean_code, language)
        
        block_analysis['block_number'] = i
        block_analysis['language'] = language
        block_analysis['line number'] = start_line_number if start_line_number is not None else 0

        # Update counters
        if block_analysis['has_docstring']:
            results['blocks_with_docstring'] += 1
        else:
            results['blocks_without_docstring'] += 1
        
        results['Docstring analysis'].append(block_analysis)
    
    return results