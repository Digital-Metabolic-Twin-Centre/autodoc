import logging

from config.log_config import _configure_root_logger, _SecretRedactingFilter


def test_configure_root_logger_adds_stream_handler_when_none_present():
    root_logger = logging.getLogger()
    saved_handlers = list(root_logger.handlers)
    root_logger.handlers = []

    try:
        result = _configure_root_logger()

        assert result is root_logger
        assert len(root_logger.handlers) == 1
        stream_handler = root_logger.handlers[0]
        assert isinstance(stream_handler, logging.StreamHandler)
        assert any(isinstance(f, _SecretRedactingFilter) for f in stream_handler.filters)
    finally:
        root_logger.handlers = saved_handlers
