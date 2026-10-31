import math
import httpx
from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    request,
)
from psycopg.types.json import Jsonb
from app.logging import audit_event
from app.decorators import admin_required, service_required


bp = Blueprint("datasets", __name__, url_prefix="/datasets")


def check_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else None


def validate_dataset_maps(class_labels, class_counts, train_percent):
    if not isinstance(class_labels, dict): return "class_labels должен быть JSON-объектом"
    if not isinstance(class_counts, dict): return "class_counts должен быть JSON-объектом"
    if not isinstance(train_percent, dict): return "train_percent должен быть JSON-объектом"

    label_keys = set(class_labels.keys())
    count_keys = set(class_counts.keys())
    percent_keys = set(train_percent.keys())

    if not label_keys: return "Датасет должен содержать хотя бы один класс"

    if label_keys != count_keys or label_keys != percent_keys:
        return "class_labels, class_counts и train_percent должны содержать одинаковые классы"

    for class_id, label in class_labels.items():
        if not isinstance(class_id, str): return "Идентификаторы классов должны быть строками"

        if not isinstance(label, str) or not label.strip(): return f"Название класса {class_id} должно быть непустой строкой"

    for class_id, count in class_counts.items():
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0):
            return (f"Число изображений класса {class_id} должно быть неотрицательным целым числом")

    for class_id, value in train_percent.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1):
            return (f"Доля тренировочной выборки класса {class_id} должна находиться в диапазоне [0, 1]")

    return None


def serialize_dataset(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "name": row[2],
        "manifest_path": row[3],
        "train_percent": row[4],
        "class_labels": row[5],
        "class_counts": row[6],
        "created_at": (
            row[7].isoformat()
            if row[7] is not None
            else None
        ),
    }


@bp.get("")
@service_required("web-service")
def get_datasets():
    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            rows = cur.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    manifest_path,
                    train_percent,
                    class_labels,
                    class_counts,
                    created_at
                FROM datasets
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()

    datasets = [serialize_dataset(row) for row in rows]
    return jsonify(datasets), 200


@bp.post("")
@service_required("collector-service")
@admin_required
def create_dataset():
    body = check_body()

    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    name = body.get("name")
    manifest_path = body.get("manifest_path")
    class_labels = body.get("class_labels")
    class_counts = body.get("class_counts")
    train_percent = body.get("train_percent")

    if not isinstance(name, str) or not name.strip(): return jsonify(error="Название датасета должно быть непустой строкой"), 400

    if (
        not isinstance(manifest_path, str)
        or not manifest_path.strip()
    ):
        return jsonify(error="manifest_path должен быть непустой строкой"), 400

    name = name.strip()
    manifest_path = manifest_path.strip()

    validation_error = validate_dataset_maps(
        class_labels=class_labels,
        class_counts=class_counts,
        train_percent=train_percent,
    )

    if validation_error is not None: return jsonify(error=validation_error), 400

    class_labels = {
        class_id: label.strip()
        for class_id, label in class_labels.items()
    }

    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                INSERT INTO datasets (
                    user_id,
                    name,
                    manifest_path,
                    train_percent,
                    class_labels,
                    class_counts
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    g.caller_user,
                    name,
                    manifest_path,
                    Jsonb(train_percent),
                    Jsonb(class_labels),
                    Jsonb(class_counts),
                ),
            ).fetchone()

    audit_event(
        "dataset.created",
        entity_type="dataset",
        entity_id=row[0],
        details={
            "name": name,
            "classes_count": len(class_labels),
            "images_count": sum(class_counts.values()),
        },
    )
    return jsonify(id=row[0]), 201


