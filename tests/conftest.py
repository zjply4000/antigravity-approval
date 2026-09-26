import logging
import os
import pathlib

import pytest

if hasattr(pathlib, "_NormalAccessor") and hasattr(pathlib._NormalAccessor, "mkdir"):
    pathlib._NormalAccessor.mkdir = staticmethod(pathlib._NormalAccessor.mkdir)


@pytest.fixture(autouse=True)
def _reset_audit_logger():
    logger = logging.getLogger("jev_eval.audit")
    logger.handlers.clear()
    logger.propagate = True
    yield
    logger.handlers.clear()
    logger.propagate = True
