from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    request,
)
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from app.logging import audit_event
from app.decorators import admin_required, service_required


bp = Blueprint("models", __name__, url_prefix="/models")

internal_bp = Blueprint("internal_models", __name__, url_prefix="/internal/models")


MODEL_STATUSES = {
    "pending_validation",
    "validating",
    "validated",
    "failed",
    "disabled",
}


MODEL_SELECT = """
    SELECT
        id,
        user_id,
        name,
        version,
        import_url,
        status,
        metadata,
        error_message,
        validation_worker_id,
        validation_started_at,
        validated_at,
        created_at
    FROM models
"""


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
        model_runs.created_at,
        model_runs.started_at,
        model_runs.finished_at
    FROM model_runs
    JOIN models
        ON models.id = model_runs.model_id
    JOIN datasets
        ON datasets.id = model_runs.dataset_id
"""


def check_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def serialize_datetime(value):
    return value.isoformat() if value is not None else None


def serialize_model(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "name": row[2],
        "version": row[3],
        "import_url": row[4],
        "status": row[5],
        "metadata": row[6],
        "error_message": row[7],
        "validation_worker_id": row[8],
        "validation_started_at": serialize_datetime(row[9]),
        "validated_at": serialize_datetime(row[10]),
        "created_at": serialize_datetime(row[11]),
    }


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
        "created_at": serialize_datetime(row[15]),
        "started_at": serialize_datetime(row[16]),
        "finished_at": serialize_datetime(row[17]),
    }


@bp.get("")
@service_required("web-service")
def get_models():
    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            rows = cur.execute(
                MODEL_SELECT
                + """
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()

    models = [serialize_model(row) for row in rows]
    return jsonify(models), 200


@bp.post("")
@service_required("ml-service")
@admin_required
def create_model():
    body = check_body()

    if body is None:
        return jsonify(
            error="Тело запроса должно быть JSON-объектом"
        ), 400

    name = body.get("name")
    version = body.get("version")
    import_url = body.get("import_url")

    if not isinstance(name, str) or not name.strip():
        return jsonify(
            error="Название модели должно быть непустой строкой"
        ), 400

    if not isinstance(version, str) or not version.strip():
        return jsonify(
            error="Версия модели должна быть непустой строкой"
        ), 400

    if not isinstance(import_url, str) or not import_url.strip():
        return jsonify(
            error="import_url должен быть непустой строкой"
        ), 400

    name = name.strip()
    version = version.strip()
    import_url = import_url.strip()

    if not import_url.lower().startswith(("http://", "https://")):
        return jsonify(
            error="import_url должен начинаться с http:// или https://"
        ), 400

    pool = current_app.extensions["db_pool"]
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                row = cur.execute(
                    """
                    INSERT INTO models (
                        user_id,
                        name,
                        version,
                        import_url,
                        status,
                        metadata
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        'pending_validation',
                        '{}'::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        g.caller_user,
                        name,
                        version,
                        import_url,
                    ),
                ).fetchone()
    except UniqueViolation: return jsonify(error="Модель с таким названием и версией уже существует"), 409
    audit_event(
        "model.created",
        entity_type="model",
        entity_id=row[0],
        details={
            "name": name,
            "version": version,
            "status": "pending_validation",
        },
    )
    return jsonify(id=row[0]), 201


@bp.get("/<int:model_id>")
@service_required("web-service", "ml-service")
def get_model(model_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                MODEL_SELECT
                + """
                WHERE id = %s
                """,
                (model_id,),
            ).fetchone()

    if row is None: return jsonify(error="Модель не найдена"), 404
    return jsonify(serialize_model(row)), 200


@bp.get("/<int:model_id>/hyperparameters")
@service_required("ml-service")
def get_model_hyperparameters(model_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT metadata
                FROM models
                WHERE id = %s
                """,
                (model_id,),
            ).fetchone()

    if row is None: return jsonify(error="Модель не найдена"), 404
    metadata = row[0] or {}
    hyperparameters = metadata.get("hyperparameters", [])

    return jsonify(hyperparameters=hyperparameters), 200


