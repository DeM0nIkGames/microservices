from flask import (
    Blueprint, 
    request, 
    redirect, 
    render_template,
    current_app,
    abort,
    flash,
    url_for,
)
from flask_login import current_user, login_required
import httpx
import json
import re

bp = Blueprint("models", __name__, url_prefix="/models")


def prepare_hyperparameters(payload):
    parameters = []
    for parameter in payload.get("hyperparameters", []):
        parameter_type = {
            "int": "integer",
            "float": "number",
            "enum": "enum",
        }.get(parameter["type"], parameter["type"])

        parameters.append({
            **parameter,
            "label": parameter["name"],
            "help": parameter.get("description"),
            "type": parameter_type,
            "choices": parameter.get("enum_values"),
            "value": parameter.get("default"),
        })
    return parameters


def prepare_run(run):
    progress_data = run.get("progress") or {}
    metrics = run.get("metrics") or {}
    main_metrics = (metrics.get("test") or metrics.get("train") or {})
    percent = float(progress_data.get("percent", 0))

    return {
        **run,
        "display_id": run["id"],
        "progress": max(0.0, min(1.0, percent / 100)),
        "epoch": progress_data.get("current_epoch"),
        "total_epochs": progress_data.get("total_epochs"),
        "accuracy": main_metrics.get("accuracy"),
        "roc_auc": main_metrics.get("roc_auc"),
    }


