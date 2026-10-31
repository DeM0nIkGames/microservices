from flask import (
    Blueprint, 
    jsonify, 
    redirect, 
    render_template,
    current_app,
    abort,
    flash,
    url_for,
    request,
)
from flask_login import current_user, login_required
import httpx

bp = Blueprint("results", __name__, url_prefix="/results")


@bp.get("/<int:run_id>")
@login_required
def detail(run_id):
    collector = current_app.extensions["collector_client"]
    storage = current_app.extensions["storage_client"]
    ml = current_app.extensions["ml_client"]
    misclassified_groups = []

    try:
        run = storage.get_run_info(actor_id=current_user.id, run_id=run_id)
        if run is None: abort(404)
        run["task_type"] = "classification"
        if run["status"] == "completed":
            misclassified_payload = ml.get_misclassified(actor_id=current_user.id, run_id=run_id, limit=4)
            if isinstance(misclassified_payload, dict): misclassified_groups = misclassified_payload.get("groups", [])
            else: misclassified_groups = misclassified_payload

            item_ids = [
                image["item_id"]
                for group in misclassified_groups
                for image in group["images"]
            ]

            url_items = []
            for start in range(0, len(item_ids), 64):
                chunk = item_ids[start:start + 64]
                url_items.extend(
                    collector.get_image_urls(
                        actor_id=current_user.id,
                        dataset_id=run["dataset_id"],
                        item_ids=chunk,
                    )
                )

            url_by_item_id = {item["item_id"]: item["url"] for item in url_items}
            for group in misclassified_groups:
                for image in group["images"]:
                    image["url"] = url_by_item_id.get(image["item_id"])

    except httpx.HTTPStatusError:
        flash("Не удалось получить данные запуска.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.RequestError:
        flash("Один из сервисов временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))

    metrics = []
    for split, label in (("train", "Тренировочная выборка"), ("test", "Тестовая выборка")):
        values = (run.get("metrics") or {}).get(split)
        if values is not None:
            metrics.append({
                "label": label,
                "accuracy": values.get("accuracy"),
                "precision": values.get("precision_macro"),
                "recall": values.get("recall_macro"),
                "f1": values.get("f1_macro"),
                "roc_auc": values.get("roc_auc"),
            })

    return render_template(
        "instances/result.html",
        user=current_user,
        run=run,
        metric_rows=metrics,
        error_groups=misclassified_groups,
    )


@bp.get("/<int:run_id>/charts")
@login_required
def charts(run_id):
    percentile = request.args.get("percentile", 95, type=int)
    mode = request.args.get("mode", "manual")

    if mode not in {"manual", "auto"}: return jsonify(error="Некорректный режим"), 400
    if not 1 <= percentile <= 100: return jsonify(error="Некорректный перцентиль"), 400
    vis = current_app.extensions["vis_client"]

    try:
        charts_data = vis.get_charts_data(
            actor_id=current_user.id,
            run_id=run_id,
            percentile=percentile,
            mode=mode,
        )
    except httpx.TimeoutException:
        return jsonify(error="Сервис визуализации временно не отвечает."), 503
    except httpx.RequestError:
        return jsonify(error="Не удалось подключиться к сервису визуализации."), 503
    except httpx.HTTPStatusError as error:
        return jsonify(error="Не удалось получить анализ запуска."), error.response.status_code

    return jsonify(charts_data)


@bp.post("/<int:run_id>/delete")
@login_required
def delete_run(run_id):
    storage = current_app.extensions["storage_client"]

    try:
        storage.delete_run(actor_id=current_user.id, 
                             run_id=run_id)
    except httpx.HTTPStatusError:
        flash("Не удалось удалить запуск", "error")
    else:
        flash("Запуск модели удален", "success")

    return redirect(url_for("main.dashboard"))


@bp.get("/<int:run_id>/progress")
@login_required
def progress(run_id):
    storage = current_app.extensions["storage_client"]
    ml = current_app.extensions["ml_client"]

    try:
        run = storage.get_run_info(actor_id=current_user.id, run_id=run_id)
        if run is None: abort(404)
        payload = ml.get_run_progress(actor_id=current_user.id, run_id=run_id)
    except httpx.HTTPStatusError:
        return jsonify(error="Не удалось получить прогресс"), 502
    except httpx.RequestError:
        return jsonify(error="Сервис временно недоступен"), 503

    progress_data = payload.get("progress") or {}
    metrics = run.get("metrics") or {}
    main_metrics = (metrics.get("test") or metrics.get("train") or {})

    return jsonify(
        status=payload.get("status", run["status"]),
        progress=float(progress_data.get("percent", 0)) / 100,
        epoch=progress_data.get("current_epoch"),
        total_epochs=progress_data.get("total_epochs"),
        accuracy=main_metrics.get("accuracy"),
        roc_auc=main_metrics.get("roc_auc"),
    )