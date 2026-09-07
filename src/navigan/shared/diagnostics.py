"""Safe phase diagnostics: never log SQL, parameters, tokens or exception messages."""
import json
import logging
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_context = ContextVar("diagnostic_context", default={})


def emit(stage, status, **fields):
    logger.info(json.dumps({**_context.get(), "stage": stage, "status": status, **fields}))


@contextmanager
def phase(stage, **fields):
    started = time.monotonic()
    emit(stage, "started", **fields)
    try:
        yield
    except Exception as error:
        emit(stage, "failed", elapsedMs=round((time.monotonic()-started)*1000, 2),
             errorType=type(error).__name__, sqlState=getattr(error, "sqlstate", None),
             locations=[{"file": f.filename.rsplit("/", 1)[-1], "line": f.lineno, "function": f.name}
                        for f in traceback.extract_tb(error.__traceback__)][-8:],
             awsErrorCode=(getattr(error, "response", {}) or {}).get("Error", {}).get("Code"), **fields)
        raise
    else:
        emit(stage, "completed", elapsedMs=round((time.monotonic()-started)*1000, 2), **fields)


def invocation(handler):
    @wraps(handler)
    def wrapped(event, context):
        token = _context.set({"requestId": getattr(context, "aws_request_id", None),
                              "gatewayRequestId": event.get("requestContext", {}).get("requestId")})
        try:
            with phase("invocation"):
                result = handler(event, context)
                emit("response", "completed", statusCode=result.get("statusCode"))
                return result
        finally:
            _context.reset(token)
    return wrapped
