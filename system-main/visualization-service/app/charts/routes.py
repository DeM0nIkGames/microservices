from flask import (
    Blueprint,
    request,
    jsonify,
    current_app
)
import json, httpx
from app.decorators import service_required
from minio.error import S3Error
from app.charts.builders import build_charts, calculate_threshold_analysis

bp = Blueprint("charts", __name__)


def load_json_object(object_key):
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]

    response = minio_client.get_object(bucket_name, object_key)

    try:
        return json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()


@bp.get("/runs/<int:run_id>/charts")
@service_required("web-service")
def get_charts(run_id):
    actor_id = request.headers.get("X-Acting-User-Id", type=int)
    mode = request.args.get("mode", "manual")
    percentile = request.args.get("percentile", 95, type=int)

    if actor_id is None or actor_id <= 0: return jsonify(error="Некорректный X-Acting-User-Id"), 400
    if mode not in {"manual", "auto"}: return jsonify(error="Некорректный режим подбора порога"), 400
    if not 1 <= percentile <= 100: return jsonify(error="Перцентиль должен быть от 1 до 100"), 400

    storage = current_app.extensions["storage_client"]

    try:
        run = storage.get_run_info(
            actor_id=actor_id,
            run_id=run_id,
        )
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.RequestError:
        return jsonify(error="Не удалось получить данные запуска"), 502

    if run is None:
        return jsonify(error="Запуск не найден"), 404

    if run["status"] != "completed":
        return jsonify(
            error="Графики будут доступны после завершения запуска"
        ), 409

    try:
        artifacts = load_json_object(run["results_path"])

        scores_path = artifacts.get("scores_path")
        if not scores_path:
            return jsonify(
                error="Для запуска не сохранены anomaly score"
            ), 409
        scores_document = load_json_object(scores_path)

        analysis = calculate_threshold_analysis(
            scores_document=scores_document,
            percentile=percentile,
            mode=mode,
        )

        dynamic_artifacts = {
            **artifacts,
            "metrics": analysis["metrics"],
            "confusion_matrix": analysis["confusion_matrix"],
            "per_class": analysis["per_class"],
        }
        charts = build_charts(dynamic_artifacts)

    except (S3Error, ValueError, KeyError):
        current_app.logger.exception("Не удалось построить анализ запуска")
        return jsonify(error="Не удалось пересчитать результаты"), 502

    return jsonify(
        run_id=run_id,
        threshold=analysis["threshold"],
        percentile=analysis["percentile"],
        mode=analysis["mode"],
        metrics=analysis["metrics"],
        misclassified=analysis["misclassified"],
        charts=charts,
    ), 200