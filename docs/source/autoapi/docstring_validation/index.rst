docstring_validation
====================

.. py:module:: docstring_validation


Attributes
----------

.. autoapisummary::

   docstring_validation.logger


Functions
---------

.. autoapisummary::

   docstring_validation.analyze_docstring_in_blocks
   docstring_validation.analyze_docstring_in_module


Module Contents
---------------

.. py:data:: logger

.. py:function:: analyze_docstring_in_blocks(code_blocks: list, file_name: str = 'unknown', file_path: str = 'unknown', language: str = None) -> dict

   Analyzes code blocks to find docstring and identify missing ones.
   Supports multiple programming languages including Python, JavaScript/TypeScript and MATLAB.

   :param code_blocks: List of code blocks extracted from a file
   :type code_blocks: list
   :param file_name: Name of the file being analyzed
   :type file_name: str
   :param language: Programming language of the code blocks
   :type language: str

   :returns: Analysis results with docstring information
   :rtype: dict


.. py:function:: analyze_docstring_in_module(content: str, language: str = None) -> Optional[str]

   Extract module-level docstring from file content.

   :param content: The file content
   :type content: str
   :param language: The programming language
   :type language: str

   :returns: The module docstring if found, None otherwise
   :rtype: str or None