@bp.get("/<int:model_id>")
@login_required
def detail(model_id):
    storage = current_app.extensions["storage_client"]
    ml_service = current_app.extensions["ml_client"]
    try:
        model = storage.get_model_info(actor_id=current_user.id, model_id=model_id)
    except httpx.HTTPStatusError:
        flash("Не удалось загрузить модель.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.RequestError:
        flash("Сервис хранения временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))

    if model is None: abort(404)

    metadata = model.get("metadata") or {}
    model = {**model, "task_type": metadata.get("task_type", "classification")}
    try:
        hyperparameters_payload = ml_service.get_hyperparameters(actor_id=current_user.id, model_id=model_id)
        raw_runs = storage.get_model_runs(actor_id=current_user.id, model_id=model_id)
        datasets = storage.get_datasets(actor_id=current_user.id)
    except httpx.HTTPStatusError:
        flash("Не удалось загрузить параметры или запуски модели.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.RequestError:
        flash("Один из сервисов временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))

    hyperparameters = prepare_hyperparameters(hyperparameters_payload)
    runs = [prepare_run(run) for run in raw_runs]
    return render_template(
        "instances/model.html",
        user=current_user,
        model=model,
        hyperparameters=hyperparameters,
        runs=runs,
        datasets=datasets,
    )


@bp.post("")
@login_required
def create_model():
    name = request.form.get("name", "").strip()
    version = request.form.get("version", "").strip()
    import_url = request.form.get("import_url", "").strip()

    if not name or not version or not import_url:
        flash("Заполните необходимые поля", "error")
        return redirect(url_for("main.dashboard"))

    if not import_url.lower().startswith(("https://", "http://")):
        flash("URL должен начинаться с http:// или https://", "error")
        return redirect(url_for("main.dashboard"))

    ml_service = current_app.extensions["ml_client"]

    try:
        result = ml_service.register_model(
            actor_id=current_user.id,
            name=name,
            version=version,
            import_url=import_url)
    except httpx.TimeoutException:
        flash("ML-сервис временно не отвечает", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.HTTPStatusError:
        flash("Не удалось зарегистрировать или валидировать модель", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.RequestError:
        flash("Не удалось подключиться к ML-сервису.", "error")
        return redirect(url_for("main.dashboard"))

    flash("Модель зарегистрирована и отправлена на валидацию", "success")
    return redirect(url_for("models.detail", model_id=result["model_id"]))


@bp.post("/<int:model_id>/runs")
@login_required
def create_run(model_id):
    raw_dataset_id = request.form.get("dataset_id", "")
    raw_hyperparameters = request.form.get("hyperparameters", "")

    try:
        dataset_id = int(raw_dataset_id)
        hyperparameters = json.loads(raw_hyperparameters)
    except (ValueError, json.JSONDecodeError):
        flash("Некорректные параметры запуска", "error")
        return redirect(url_for("models.detail", model_id=model_id))

    if not isinstance(hyperparameters, dict):
        flash("Гиперпараметры должны быть JSON-объектом", "error")
        return redirect(url_for("models.detail", model_id=model_id))

    storage = current_app.extensions["storage_client"]
    ml_service = current_app.extensions["ml_client"]

    try:
        model = storage.get_model_info(actor_id=current_user.id, model_id=model_id)
        dataset = storage.get_dataset_info(actor_id=current_user.id, dataset_id=dataset_id)

        if model is None or dataset is None: abort(404)
        if model["status"] != "validated":
            flash("Модель ещё не прошла валидацию.", "error")
            return redirect(url_for("models.detail", model_id=model_id))

        result = ml_service.create_run(
            actor_id=current_user.id,
            model_id=model_id,
            dataset_id=dataset_id,
            hyperparameters=hyperparameters,
        )

    except httpx.TimeoutException:
        flash("Один из сервисов временно не отвечает.", "error")
        return redirect(url_for("models.detail", model_id=model_id))
    except httpx.HTTPStatusError:
        flash("Не удалось создать запуск модели.", "error")
        return redirect(url_for("models.detail", model_id=model_id))
    except httpx.RequestError:
        flash("Не удалось подключиться к ML-сервису.", "error")
        return redirect(url_for("main.dashboard"))

    return redirect(url_for("results.detail", run_id=result["run_id"]))


@bp.post("/<int:model_id>/delete")
@login_required
def delete_model(model_id):
    storage = current_app.extensions["storage_client"]

    try:
        storage.delete_model(actor_id=current_user.id,
                            model_id=model_id)
    except httpx.HTTPStatusError:
        flash("Не удалось удалить модель", "error")
    else:
        flash("Модель удалена", "success")

    return redirect(url_for("main.dashboard"))


@bp.post("/<int:model_id>/versions")
@login_required
def create_version(model_id):
    version = request.form.get("version", "").strip()

    semver = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

    if not semver.fullmatch(version):
        flash("Версия должна иметь вид major.minor.patch, например 1.1.0", "error")
        return redirect(url_for("models.detail", model_id=model_id))

    ml_client = current_app.extensions["ml_client"]

    try:
        result = ml_client.register_new_version(
            actor_id=current_user.id,
            model_id=model_id,
            version=version,
        )
    except httpx.TimeoutException:
        flash("ML-сервис временно не отвечает", "error")
        return redirect(url_for("models.detail", model_id=model_id))
    except httpx.RequestError:
        flash("Не удалось подключиться к ML-сервису", "error")
        return redirect(url_for("models.detail", model_id=model_id))
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 409:
            flash("Такая версия модели уже зарегистрирована", "error")
        else:
            flash("Не удалось провалидировать новую версию модели", "error")

        return redirect(url_for("models.detail", model_id=model_id))

    flash("Новая версия модели успешно зарегистрирована", "success")
    return redirect(url_for("models.detail", model_id=result["model_id"]))


@bp.post("/<int:model_id>/revalidate")
@login_required
def revalidate_model(model_id):
    storage = current_app.extensions["storage_client"]
    try:
        storage.revalidate_model(actor_id=current_user.id, model_id=model_id)
    except httpx.TimeoutException:
        flash("Сервис хранения временно не отвечает", "error")
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            abort(404)
        elif error.response.status_code == 409:
            flash("Модель уже ожидает валидации или валидируется", "error")
        else: flash("Не удалось повторно отправить модель на валидацию", "error")
    except httpx.RequestError:
        flash("Не удалось подключиться к сервису хранения", "error")
    else: flash("Модель повторно отправлена на валидацию", "success")

    return redirect(url_for("models.detail", model_id=model_id))