@bp.get("/<int:dataset_id>")
@service_required(
    "web-service",
    "collector-service",
    "ml-service",
)
def get_dataset(dataset_id):
    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT
                    id,
                    user_id,
                    name,
                    manifest_path,
                    train_percent,
                    class_labels,
                    class_counts,
                    created_at
                FROM datasets
                WHERE id = %s
                """,
                (dataset_id,),
            ).fetchone()

    if row is None: return jsonify(error="Датасет не найден"), 404

    return jsonify(serialize_dataset(row)), 200


@bp.post("/<int:dataset_id>/settings")
@service_required("web-service")
@admin_required
def update_dataset_settings(dataset_id):
    body = check_body()

    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    train_percent = body.get("train_percent")

    if not isinstance(train_percent, dict): return jsonify(error="train_percent должен быть JSON-объектом"), 400

    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT class_labels
                FROM datasets
                WHERE id = %s
                """,
                (dataset_id,),
            ).fetchone()

            if row is None: return jsonify(error="Датасет не найден"), 404

            class_labels = row[0]

            if set(train_percent.keys()) != set(class_labels.keys()): return jsonify(error="Передан неверный набор классов"), 400

            for class_id, value in train_percent.items():
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or not 0 <= value <= 1
                ):
                    return jsonify(
                        error=(
                            "Доля тренировочной выборки класса "
                            f"{class_id} должна находиться "
                            "в диапазоне [0, 1]"
                        )
                    ), 400

            cur.execute(
                """
                UPDATE datasets
                SET train_percent = %s
                WHERE id = %s
                """,
                (
                    Jsonb(train_percent),
                    dataset_id,
                ),
            )

    audit_event(
        "dataset.train_percent_updated",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "train_percent": train_percent,
        },
    )
    return "", 204


@bp.post("/<int:dataset_id>/classes/<int:class_id>")
@service_required("web-service")
@admin_required
def update_class_label(dataset_id, class_id):
    body = check_body()
    if body is None: return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    label = body.get("label")
    if not isinstance(label, str) or not label.strip(): return jsonify(error="Название класса должно быть непустой строкой"), 400

    label = label.strip()
    class_key = str(class_id)
    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT class_labels
                FROM datasets
                WHERE id = %s
                """,
                (dataset_id,),
            ).fetchone()

            if row is None: return jsonify(error="Датасет не найден"), 404
            class_labels = row[0]
            if class_key not in class_labels: return jsonify(error="Класс не найден"), 404
            class_labels[class_key] = label

            cur.execute(
                """
                UPDATE datasets
                SET class_labels = %s
                WHERE id = %s
                """,
                (
                    Jsonb(class_labels),
                    dataset_id,
                ),
            )

    audit_event(
        "dataset.class_label_updated",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "class_id": class_id,
            "new_label": label,
        },
    )
    return "", 204


@bp.post("/<int:dataset_id>/delete")
@service_required("web-service")
@admin_required
def delete_dataset(dataset_id):
    pool = current_app.extensions["db_pool"]

    with pool.connection() as conn:
        with conn.cursor() as cur:
            row = cur.execute(
                """
                SELECT manifest_path
                FROM datasets
                WHERE id = %s
                """,
                (dataset_id,),
            ).fetchone()

    if row is None: return jsonify(error="Датасет не найден"), 404

    manifest_path = row[0]
    collector = current_app.extensions["collector_client"]

    try:
        collector.delete_dataset(
            actor_id=g.caller_user,
            dataset_id=dataset_id,
            manifest_key=manifest_path,
        )
    except httpx.TimeoutException:
        return jsonify(error="Collector временно недоступен"), 503
    except httpx.HTTPStatusError:
        current_app.logger.exception("Collector не смог удалить файлы датасета %s", dataset_id)
        return jsonify(error="Не удалось удалить файлы датасета"), 502

    with pool.connection() as conn:
        with conn.cursor() as cur:
            deleted = cur.execute(
                """
                DELETE FROM datasets
                WHERE id = %s
                RETURNING id
                """,
                (dataset_id,),
            ).fetchone()

    if deleted is None: return jsonify(error="Датасет уже был удалён"), 404
    
    audit_event(
        "dataset.deleted",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "manifest_path": manifest_path,
        },
    )
    return "", 204