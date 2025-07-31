import re
from typing import List

class GenericCodeBlockExtractor:
    LANGUAGE_PATTERNS = {
        'python': [
            r'^\s*def\s+\w+\s*\(',                   # Python function
            r'^\s*class\s+\w+\s*(\(.*?\))?:',        # Python class
        ],
        'javascript': [
            r'^\s*(export\s+)?(default\s+)?function\s+\w+\s*\(',  # JS named function
            r'^\s*(export\s+)?(default\s+)?class\s+\w+\s*',       # JS class
            r'^\s*document\.\w+\s*\(',                            # document.addEventListener, etc.
            r'^\s*\w+\s*=\s*function\s*\(',                       # Function assignments
        ],
        'typescript': [
            r'^\s*(export\s+)?(default\s+)?function\s+\w+\s*\(',  # TS named function
            r'^\s*(export\s+)?(default\s+)?class\s+\w+\s*',       # TS class
        ],
        'matlab': [
            r'^\s*function\s+.*=',                 # MATLAB function (with output)
            r'^\s*function\s+\w+',                 # MATLAB function (no output)
            r'^\s*classdef\s+\w+',                 # MATLAB class
        ]
    }

    EXT_LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.m': 'matlab',
        '.matlab': 'matlab'
    }

    def __init__(self, file_content: str, file_name: str):
        self.file_content = file_content
        self.file_name = file_name
        self.language = self._detect_language()

    def _detect_language(self):
        for ext, lang in self.EXT_LANGUAGE_MAP.items():
            if self.file_name.endswith(ext):
                return lang
        return 'python'  # default

    def code_block_extractor(self) -> List[str]:
        """
        Extracts all code blocks (including nested) for the detected language.
        """
        lines = self.file_content.splitlines()
        blocks = []
        self._extract_blocks_recursive(lines, 0, len(lines), blocks, 0)
        return blocks

    def _extract_blocks_recursive(self, lines: List[str], start: int, end: int, blocks: List[str], base_indent: int):
        patterns = self.LANGUAGE_PATTERNS.get(self.language, [])
        combined_pattern = '|'.join(patterns)
        i = start
        while i < end:
            line = lines[i]
            indent = len(line) - len(line.lstrip())
            match = re.match(combined_pattern, line)
            if match and (self.language != 'python' or indent == base_indent):
                block_info = self._extract_single_block(lines, i, combined_pattern)
                if block_info:
                    blocks.append(block_info['block'])
                    # For Python, only recurse into the body of the block
                    if self.language == 'python':
                        body_start = i + 1
                        body_end = block_info['end_line']
                        # Only lines with greater indent than base_indent
                        body_lines = []
                        for j in range(body_start, body_end):
                            if j < len(lines):
                                body_line = lines[j]
                                if len(body_line) - len(body_line.lstrip()) > base_indent:
                                    body_lines.append(body_line)
                        if body_lines:
                            self._extract_blocks_recursive(body_lines, 0, len(body_lines), blocks, base_indent + 4)
                    i = block_info['end_line']
                else:
                    i += 1
            else:
                i += 1

    def _extract_single_block(self, lines: List[str], start_idx: int, pattern: str) -> dict:
        """
        Extracts a single code block starting from start_idx.
        Returns dict with 'block' content and 'end_line' index.
        """
        line = lines[start_idx]
        if self.language == 'python':
            if line.strip().startswith("def"):
                return self._extract_python_function_complete(lines, start_idx)
            elif line.strip().startswith("class") and line.rstrip().endswith(":"):
                return self._extract_python_class_complete(lines, start_idx)
        elif self.language in ['javascript', 'typescript']:
            return self._extract_curly_brace_block(lines, start_idx)
        elif self.language == 'matlab':
            if line.strip().startswith("function"):
                return self._extract_matlab_function(lines, start_idx)
            elif line.strip().startswith("classdef"):
                return self._extract_matlab_class(lines, start_idx)
        return None

    def _extract_python_function_complete(self, lines: List[str], start_idx: int) -> dict:
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        i = start_idx
        function_def_complete = False
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
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            if line.strip() == '':
                block.append(line.rstrip())
                i += 1
                continue
            if current_indent <= function_indent:
                break
            block.append(line.rstrip())
            i += 1
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        return {'block': full_block, 'end_line': i}

    def _extract_python_class_complete(self, lines: List[str], start_idx: int) -> dict:
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        line = lines[start_idx]
        block.append(line.rstrip())
        class_indent = len(line) - len(line.lstrip())
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            current_indent = len(line) - len(line.lstrip())
            if line.strip() == '':
                block.append(line.rstrip())
                i += 1
                continue
            if current_indent <= class_indent:
                break
            block.append(line.rstrip())
            i += 1
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        return {'block': full_block, 'end_line': i}

    def _extract_matlab_function(self, lines: List[str], start_idx: int) -> dict:
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        line = lines[start_idx]
        block.append(line.rstrip())
        nested_level = 0
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            block.append(line.rstrip())
            if (re.match(r'^\s*(if|for|while|switch|try|function|classdef)\b', line) or
                re.match(r'^\s*parfor\b', line)):
                nested_level += 1
            elif re.match(r'^\s*end\b', line):
                if nested_level == 0:
                    i += 1
                    break
                else:
                    nested_level -= 1
            i += 1
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        return {'block': full_block, 'end_line': i}

    def _extract_matlab_class(self, lines: List[str], start_idx: int) -> dict:
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        line = lines[start_idx]
        block.append(line.rstrip())
        nested_level = 0
        i = start_idx + 1
        while i < len(lines):
            line = lines[i]
            block.append(line.rstrip())
            if re.match(r'^\s*end\b', line):
                i += 1
                break
            i += 1
        footer = f"# --- Code Block ends at line {i} ---"
        full_block = header + '\n' + '\n'.join(block) + '\n' + footer
        return {'block': full_block, 'end_line': i}

    def _extract_curly_brace_block(self, lines: List[str], start_idx: int) -> dict:
        block = []
        header = f"# --- Code Block starts at line {start_idx + 1} ---"
        line = lines[start_idx]
        block.append(line.rstrip())
        # Check if opening brace is on this or next line
        if line.rstrip().endswith("{"):
            brace_count = line.count("{") - line.count("}")
            i = start_idx + 1
        else:
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