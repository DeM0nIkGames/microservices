from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
)
from psycopg.types.json import Jsonb
from app.logging import audit_event
from app.decorators import admin_required, service_required


results_bp = Blueprint("results", __name__, url_prefix="/results")

bp = Blueprint("runs", __name__, url_prefix="/runs")

internal_bp = Blueprint("internal_runs", __name__, url_prefix="/internal/runs")


RUN_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
}


def check_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def serialize_datetime(value): return value.isoformat() if value is not None else None


RUN_SELECT = """
    SELECT
        model_runs.id,
        model_runs.model_id,
        models.name,
        models.version,
        model_runs.dataset_id,
        datasets.name,
        model_runs.user_id,
        model_runs.seed,
        model_runs.hyperparameters,
        model_runs.split_config,
        model_runs.progress,
        model_runs.metrics,
        model_runs.results_path,
        model_runs.status,
        model_runs.error_message,
        model_runs.worker_id,
        model_runs.created_at,
        model_runs.started_at,
        model_runs.finished_at
    FROM model_runs
    JOIN models
        ON models.id = model_runs.model_id
    JOIN datasets
        ON datasets.id = model_runs.dataset_id
"""


def serialize_run(row):
    return {
        "id": row[0],

        "model_id": row[1],
        "model_name": row[2],
        "model_version": row[3],

        "dataset_id": row[4],
        "dataset_name": row[5],

        "user_id": row[6],
        "seed": row[7],

        "hyperparameters": row[8],
        "split_config": row[9],
        "progress": row[10],
        "metrics": row[11],

        "results_path": row[12],
        "status": row[13],
        "error_message": row[14],
        "worker_id": row[15],

        "created_at": serialize_datetime(row[16]),
        "started_at": serialize_datetime(row[17]),
        "finished_at": serialize_datetime(row[18]),
    }


@results_bp.get("")
@service_required("web-service")
def get_runs():
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            rows = cur.execute(
                RUN_SELECT
                + """
                ORDER BY
                    model_runs.created_at DESC,
                    model_runs.id DESC
                """
            ).fetchall()

    runs = [serialize_run(row) for row in rows]
    return jsonify(runs), 200