@bp.post("/<int:model_id>/versions")
@service_required("ml-service")
@admin_required
def create_model_version(model_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    version = body.get("version")
    if not isinstance(version, str) or not version.strip(): return jsonify(error="Версия должна быть непустой строкой"), 400

    version = version.strip()
    pool = current_app.extensions["db_pool"]
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                source_model = cur.execute(
                    """
                    SELECT
                        user_id,
                        name,
                        import_url
                    FROM models
                    WHERE id = %s
                    """,
                    (model_id,),
                ).fetchone()

                if source_model is None: return jsonify(error="Модель не найдена"), 404
                user_id, name, import_url = source_model
                row = cur.execute(
                    """
                    INSERT INTO models (
                        user_id,
                        name,
                        version,
                        import_url,
                        status,
                        metadata
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        'pending_validation',
                        '{}'::jsonb
                    )
                    RETURNING id
                    """,
                    (
                        user_id,
                        name,
                        version,
                        import_url,
                    ),
                ).fetchone()

    except UniqueViolation: return jsonify(error="Такая версия модели уже зарегистрирована"), 409
    audit_event(
        "model.version_created",
        entity_type="model",
        entity_id=row[0],
        details={
            "source_model_id": model_id,
            "name": name,
            "version": version,
        },
    )
    return jsonify(id=row[0]), 201


@bp.get("/<int:model_id>/runs")
@service_required("web-service")
def get_model_runs(model_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            model = cur.execute(
                """
                SELECT id
                FROM models
                WHERE id = %s
                """,
                (model_id,),
            ).fetchone()

            if model is None: return jsonify(error="Модель не найдена"), 404
            rows = cur.execute(
                RUN_SELECT
                + """
                WHERE model_runs.model_id = %s
                ORDER BY model_runs.created_at DESC,
                         model_runs.id DESC
                """,
                (model_id,),
            ).fetchall()

    runs = [serialize_run(row) for row in rows]
    return jsonify(runs), 200


@bp.post("/<int:model_id>/runs")
@service_required("ml-service")
@admin_required
def create_model_run(model_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    dataset_id = body.get("dataset_id")
    hyperparameters = body.get("hyperparameters")
    if (
        isinstance(dataset_id, bool)
        or not isinstance(dataset_id, int)
    ): return jsonify(error="dataset_id должен быть целым числом"), 400
    if not isinstance(hyperparameters, dict): return jsonify(error="hyperparameters должен быть JSON-объектом"), 400

    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            model = cur.execute(
                """
                SELECT status
                FROM models
                WHERE id = %s
                """,
                (model_id,),
            ).fetchone()

            if model is None: return jsonify(error="Модель не найдена"), 404
            if model[0] != "validated": return jsonify(error="Модель ещё не прошла валидацию"), 409

            dataset = cur.execute(
                """
                SELECT train_percent
                FROM datasets
                WHERE id = %s
                """,
                (dataset_id,),
            ).fetchone()
            if dataset is None: return jsonify(error="Датасет не найден"), 404

            split_config = {"train_percent": dataset[0]}
            row = cur.execute(
                """
                INSERT INTO model_runs (
                    model_id,
                    dataset_id,
                    user_id,
                    hyperparameters,
                    split_config,
                    progress,
                    metrics,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    'queued'
                )
                RETURNING id
                """,
                (
                    model_id,
                    dataset_id,
                    g.caller_user,
                    Jsonb(hyperparameters),
                    Jsonb(split_config),
                ),
            ).fetchone()
    audit_event(
        "run.created",
        entity_type="model_run",
        entity_id=row[0],
        details={
            "model_id": model_id,
            "dataset_id": dataset_id,
            "status": "queued",
        },
    )
    return jsonify(id=row[0]), 201


@bp.post("/<int:model_id>/delete")
@service_required("web-service")
@admin_required
def delete_model(model_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                DELETE FROM models
                WHERE id = %s
                RETURNING id
                """,
                (model_id,),
            ).fetchone()

    if row is None: return jsonify(error="Модель не найдена"), 404
    audit_event(
        "model.deleted",
        entity_type="model",
        entity_id=model_id,
    )
    return "", 204


@bp.post("/<int:model_id>/revalidate")
@service_required("web-service")
@admin_required
def revalidate_model(model_id):
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT status
                FROM models
                WHERE id = %s
                FOR UPDATE
                """,
                (model_id,),
            ).fetchone()

            if row is None: return jsonify(error="Модель не найдена"), 404
            current_status = row[0]
            if current_status in {"pending_validation", "validating"}:
                return jsonify(error=("Модель уже ожидает валидации или валидируется")), 409

            cur.execute(
                """
                UPDATE models
                SET
                    status = 'pending_validation',
                    metadata = '{}'::jsonb,
                    error_message = NULL,
                    validation_worker_id = NULL,
                    validation_started_at = NULL,
                    validated_at = NULL
                WHERE id = %s
                """,
                (model_id,),
            )
    audit_event(
        "model.revalidation_requested",
        entity_type="model",
        entity_id=model_id,
        details={
            "old_status": current_status,
            "new_status": "pending_validation",
        },
    )
    return jsonify(id=model_id, status="pending_validation"), 200


@internal_bp.post("/claim-validation")
@service_required("ml-service")
def claim_model_for_validation():
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
                WITH selected_model AS (
                    SELECT id
                    FROM models
                    WHERE status = 'pending_validation'
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE models
                SET
                    status = 'validating',
                    validation_worker_id = %s,
                    validation_started_at = NOW(),
                    error_message = NULL
                FROM selected_model
                WHERE models.id = selected_model.id
                RETURNING
                    models.id,
                    models.name,
                    models.version,
                    models.import_url
                """,
                (worker_id,),
            ).fetchone()

    if row is None: return "", 204
    audit_event(
        "model.validation_claimed",
        entity_type="model",
        entity_id=row[0],
        details={
            "worker_id": worker_id,
            "status": "validating",
        },
    )
    return jsonify(id=row[0], name=row[1], version=row[2], import_url=row[3]), 200


@internal_bp.patch("/<int:model_id>/metadata")
@service_required("ml-service")
def update_model_metadata(model_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    metadata = body.get("metadata")
    if not isinstance(metadata, dict): return jsonify(error="metadata должен быть JSON-объектом"), 400
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE models
                SET metadata = %s
                WHERE id = %s
                RETURNING id
                """,
                (
                    Jsonb(metadata),
                    model_id,
                ),
            ).fetchone()

    if row is None: return jsonify(error="Модель не найдена"), 404
    audit_event(
        "model.metadata_updated",
        entity_type="model",
        entity_id=model_id,
        details={
            "metadata_fields": sorted(metadata.keys()),
        },
    )
    return "", 204


@internal_bp.patch("/<int:model_id>/status")
@service_required("ml-service")
def update_model_status(model_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    status = body.get("status")
    error_message = body.get("error_message")
    if status not in {"validated", "failed"}: return jsonify(error="Допустимые статусы: validated и failed"), 400

    if error_message is not None and not isinstance(error_message, str):
        return jsonify(error="error_message должен быть строкой или null"), 400

    if status == "validated": error_message = None
    pool = current_app.extensions["db_pool"]
    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                UPDATE models
                SET
                    status = %s,
                    error_message = %s,
                    validated_at = CASE
                        WHEN %s = 'validated' THEN NOW()
                        ELSE NULL
                    END,
                    validation_worker_id = NULL
                WHERE id = %s
                RETURNING id
                """,
                (
                    status,
                    error_message,
                    status,
                    model_id,
                ),
            ).fetchone()

    if row is None: return jsonify(error="Модель не найдена"), 404
    audit_event(
        "model.status_updated",
        entity_type="model",
        entity_id=model_id,
        outcome="failed" if status == "failed" else "success",
        details={
            "status": status,
            "error_message": error_message,
        },
    )
    return "", 204