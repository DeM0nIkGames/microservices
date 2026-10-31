from flask import Blueprint, current_app, render_template, flash
from flask_login import login_required, current_user
import httpx


bp = Blueprint("main", __name__)


def prepare_model(model):
    metadata = model.get("metadata") or {}
    return {**model, "task_type": metadata.get("task_type", "classification")}


def prepare_dataset(dataset):
    class_counts = dataset.get("class_counts") or {}
    return {**dataset, "items_count": sum(class_counts.values())}


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


@bp.get("/")
@login_required
def dashboard():
    storage = current_app.extensions["storage_client"]

    try:
        models = [prepare_model(model) for model in storage.get_models(actor_id=current_user.id)]
        datasets = [prepare_dataset(dataset) for dataset in storage.get_datasets(actor_id=current_user.id)]
        results = [prepare_run(run) for run in storage.get_runs(actor_id=current_user.id)]
        
    except httpx.HTTPStatusError:
        flash("Сервис хранения не смог выполнить запрос.", "error")
        models, datasets, results = [], [], []
    except httpx.RequestError:
        flash("Сервис хранения временно не отвечает.", "error")
        models, datasets, results = [], [], []

    return render_template(
        "dashboard.html",
        user=current_user,
        models=models,
        datasets=datasets,
        results=results,
    )