@bp.get("/<int:run_id>")
@service_required("web-service", "ml-service", "visualization-service")
def get_run(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                RUN_SELECT
                + """
                WHERE model_runs.id = %s
                """,
                (run_id,),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    return jsonify(serialize_run(row)), 200


@bp.get("/<int:run_id>/progress")
@service_required("ml-service")
def get_run_progress(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT status, progress
                FROM model_runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    return jsonify(status=row[0], progress=row[1]), 200


@bp.post("/<int:run_id>/cancel")
@service_required("ml-service")
@admin_required
def cancel_run(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT status
                FROM model_runs
                WHERE id = %s
                FOR UPDATE
                """,
                (run_id,),
            ).fetchone()

            if row is None: return jsonify(error="Запуск не найден"), 404
            current_status = row[0]
            if current_status not in {"queued", "running"}: 
                return jsonify(error="Можно отменить только запуск со статусом queued или running"), 409

            cur.execute(
                """
                UPDATE model_runs
                SET
                    status = 'cancelled',
                    finished_at = NOW()
                WHERE id = %s
                """,
                (run_id,),
            )
    audit_event(
        "run.cancelled_by_user",
        entity_type="model_run",
        entity_id=run_id,
        details={
            "old_status": current_status,
            "new_status": "cancelled",
        },
    )
    return jsonify(id=run_id, status="cancelled"), 200


@bp.post("/<int:run_id>/delete")
@service_required("web-service")
@admin_required
def delete_run(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                DELETE FROM model_runs
                WHERE id = %s
                RETURNING id
                """,
                (run_id,),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    audit_event(
        "run.deleted",
        entity_type="model_run",
        entity_id=run_id,
    )
    return "", 204


@internal_bp.post("/claim")
@service_required("ml-service")
def claim_run():
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    worker_id = body.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip(): return jsonify(error="worker_id должен быть непустой строкой"), 400

    worker_id = worker_id.strip()
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                WITH selected_run AS (
                    SELECT id
                    FROM model_runs
                    WHERE status = 'queued'
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE model_runs
                SET
                    status = 'running',
                    worker_id = %s,
                    started_at = NOW(),
                    error_message = NULL
                FROM selected_run
                WHERE model_runs.id = selected_run.id
                RETURNING model_runs.id
                """,
                (worker_id,),
            ).fetchone()

    if row is None: return "", 204
    return jsonify(id=row[0]), 200


@internal_bp.get("/<int:run_id>")
@service_required("ml-service")
def get_internal_run(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT
                    id,
                    model_id,
                    dataset_id,
                    user_id,
                    seed,
                    hyperparameters,
                    split_config,
                    progress,
                    metrics,
                    results_path,
                    status,
                    error_message,
                    worker_id,
                    created_at,
                    started_at,
                    finished_at
                FROM model_runs
                WHERE id = %s
                """,
                (run_id,),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    return jsonify(
        id=row[0],
        model_id=row[1],
        dataset_id=row[2],
        user_id=row[3],
        seed=row[4],
        hyperparameters=row[5],
        split_config=row[6],
        progress=row[7],
        metrics=row[8],
        results_path=row[9],
        status=row[10],
        error_message=row[11],
        worker_id=row[12],
        created_at=serialize_datetime(row[13]),
        started_at=serialize_datetime(row[14]),
        finished_at=serialize_datetime(row[15]),
    ), 200


@internal_bp.patch("/<int:run_id>/progress")
@service_required("ml-service")
def update_run_progress(run_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    progress = body.get("progress")
    if not isinstance(progress, dict): return jsonify(error="progress должен быть JSON-объектом"), 400
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE model_runs
                SET progress = %s
                WHERE id = %s
                RETURNING id
                """,
                (
                    Jsonb(progress),
                    run_id,
                ),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    return "", 204


@internal_bp.post("/<int:run_id>/complete")
@service_required("ml-service")
def complete_run(run_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    metrics = body.get("metrics")
    results_path = body.get("results_path")
    if not isinstance(metrics, dict): return jsonify(error="metrics должен быть JSON-объектом"), 400

    if not isinstance(results_path, str) or not results_path.strip():
        return jsonify(error="results_path должен быть непустой строкой"), 400

    results_path = results_path.strip()
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE model_runs
                SET
                    status = 'completed',
                    metrics = %s,
                    results_path = %s,
                    finished_at = NOW(),
                    error_message = NULL
                WHERE id = %s
                RETURNING id
                """,
                (
                    Jsonb(metrics),
                    results_path,
                    run_id,
                ),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    audit_event(
        "run.completed",
        entity_type="model_run",
        entity_id=run_id,
        details={
            "results_path": results_path,
            "status": "completed",
        },
    )
    return "", 204


@internal_bp.post("/<int:run_id>/cancelled")
@service_required("ml-service")
def mark_run_cancelled(run_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE model_runs
                SET
                    status = 'cancelled',
                    finished_at = COALESCE(finished_at, NOW())
                WHERE id = %s
                RETURNING id
                """,
                (run_id,),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    audit_event(
        "run.marked_cancelled",
        entity_type="model_run",
        entity_id=run_id,
        details={
            "status": "cancelled",
        },
    )
    return "", 204


@internal_bp.post("/<int:run_id>/fail")
@service_required("ml-service")
def fail_run(run_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400
    error_message = body.get("error_message")

    if not isinstance(error_message, str) or not error_message.strip():
        return jsonify(error="error_message должен быть непустой строкой"), 400

    error_message = error_message.strip()
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE model_runs
                SET
                    status = 'failed',
                    error_message = %s,
                    finished_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (
                    error_message,
                    run_id,
                ),
            ).fetchone()

    if row is None: return jsonify(error="Запуск не найден"), 404
    audit_event(
        "run.failed",
        entity_type="model_run",
        entity_id=run_id,
        outcome="failed",
        details={
            "status": "failed",
            "error_message": error_message,
        },
    )
    return "", 204