docstring_generation
====================

.. py:module:: docstring_generation


Attributes
----------

.. autoapisummary::

   docstring_generation.logger


Functions
---------

.. autoapisummary::

   docstring_generation.configure_openai
   docstring_generation._clean_json_block
   docstring_generation.create_openai_docstring_prompt
   docstring_generation.generate_docstring_with_openai
   docstring_generation.generate_docstrings_for_code_blocks_openai
   docstring_generation.format_docstring_for_language


Module Contents
---------------

.. py:data:: logger

.. py:function:: configure_openai(api_key: str = None)

   Configure OpenAI API with the provided API key.

   :param api_key: OpenAI API key. If None, reads from environment.
   :type api_key: str, optional


.. py:function:: _clean_json_block(response_text: str) -> str

   Clean JSON response from ChatGPT response.

   :param response_text: Raw response text from API.
   :type response_text: str

   :returns: Cleaned JSON string.
   :rtype: str


.. py:function:: create_openai_docstring_prompt(code: str, language: str = 'python') -> str

   Create a prompt for ChatGPT to generate a concise docstring.

   :param code: The code block to analyze.
   :type code: str
   :param language: Programming language of the code.
   :type language: str

   :returns: Formatted prompt for docstring generation.
   :rtype: str


.. py:function:: generate_docstring_with_openai(code: str, language: str = 'python', api_key: str = None, model: str = 'gpt-4o-mini') -> Optional[str]

   Generate a concise docstring for the given code using OpenAI ChatGPT.

   :param code: The code block for which to generate docstring.
   :type code: str
   :param language: Programming language of the code (default: "python").
   :type language: str
   :param api_key: OpenAI API key.
   :type api_key: str, optional
   :param model: OpenAI model name.
   :type model: str

   :returns: Generated docstring or None if generation fails.
   :rtype: str


.. py:function:: generate_docstrings_for_code_blocks_openai(code_blocks_data: list, language: str = 'python', model: str = 'gpt-3.5-turbo') -> list

   Generate docstrings for multiple code blocks using OpenAI ChatGPT.

   :param code_blocks_data: List of dictionaries containing code block information.
   :type code_blocks_data: list
   :param language: Programming language of the code blocks.
   :type language: str
   :param model: OpenAI model name.
   :type model: str

   :returns: Updated list with generated docstrings.
   :rtype: list


.. py:function:: format_docstring_for_language(docstring: str, language: str) -> str

   Format the generated docstring according to language conventions.

   :param docstring: Raw docstring content.
   :type docstring: str
   :param language: Programming language.
   :type language: str

   :returns: Formatted docstring.
   :rtype: str


