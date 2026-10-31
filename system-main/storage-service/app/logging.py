import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from flask import current_app, g, request


def make_logger(name, path, level):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers: return logger
    handler = RotatingFileHandler(
        filename=path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def write_json_log(logger, event, **fields):
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "INFO",
        "event": event,
        **fields,
    }
    logger.info(json.dumps(record, ensure_ascii=False, default=str))


def configure_logging(app, service_name):
    log_directory = app.config.get("LOG_DIR", "/service/logs")
    os.makedirs(log_directory, exist_ok=True)
    log_level = app.config.get("LOG_LEVEL", "INFO").upper()
    request_logger = make_logger(
        name=f"{service_name}.requests",
        path=os.path.join(log_directory, "requests.log"),
        level=log_level,
    )
    audit_logger = make_logger(name=f"{service_name}.audit", path=os.path.join(log_directory, "audit.log"), level=log_level)
    app.extensions["request_logger"] = request_logger
    app.extensions["audit_logger"] = audit_logger

    @app.before_request
    def start_request_logging():
        g.request_started_at = time.perf_counter()
        supplied_request_id = request.headers.get("X-Request-ID")
        g.request_id = (
            supplied_request_id
            if supplied_request_id
            else uuid.uuid4().hex
        )

    @app.after_request
    def finish_request_logging(response):
        started_at = getattr(g, "request_started_at", time.perf_counter())
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        if request.path not in {
            "/health",
            "/health/live",
            "/health/ready",
        }:
            write_json_log(
                request_logger,
                event="http_request",
                request_id=getattr(g, "request_id", None),
                service=service_name,
                method=request.method,
                path=request.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                caller_service=getattr(g, "caller_service", request.headers.get("X-Service-Name")),
                actor_id=getattr(g, "caller_user", request.headers.get("X-Acting-User-Id")),
                remote_address=request.remote_addr,
                content_length=request.content_length,
            )
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response

    @app.teardown_request
    def log_unhandled_exception(error):
        if error is None: return
        record = {
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "level": "ERROR",
            "event": "unhandled_exception",
            "request_id": getattr(g, "request_id", None),
            "service": service_name,
            "method": request.method,
            "path": request.path,
            "error_type": type(error).__name__,
            "error": str(error),
        }

        request_logger.error(
            json.dumps(
                record,
                ensure_ascii=False,
            ),
            exc_info=(
                type(error),
                error,
                error.__traceback__,
            ),
        )


def audit_event(
    action,
    *,
    entity_type=None,
    entity_id=None,
    outcome="success",
    details=None,
):
    logger = current_app.extensions["audit_logger"]

    write_json_log(
        logger,
        event="audit",
        request_id=getattr(g, "request_id", None),
        caller_service=getattr(g, "caller_service", None),
        actor_id=getattr(g, "caller_user", None),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        outcome=outcome,
        details=details or {},
    )