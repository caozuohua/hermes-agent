import io
import logging
from agent.sdk_log_redaction import protect_sdk_logger


def test_sdk_handler_and_propagated_record_hide_credentials():
    logger = logging.Logger('Lark-test', logging.INFO)
    output = io.StringIO()
    file_output = io.StringIO()
    parent = logging.Logger('file-sink', logging.INFO)
    parent.addHandler(logging.StreamHandler(file_output))
    logger.parent = parent
    logger.addHandler(logging.StreamHandler(output))
    protect_sdk_logger(logger)
    protect_sdk_logger(logger)
    try:
        raise RuntimeError('wss://example.invalid/ws?ticket=private-query-value')
    except RuntimeError:
        logger.exception('connecting %s Authorization: Bearer %s',
                         'wss://example.invalid/ws?ticket=private-query-value', 'syntheticCredential123456789012345')
    assert 'private-query-value' not in output.getvalue()
    assert 'private-query-value' not in file_output.getvalue()
    assert 'syntheticCredential123456789012345' not in output.getvalue() + file_output.getvalue()
    assert 'example.invalid/ws' in output.getvalue()
