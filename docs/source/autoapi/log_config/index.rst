log_config
==========

.. py:module:: log_config

.. autoapi-nested-parse::

   Centralized logging configuration.

   Sets up file-based logging with configurable log level and format
   (via environment variables). Suppresses noisy logs from `watchfiles`
   and `uvicorn`. Use `get_logger(name)` to retrieve a module-specific logger.



Attributes
----------

.. autoapisummary::

   log_config.LOG_LEVEL
   log_config.LOG_FORMAT
   log_config.LOG_DIR
   log_config.timestamp
   log_config.LOG_FILE


Functions
---------

.. autoapisummary::

   log_config.get_logger


Module Contents
---------------

.. py:data:: LOG_LEVEL

.. py:data:: LOG_FORMAT
   :value: '%(asctime)s - %(levelname)s - %(name)s - %(message)s'


.. py:data:: LOG_DIR

.. py:data:: timestamp

.. py:data:: LOG_FILE

.. py:function:: get_logger(name: str)

