from flask import (
    Blueprint,
    jsonify,
    current_app,
    request,
    g
)
import httpx
import json
from minio.error import S3Error
from app.decorators import service_required, admin_required, actor_required


bp = Blueprint("models", __name__)


def get_req_body():
    res = request.get_json(silent=True)
    return res if isinstance(res, dict) else None


def load_json_object(object_key):
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]
    response = minio_client.get_object(bucket_name, object_key)
    try:
        return json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()


@bp.post("/models")
@service_required("web-service")
@admin_required
def register_model():
    json_r = get_req_body()
    if not isinstance(json_r, dict): return jsonify(error="Неверный формат тела запроса"), 400
    name = json_r.get("name", "")
    version = json_r.get("version", "")
    url = json_r.get("import_url", "")
    if not name or not version or not url:
        return jsonify(error="Поля не должны быть пустыми"), 400
    
    storage = current_app.extensions["storage_client"]

    try:
        response = storage.create_model(
            actor_id=g.caller_user,
            name=name,
            version=version,
            import_url=url
        )
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code

    return jsonify(model_id=response["id"]), 202


@bp.get("/models/<int:model_id>/hyperparameters")
@service_required("web-service")
@actor_required
def get_hyperparams(model_id):
    storage = current_app.extensions["storage_client"]
    
    try:
        response = storage.get_hyperparams(actor_id=g.caller_user, model_id=model_id)
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code
    
    return jsonify(hyperparameters=response["hyperparameters"]), 200


@bp.post("/models/<int:model_id>/versions")
@service_required("web-service")
@admin_required
def register_version(model_id):

    json_r = get_req_body()
    if not isinstance(json_r, dict): return jsonify(error="Неверный формат тела запроса"), 400
    version = json_r.get("version", "")
    if not version: return jsonify(error="Поле version не должно быть пустым"), 400

    storage = current_app.extensions["storage_client"]
    
    try:
        response = storage.register_version(actor_id=g.caller_user, model_id=model_id, version=version)
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code
    
    return jsonify(model_id=response["id"]), 202


@bp.post("/models/<int:model_id>/runs")
@service_required("web-service")
@admin_required
def create_run(model_id):

    json_r = get_req_body()
    if not isinstance(json_r, dict): return jsonify(error="Неверный формат тела запроса"), 400
    dataset_id = json_r.get("dataset_id", "")
    hyperparams = json_r.get("hyperparameters", "")

    if dataset_id is None or hyperparams is None:
        return jsonify(error="Поле не должно быть пустым"), 400

    if not isinstance(dataset_id, int) or not isinstance(hyperparams, dict):
        return jsonify(error="dataset_id должен быть целым числом, а hyperparams - словарём"), 400

    storage = current_app.extensions["storage_client"]
    
    try:
        response = storage.create_run(actor_id=g.caller_user, model_id=model_id, dataset_id=dataset_id, hyperparameters=hyperparams)
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code
    
    return jsonify(run_id=response["id"]), 202


@bp.post("/runs/<int:run_id>/cancel")
@service_required("web-service")
@admin_required
def cancel_run(run_id):
    storage = current_app.extensions["storage_client"]
    
    try:
        response = storage.request_run_cancel(actor_id=g.caller_user, run_id=run_id)
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code
    
    return jsonify(run_id=response["id"]), 200


@bp.get("/runs/<int:run_id>/progress")
@service_required("web-service")
@actor_required
def get_progress(run_id):
    storage = current_app.extensions["storage_client"]
    
    try:
        response = storage.get_progress(actor_id=g.caller_user, run_id=run_id)
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось зарегистрировать модель"), error.response.status_code
    
    return jsonify(status=response["status"], progress=response["progress"]), 200


@bp.get("/runs/<int:run_id>/misclassified-examples")
@service_required("web-service")
@actor_required
def get_misclassified(run_id):
    limit_per_pair = request.args.get(
        "limit_per_pair",
        default=4,
        type=int,
    )

    if (
        limit_per_pair is None
        or limit_per_pair < 1
        or limit_per_pair > 100
    ):
        return jsonify(error="limit_per_pair должен находиться в диапазоне [1, 100]"), 400

    storage = current_app.extensions["storage_client"]
    try:
        run = storage.get_run_info(
            actor_id=g.caller_user,
            run_id=run_id,
        )
    except httpx.TimeoutException:
        return jsonify(error="Storage временно недоступен"), 503
    except httpx.RequestError:
        return jsonify(error="Не удалось подключиться к Storage"), 502
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось получить информацию о запуске"), error.response.status_code

    if run is None: return jsonify(error="Запуск не найден"), 404
    if run["status"] != "completed":
        return jsonify(error="Ошибочные примеры доступны только для завершённого запуска"), 409
    results_path = run.get("results_path")
    if not results_path: return jsonify(error="У запуска отсутствует путь к результатам"), 409

    try:
        artifacts = load_json_object(results_path)
        misclassified_path = artifacts.get("misclassified_path")
        if not isinstance(misclassified_path, str): return jsonify(error="В артефактах отсутствует misclassified_path"), 500
        misclassified = load_json_object(misclassified_path)

    except S3Error:
        current_app.logger.exception("Не удалось прочитать ошибочные примеры запуска %s", run_id)
        return jsonify(error="Не удалось загрузить ошибочные примеры из MinIO"), 502
    except (UnicodeDecodeError, json.JSONDecodeError):
        current_app.logger.exception("Некорректный файл ошибочных примеров запуска %s", run_id)
        return jsonify(error="Файл ошибочных примеров повреждён"), 500

    result = []
    for group in misclassified.get("groups", []):
        selected_ids = group.get("item_ids", [])[:limit_per_pair]
        result.append({
            "true_label": group["true_label"],
            "predicted_label": group["predicted_label"],
            "images": [{"item_id": item_id}for item_id in selected_ids]
        })

    return jsonify(result), 200