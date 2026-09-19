import logging

import pytest

@pytest.fixture(autouse=True)
def _reset_audit_logger():
    logger = logging.getLogger("jev_eval.audit")
    logger.handlers.clear()
    logger.propagate = True
    yield
    logger.handlers.clear()
    logger.propagate = True
