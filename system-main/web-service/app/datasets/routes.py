from flask import (
    Blueprint, 
    current_app, 
    redirect, 
    render_template, 
    request,
    flash,
    url_for,
    abort,
    jsonify,
)
from flask_login import login_required, current_user
from decimal import Decimal, InvalidOperation
import httpx
import json

bp = Blueprint("datasets", __name__, url_prefix="/datasets")


@bp.get("/<int:dataset_id>")
@login_required
def detail(dataset_id):
    storage = current_app.extensions["storage_client"]
    collector = current_app.extensions["collector_client"]

    try:
        raw_dataset = storage.get_dataset_info(
            actor_id=current_user.id,
            dataset_id=dataset_id,
        )
    except httpx.TimeoutException:
        flash("Сервис хранилища временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.HTTPStatusError:
        flash("Не удалось загрузить датасет.", "error")
        return redirect(url_for("main.dashboard"))
    
    if raw_dataset is None: abort(404)

    try:
        preview_urls = collector.get_preview_urls(actor_id=current_user.id,
                                                  dataset_id=dataset_id)
    except httpx.TimeoutException:
        flash("Сервис сборщик временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.HTTPStatusError:
        flash("Не удалось загрузить изображения.", "error")
        return redirect(url_for("main.dashboard"))

    classes = []
    for class_id, label in raw_dataset["class_labels"].items():
        classes.append({
            "id": class_id,
            "label": label,
            "items_count": raw_dataset["class_counts"][class_id],
            "train_percent": float(raw_dataset["train_percent"][class_id]),
            "preview_url": preview_urls[class_id],
        })

    dataset = {
        "id": raw_dataset["id"],
        "name": raw_dataset["name"],
        "total_items": sum(item["items_count"] for item in classes),
        "classes": classes,
    }

    return render_template(
        "instances/dataset.html",
        user=current_user,
        dataset=dataset,
    )


@bp.post("")
@login_required
def create_dataset():
    name = request.form.get("name", "").strip()
    archive = request.files.get("archive")
    train_percent = request.form.get("train_percent", "").strip() or "0"

    if not name:
        flash("Название датасета обязательно", "error")
        return redirect(url_for("main.dashboard"))
    if archive is None or not archive.filename:
        flash("Загрузка файла обязательна", "error")
        return redirect(url_for("main.dashboard"))
    if not archive.filename.lower().endswith(".zip"):
        flash("Файл обязан быть zip-архивом", "error")
        return redirect(url_for("main.dashboard"))

    try:
        default_train_percent = Decimal(train_percent)
        if (not default_train_percent.is_finite() or not Decimal("0") <= default_train_percent <= Decimal("1")):
            raise ValueError
    except (InvalidOperation, ValueError):
        flash("Доля обучения должна быть числом от 0 до 1.", "error")
        return redirect(url_for("main.dashboard"))

    collector = current_app.extensions["collector_client"]

    try:
        result = collector.create_dataset(
            actor_id=current_user.id,
            name=name,
            archive=archive,
            default_train_percent=str(default_train_percent),
        )
    except httpx.TimeoutException:
        flash("Сборщик данных временно не отвечает.", "error")
        return redirect(url_for("main.dashboard"))
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 400:
            flash("Архив или файл разметки имеют неверную структуру.", "error")
        else:
            flash("Не удалось загрузить датасет.", "error")
        return redirect(url_for("main.dashboard"))

    return redirect(url_for("datasets.detail", dataset_id=result["dataset_id"]))


@bp.post("/<int:dataset_id>/settings")
@login_required
def update_settings(dataset_id):
    new_train_percent_json = request.form.get("train_percent", "")

    try:
        train_percent = json.loads(new_train_percent_json)
    except json.JSONDecodeError:
        flash("Не удалось прочитать параметры разбиения", "error")
        return redirect(url_for("datasets.detail", dataset_id=dataset_id))
    if not isinstance(train_percent, dict):
        flash("Не удалось прочитать параметры разбиения", "error")
        return redirect(url_for("datasets.detail", dataset_id=dataset_id))

    storage = current_app.extensions["storage_client"]

    try:
        dataset = storage.get_dataset_info(actor_id=current_user.id,
                                            dataset_id=dataset_id)
        if dataset is None: abort(404)
        classes = set(dataset["class_labels"].keys())

        if set(train_percent.keys()) != classes:
            flash("Передан неверный набор классов.", "error")
            return redirect(url_for("datasets.detail", dataset_id=dataset_id))

        for class_id, value in train_percent.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Некорректное значение для класса {class_id}")

            if not 0 <= value <= 1:
                raise ValueError(f"Значение для класса {class_id} вне диапазона")

        storage.update_dataset_train_percent(
            actor_id=current_user.id,
            dataset_id=dataset_id,
            train_percent=train_percent,
        )

    except ValueError:
        flash("Каждый процент должен быть числом от 0 до 1.", "error")
    except httpx.TimeoutException:
        flash("Сервис хранилища временно не отвечает.", "error")
    except httpx.HTTPStatusError:
        flash("Не удалось сохранить разбиение датасета", "error")
    else:
        flash("Разбиение датасета сохранено", "success")

    return redirect(url_for("datasets.detail", dataset_id=dataset_id))


@bp.post("/<int:dataset_id>/classes/<int:class_id>")
@login_required
def update_class_label(dataset_id, class_id):
    new_label = request.form.get("label", "").strip()
    if not new_label:
        flash("Название не должно быть пустым", "error")
        return redirect(url_for("datasets.detail", dataset_id=dataset_id))


    storage = current_app.extensions["storage_client"]

    try:
        storage.rename_class(actor_id=current_user.id, dataset_id=dataset_id, class_id=class_id, label=new_label)
    except httpx.TimeoutException:
        flash("Сервис хранилища временно не отвечает.", "error")
    except httpx.HTTPStatusError:
        flash("Не удалось изменить название класса", "error")
    else:
        flash("Новая метка класса сохранена", "success")
    
    return redirect(url_for("datasets.detail", dataset_id=dataset_id))


@bp.get("/<int:dataset_id>/summary")
@login_required
def summary(dataset_id):
    storage = current_app.extensions["storage_client"]

    try:
        dataset = storage.get_dataset_info(actor_id=current_user.id,
                                           dataset_id=dataset_id)
    except httpx.TimeoutException:
        return jsonify({"error": "Сервис хранилища временно не отвечает."}), 503
    except httpx.RequestError:
        return jsonify({"error": "Не удалось подключиться к сервису хранилища."}), 503
    except httpx.HTTPStatusError:
        return jsonify({"error": "Не удалось получить данные датасета."}), 502

    if dataset is None: abort(404)

    classes = []
    for class_id, label in dataset["class_labels"].items():
        items_count = int(dataset["class_counts"][class_id])
        train_percent = float(dataset["train_percent"][class_id])

        train_count = int(items_count * train_percent)
        test_count = items_count - train_count

        classes.append({
            "id": class_id,
            "label": label,
            "train_count": train_count,
            "test_count": test_count,
            "train_percent": train_percent,
        })

    return jsonify({"classes": classes})


@bp.post("/<int:dataset_id>/delete")
@login_required
def delete_dataset(dataset_id):
    storage = current_app.extensions["storage_client"]

    try:
        storage.delete_dataset(actor_id=current_user.id,
                               dataset_id=dataset_id)
    except httpx.HTTPStatusError:
        flash("Не удалось удалить датасет", "error")
    except httpx.RequestError:
        flash("Сервис хранения временно недоступен", "error")
    else:
        flash("Датасет удалён", "success")

    return redirect(url_for("main.dashboard"))