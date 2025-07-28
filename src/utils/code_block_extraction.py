import re
from typing import List

class GenericCodeBlockExtractor:
    def __init__(self, file_content: str, file_name: str):
        self.file_content = file_content
        self.file_name = file_name

    def code_block_extractor(self) -> List:
        """
        Extracts code blocks (functions, classes) from the file content for common languages.
        Handles Python indentation, MATLAB 'end' blocks, and curly-brace blocks.
        Treats nested functions and classes as separate code blocks while preserving parent structure.
        """
        patterns = [
            r'^\s*def\s+\w+\s*\(',                                                     # Python function (multi-line support)
            r'^\s*class\s+\w+\s*(\(.*?\))?:',                                          # Python class
            r'^\s*(export\s+)?(default\s+)?function\s+\w+\s*\(',                      # JS/TS named function (fixed)
            r'^\s*(export\s+)?(default\s+)?class\s+\w+\s*',                            # JS/TS class
            r'^\s*document\.\w+\s*\(',                                                 # document.addEventListener, etc. (simplified)
            r'^\s*\w+\s*=\s*function\s*\(',                                            # Function assignments (fixed)
            r'^\s*function\s+.*=',                                                     # MATLAB function (with output)
            r'^\s*function\s+\w+',                                                     # MATLAB function (no output)
            r'^\s*classdef\s+\w+',                                                     # MATLAB class
        ]
          
        combined_pattern = '|'.join(patterns)
        code_blocks = []
        lines = self.file_content.splitlines()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            match = re.match(combined_pattern, line)
            
            if match:
                # Extract this code block starting from current line
                block_info = self._extract_single_block(lines, i, combined_pattern)
                if block_info:
                    code_blocks.append(block_info['block'])
                    i = block_info['end_line']
                else:
                    i += 1
            else:
                i += 1
                
        return code_blocks

    def _extract_single_block(self, lines: List[str], start_idx: int, pattern: str) -> dict:
        """
        Extracts a single code block starting from start_idx.
        Returns dict with 'block' content and 'end_line' index.
        """
        line = lines[start_idx]
        match = re.match(pattern, line)

        if not match:
            return None
            
        # Handle different language patterns
        if line.strip().startswith("def"):
            return self._extract_python_function_complete(lines, start_idx)
        elif line.strip().startswith("class") and line.rstrip().endswith(":"):
            return self._extract_python_class_complete(lines, start_idx)
        elif line.strip().startswith("function") and not re.search(r'document\.|=', line):
            # Check if it's a MATLAB function or JS function
            if "=" in line or self.file_name.endswith(('.m', '.matlab')):
                return self._extract_matlab_function(lines, start_idx)
            else:
                return self._extract_curly_brace_block(lines, start_idx)
        elif re.search(r'document\.\w+\s*\(', line):
            # Document method calls - always use curly brace extraction
            return self._extract_curly_brace_block(lines, start_idx)
        elif re.search(r'\w+\s*=\s*function\s*\(', line):
            # Function assignments - use curly brace extraction
            return self._extract_curly_brace_block(lines, start_idx)
        elif line.rstrip().endswith("{") or (start_idx + 1 < len(lines) and lines[start_idx + 1].strip() == "{"):
            return self._extract_curly_brace_block(lines, start_idx)
        else:
            return self._extract_generic_block(lines, start_idx)

    def _extract_python_function_complete(self, lines: List[str], start_idx: int) -> dict:
        """Extract a complete Python function including all nested structures."""
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        
        # Handle multi-line function definition
        i = start_idx
        function_def_complete = False
        
        # Collect function definition lines until we find the colon
        while i < len(lines):
            line = lines[i]
            block.append(line.rstrip())
            
            if line.rstrip().endswith(':'):
                function_def_complete = True
                function_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
                i += 1
                break
            i += 1
            
        if not function_def_complete:
            return None
            
        # Now collect the entire function body
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            
            # Empty line - include it
            if line.strip() == '':
                block.append(line.rstrip())
                i += 1
                continue
                
            # Line at same or less indentation than function - end of function
            if current_indent <= function_indent:
                break
                
            # Include all lines within the function, including nested structures
            block.append(line.rstrip())
            i += 1
            
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        
        return {'block': full_block, 'end_line': i}

    def _extract_python_class_complete(self, lines: List[str], start_idx: int) -> dict:
        """Extract a complete Python class including all nested structures."""
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        
        line = lines[start_idx]
        block.append(line.rstrip())
        class_indent = len(line) - len(line.lstrip())
        
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            
            # Empty line - include it
            if line.strip() == '':
                block.append(line.rstrip())
                i += 1
                continue
                
            # Line at same or less indentation than class - end of class
            if current_indent <= class_indent:
                break
                
            # Include all lines within the class, including nested structures
            block.append(line.rstrip())
            i += 1
            
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        
        return {'block': full_block, 'end_line': i}

    def _extract_matlab_function(self, lines: List[str], start_idx: int) -> dict:
        """Extract a MATLAB function block."""
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        
        line = lines[start_idx]
        block.append(line.rstrip())
        nested_level = 0
        
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            block.append(line.rstrip())
            
            # Track nested constructs
            if (re.match(r'^\s*(if|for|while|switch|try|function|classdef)\b', line) or
                re.match(r'^\s*parfor\b', line)):
                nested_level += 1
            elif re.match(r'^\s*end\b', line):
                if nested_level == 0:
                    # This 'end' closes the main function
                    i += 1
                    break
                else:
                    nested_level -= 1
            i += 1
            
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        
        return {'block': full_block, 'end_line': i}

    def _extract_curly_brace_block(self, lines: List[str], start_idx: int) -> dict:
        """Extract a JavaScript/TypeScript function or class block."""
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        
        line = lines[start_idx]
        block.append(line.rstrip())
        
        # Check if opening brace is on next line
        if line.rstrip().endswith("{"):
            brace_count = line.count("{") - line.count("}")
            i = start_idx + 1
        else:
            # Opening brace on next line
            if start_idx + 1 < len(lines):
                block.append(lines[start_idx + 1].rstrip())
                brace_count = 1
                i = start_idx + 2
            else:
                return None
                
        while i < len(lines) and brace_count > 0:
            line = lines[i]
            block.append(line.rstrip())
            brace_count += line.count("{") - line.count("}")
            i += 1
            
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        
        return {'block': full_block, 'end_line': i}

    def _extract_generic_block(self, lines: List[str], start_idx: int) -> dict:
        """Extract a generic indentation-based block."""
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        
        line = lines[start_idx]
        block.append(line.rstrip())
        block_indent = len(line) - len(line.lstrip())
        
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            
            if line.strip() == '' or current_indent > block_indent:
                block.append(line.rstrip())
            else:
                break
            i += 1
            
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        
        return {'block': full_block, 'end_line': i}

    def extract_nested_blocks_separately(self) -> List:
        """
        Alternative method that extracts nested functions/classes as separate blocks
        while also preserving the complete parent structure.
        """
        all_blocks = self.code_block_extractor()  # Get complete blocks first
        
        # Now extract nested structures separately
        nested_blocks = []
        for block in all_blocks:
            nested_blocks.extend(self._find_nested_structures(block))
            
        return all_blocks + nested_blocks
    
    def _find_nested_structures(self, block: str) -> List[str]:
        """Find and extract nested functions/classes from a block."""
        nested_blocks = []
        lines = block.split('\n')
        
        # Remove header/footer
        clean_lines = []
        for line in lines:
            if not line.strip().startswith('# --- Code Block'):
                clean_lines.append(line)
        
        # Look for nested structures
        patterns = [
            r'^\s*def\s+\w+\s*\(',
            r'^\s*class\s+\w+\s*(\(.*?\))?:'
        ]
        combined_pattern = '|'.join(patterns)
        
        i = 0
        while i < len(clean_lines):
            line = clean_lines[i]
            match = re.match(combined_pattern, line)
            
            if match:
                # Check if this is at a nested level (has indentation)
                if len(line) - len(line.lstrip()) > 0:
                    # Extract this nested structure
                    nested_block = self._extract_nested_structure(clean_lines, i)
                    if nested_block:
                        nested_blocks.append(nested_block)
            i += 1
                
        return nested_blocks
    
    def _extract_nested_structure(self, lines: List[str], start_idx: int) -> str:
        """Extract a single nested structure."""
        block = []
        header = f"# --- Nested Code Block starts at line {start_idx + 1} ---"
        
        base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
        i = start_idx
        
        # Handle multi-line definition
        while i < len(lines):
            line = lines[i]
            block.append(line.rstrip())
            
            if line.rstrip().endswith(':'):
                i += 1
                break
            i += 1
        
        # Collect body
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            
            if line.strip() == '':
                block.append(line.rstrip())
                i += 1
                continue
                
            if current_indent <= base_indent:
                break
                
            block.append(line.rstrip())
            i += 1
            
        footer = f"# --- Nested Code Block ends at line {i} ---"
        return header + '\n' + '\n'.join(block) + '\n' + footer