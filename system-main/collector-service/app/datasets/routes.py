from flask import Blueprint, current_app, g, jsonify, request
from zipfile import BadZipFile, ZipFile
from pathlib import PurePosixPath
import csv, json, io, mimetypes, uuid
from app.decorators import admin_required, service_required
from decimal import Decimal, InvalidOperation
from minio.error import S3Error
import base64, httpx, random
from datetime import timedelta
from app.logging import audit_event

bp = Blueprint("datasets", __name__)
MAX_ARCHIVE_FILES = 20_000
MAX_UNCOMPRESSED_SIZE = 40 * 1024 * 1024 * 1024
MAX_BATCH_ITEMS = 64
MAX_BATCH_BYTES = 64 * 1024 * 1024


def open_archive(filestream):
    try:
        filestream.stream.seek(0)
        return ZipFile(filestream.stream)
    except BadZipFile as error:
        raise ValueError("Переданный файл - некорректный .zip-архив") from error


def normalize_path(raw_path):
    path = PurePosixPath(raw_path.replace("\\", "/"))
    if (not raw_path or path.is_absolute() or ".." in path.parts or str(path) == "."): raise ValueError(f"Недопустимый путь в архиве: {raw_path}")
    return path.as_posix()


def validate_zip_structure(zip_file):
    infos = zip_file.infolist()
    if len(infos) > MAX_ARCHIVE_FILES: raise ValueError("Архив содержит слишком много файлов")
    total_uncompressed_size = 0

    files_by_path = {}
    for info in infos:
        norm_path = normalize_path(info.filename)
        if info.flag_bits & 0x1: raise ValueError("Зашифрованные ZIP-архивы не поддерживаются")
        total_uncompressed_size += info.file_size
        if total_uncompressed_size > MAX_UNCOMPRESSED_SIZE: raise ValueError("Архив слишком велик после распаковки")
        if norm_path in files_by_path: raise ValueError(f"Архив содержит дублирующийся путь: {norm_path}")

        files_by_path[norm_path] = info

    return files_by_path


def read_csv_manifest(zip_file, manifest_path):
    with zip_file.open(manifest_path) as raw_f:
        f = io.TextIOWrapper(raw_f, encoding="utf-8-sig", newline="")

        reader = csv.reader(f)
        result = []
        seen = set()

        for row in reader:
            if len(row) != 2: raise ValueError("Строка должна содержать путь к изображению и метку класса")

            img_path = normalize_path(row[0])
            if not img_path in seen: seen.add(img_path)
            else: raise ValueError("Дубликаты не допускаются")

            try:
                label = int(row[1].strip())
            except ValueError: raise ValueError(f"Метка класса должна быть неотрицательным числом, изображение {img_path}, метка {row[1]}")
            if label < 0: raise ValueError(f"Метка класса должна быть неотрицательным числом, изображение {img_path}, метка {label}")

            result.append({
                "path": img_path,
                "label": label,
            })
        return result


def read_json_manifest(zip_file, manifest_path):
    with zip_file.open(manifest_path) as raw_f:
        f = io.TextIOWrapper(raw_f, encoding="utf-8-sig", newline="")
        try:
            dct = json.load(f)
        except json.JSONDecodeError as error:
            raise ValueError("JSON-разметка содержит некорректный JSON.") from error

        if not isinstance(dct, dict): raise ValueError("Неверный формат JSON-разметки")

        seen = set()
        result = []
        for label, path_list in dct.items():
            if not isinstance(path_list, list): raise ValueError("Неверный формат JSON-разметки")
            try:
                res_label = int(label)
            except ValueError: raise ValueError(f"Метка класса должна быть неотрицательным числом, класс {label}")
            if res_label < 0: raise ValueError(f"Метка класса должна быть неотрицательным числом, класс {label}")

            for path in path_list:
                if not isinstance(path, str): raise ValueError(f"Путь {path} в классе {label} должен быть строкой")
                res_path = normalize_path(path)
                if not res_path in seen: seen.add(res_path)
                else: raise ValueError("Дубликаты не допускаются")
                result.append({
                    "path": res_path,
                    "label": res_label,
                })
        return result


def cleanup_minio(uploaded_keys):
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]
    for object_key in uploaded_keys:
        try:
            minio_client.remove_object(bucket_name, object_key)
        except Exception:
            current_app.logger.exception("Не удалось удалить частично загруженный объект %s", object_key)


def import_new_dataset(archive):
    prefix = f"datasets/{uuid.uuid4()}"
    path_by_archive_path = {}
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]

    archive.stream.seek(0)
    with open_archive(archive) as zip_file:
        files_by_path = validate_zip_structure(zip_file)

        names = zip_file.namelist()
        flag = False
        for name in names:
            if name.lower().endswith((".csv", ".json")):
                if flag: raise ValueError("Может быть только один файл с разметкой")
                else: 
                    flag = True
                    manifest_file = name
        if not flag: raise ValueError("В архиве должен быть файл с разметкой")

        items_list = read_csv_manifest(zip_file, manifest_file) if manifest_file.lower().endswith(".csv") else read_json_manifest(zip_file, manifest_file)
        if not items_list: raise ValueError("Разметка не содержит изображений")
        uploaded_keys = []
        try:
            
            for item in items_list:
                archive_path = item["path"]                
                info = files_by_path.get(archive_path)
                
                if info is None: raise ValueError(f"В разметке указан отсутствующий файл: {archive_path}")
                if info.is_dir(): raise ValueError(f"В разметке указан каталог вместо изображения: {archive_path}")

                object_key = f"{prefix}/images/{archive_path}"
                content_type = (mimetypes.guess_type(archive_path)[0] or "application/octet-stream")
                uploaded_keys.append(object_key)

                with zip_file.open(info) as image_stream:
                    minio_client.put_object(
                        bucket_name=bucket_name,
                        object_name=object_key,
                        data=image_stream,
                        length=info.file_size,
                        content_type=content_type)
                path_by_archive_path[archive_path] = object_key

        except Exception:
            cleanup_minio(uploaded_keys)
            raise

    return {
        "dataset_prefix": prefix,
        "object_by_archive_path": path_by_archive_path,
        "items_list": items_list,
        "uploaded_keys": uploaded_keys,
    }


def count_statistics(name, dataset_info):
    stats = {}
    images = []
    for n, item in enumerate(dataset_info["items_list"], start=1):
        label, path = item["label"], item["path"]
        if not str(label) in stats: stats[str(label)] = 1
        else: stats[str(label)] += 1
        tmp = {
            "id": n,
            "label": label,
            "archive_path": path,
            "object_key": dataset_info["object_by_archive_path"][path]
        }
        images.append(tmp)
    manifest = {
        "name": name,
        "items": images,
    }
    manifest_key = f"{dataset_info['dataset_prefix']}/manifest.json"
    man_bytes = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]

    try:
        dataset_info["uploaded_keys"].append(manifest_key)
        minio_client.put_object(
            bucket_name=bucket_name,
            object_name=manifest_key,
            data=io.BytesIO(man_bytes),
            length=len(man_bytes),
            content_type="application/json; charset=utf-8",
        )
    except Exception:
        cleanup_minio(dataset_info["uploaded_keys"])
        raise
    
    return {
        "manifest_key": manifest_key,
        "class_counts": stats,
        "class_labels": {key: key for key in stats.keys()}
    }


def load_manifest(manifest_key):
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]

    response = minio_client.get_object(bucket_name, manifest_key)
    try:
        return json.loads(response.read().decode("utf-8"))
    finally:
        response.close()
        response.release_conn()


@bp.post("/datasets")
@service_required("web-service")
@admin_required
def check_and_register_dataset():
    name = request.form.get("name", "").strip()
    raw_train_percent = request.form.get("default_train_percent", "").strip()
    archive = request.files.get("archive")

    if not name: return jsonify(error="Не передано название датасета"), 400
    if archive is None or not archive.filename: return jsonify(error="Не передан ZIP-архив"), 400
    if not archive.filename.lower().endswith(".zip"): return jsonify(error="Ожидается файл .zip"), 400

    try:
        default_train_percent = Decimal(raw_train_percent)
    except InvalidOperation: return jsonify(error="train_percent должен быть числом"), 400

    if not default_train_percent.is_finite() or not 0 <= default_train_percent <= 1: 
        return jsonify(error="train_percent должен находиться в диапазоне [0, 1]"), 400

    dataset_info = {"uploaded_keys": []}
    try:
        dataset_info = import_new_dataset(archive)
        stats = count_statistics(name, dataset_info)
        storage = current_app.extensions["storage_client"]

        dataset = storage.create_dataset(
            actor_id=g.caller_user,
            name=name,
            manifest_path=stats["manifest_key"],
            class_labels=stats["class_labels"],
            class_counts=stats["class_counts"],
            train_percent={str(key): float(default_train_percent) for key in stats["class_labels"].keys()},
        )
    except ValueError as error:
        cleanup_minio(dataset_info["uploaded_keys"])
        return jsonify(error=str(error)), 400

    except S3Error:
        cleanup_minio(dataset_info["uploaded_keys"])
        current_app.logger.exception("Ошибка при работе с MinIO")
        return jsonify(error="Не удалось сохранить файлы датасета"), 502

    except httpx.TimeoutException:
        cleanup_minio(dataset_info["uploaded_keys"])
        current_app.logger.exception("Storage временно недоступен")
        return jsonify(error="Сервис хранилища временно недоступен"), 503

    except (httpx.RequestError, httpx.HTTPStatusError):
        cleanup_minio(dataset_info["uploaded_keys"])
        current_app.logger.exception("Ошибка обращения к Storage")
        return jsonify(error="Не удалось зарегистрировать датасет"), 502
    except Exception:
        cleanup_minio(dataset_info["uploaded_keys"])
        return jsonify(error="Внутренняя ошибка при регистрации датасета"), 500

    audit_event(
        "dataset.imported",
        entity_type="dataset",
        entity_id=dataset["id"],
        details={
            "name": name,
            "manifest_key": stats["manifest_key"],
            "images_count": sum(stats["class_counts"].values()),
            "classes_count": len(stats["class_counts"]),
            "uploaded_objects_count": len(
                dataset_info["uploaded_keys"]
            ),
        },
    )
    return jsonify(dataset_id=dataset["id"]), 201


@bp.get("/datasets/<int:dataset_id>/manifest")
@service_required("ml-service")
def get_manifest_data(dataset_id):
    storage = current_app.extensions["storage_client"]
    actor_id = request.headers.get("X-Acting-User-Id", type=int)

    if actor_id is None or actor_id <= 0: return jsonify(error="Некорректный X-Acting-User-Id"), 400

    try:
        manifest_key = storage.get_manifest_key(actor_id=actor_id, dataset_id=dataset_id)
    except Exception:
        return jsonify(error="Не удалось найти manifest_key"), 502

    if manifest_key is None: return jsonify(error="Датасет не найден"), 404
    manifest=load_manifest(manifest_key)
    items = [{
            "id": item["id"],
            "label": item["label"],
        }
        for item in manifest["items"]]

    return jsonify(items=items), 200


@bp.post("/datasets/<int:dataset_id>/batch")
@service_required("ml-service")
def get_batch(dataset_id):
    actor_id = request.headers.get("X-Acting-User-Id", type=int)
    if actor_id is None or actor_id <= 0: return jsonify(error="Некорректный X-Acting-User-Id"), 400
    idxs_json = request.get_json(silent=True)
    if not isinstance(idxs_json, dict): return jsonify(error="Некорректное тело запроса"), 400

    idxs = idxs_json.get("item_ids")
    if not isinstance(idxs, list) or not idxs or len(idxs) > MAX_BATCH_ITEMS:
        return jsonify(error=f"item_ids должен содержать от 1 до {MAX_BATCH_ITEMS} элементов"), 400

    if any(isinstance(idx, bool) or not isinstance(idx, int) for idx in idxs) or len(set(idxs)) != len(idxs):
        return jsonify(error="Переданы некорректные или повторяющиеся item_ids"), 400

    storage = current_app.extensions["storage_client"]
    try:
        manifest_key = storage.get_manifest_key(actor_id=actor_id, dataset_id=dataset_id)
    except Exception:
        return jsonify(error="Не удалось найти manifest_key"), 502

    if manifest_key is None: return jsonify(error="Датасет не найден"), 404
    manifest = load_manifest(manifest_key)
    items_dct = {item["id"]: item for item in manifest["items"]}

    result = []
    for item_id in idxs:
        item = items_dct.get(item_id)
        if item is None: return jsonify(error=f"Элемент {item_id} отсутствует в датасете {dataset_id}"), 400

        result.append(item)

    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]
    result_items = []
    total_bytes = 0

    for item in result:
        object_response = minio_client.get_object(bucket_name, item["object_key"])

        try:
            image_bytes = object_response.read()
        finally:
            object_response.close()
            object_response.release_conn()

        total_bytes += len(image_bytes)
        if total_bytes > MAX_BATCH_BYTES: return jsonify(error="Батч изображений слишком большой"), 413

        result_items.append({
            "id": item["id"],
            "label": item["label"],
            "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        })

    audit_event(
        "dataset.batch_served",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "items_count": len(result_items),
            "total_bytes": total_bytes,
        },
    )
    return jsonify(dataset_id=dataset_id, items=result_items)


@bp.post("/datasets/<int:dataset_id>/image-urls")
@service_required("web-service")
def get_image_urls(dataset_id):
    actor_id = request.headers.get("X-Acting-User-Id", type=int)

    if actor_id is None or actor_id <= 0: return jsonify(error="Некорректный X-Acting-User-Id"), 400
    idxs_json = request.get_json(silent=True)
    if not isinstance(idxs_json, dict): return jsonify(error="Некорректное тело запроса"), 400
    
    idxs = idxs_json.get("item_ids")
    if not isinstance(idxs, list) or not idxs or len(idxs) > MAX_BATCH_ITEMS:
        return jsonify(error=f"item_ids должен содержать от 1 до {MAX_BATCH_ITEMS} элементов"), 400
    
    if any(isinstance(idx, bool) or not isinstance(idx, int) for idx in idxs) or len(set(idxs)) != len(idxs):
        return jsonify(error="Переданы некорректные или повторяющиеся item_ids"), 400
    
    storage = current_app.extensions["storage_client"]
    manifest_key = storage.get_manifest_key(actor_id, dataset_id)
    if manifest_key is None: return jsonify(error="Датасет не найден"), 404

    manifest = load_manifest(manifest_key)
    items_dct = {item["id"]: item for item in manifest["items"]}

    minio_client = current_app.extensions["minio_public_client"]
    bucket_name = current_app.config["bucket_name"]
    result = []
    for item_id in idxs:
        item = items_dct.get(item_id)

        if item is None: return jsonify(error=f"Элемент {item_id} отсутствует в датасете"), 400
        url = minio_client.presigned_get_object(
            bucket_name=bucket_name,
            object_name=item["object_key"],
            expires=timedelta(minutes=30),
        )

        result.append({
            "item_id": item_id,
            "label": item["label"],
            "url": url,
        })

    return jsonify(items=result), 200


@bp.get("/datasets/<int:dataset_id>/preview")
@service_required("web-service")
def get_random_preview_urls(dataset_id):
    actor_id = request.headers.get("X-Acting-User-Id", type=int)
    if actor_id is None or actor_id <= 0: return jsonify(error="Некорректный X-Acting-User-Id"), 400

    storage = current_app.extensions["storage_client"]
    manifest_key = storage.get_manifest_key(actor_id, dataset_id)

    if manifest_key is None: return jsonify(error="Датасет не найден"), 404

    manifest = load_manifest(manifest_key)
    items_by_label = {}
    for item in manifest["items"]: items_by_label.setdefault(str(item["label"]), []).append(item)

    minio_client = current_app.extensions["minio_public_client"]
    bucket_name = current_app.config["bucket_name"]

    preview_urls = {}
    for class_id, items in items_by_label.items():
        selected_item = random.choice(items)

        preview_urls[class_id] = minio_client.presigned_get_object(
            bucket_name=bucket_name,
            object_name=selected_item["object_key"],
            expires=timedelta(minutes=30),
        )

    return jsonify(preview_urls=preview_urls), 200


@bp.delete("/datasets/<int:dataset_id>")
@service_required("storage-service")
def delete_dataset(dataset_id):
    body = request.get_json(silent=True)
    if not isinstance(body, dict): return jsonify(error="Тело запроса должно быть JSON-объектом"), 400

    manifest_key = body.get("manifest_key")
    if not manifest_key or not isinstance(manifest_key, str): return jsonify(error="Поле manifest_key должно быть строкой"), 400

    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]


    manifest = load_manifest(manifest_key=manifest_key)
    for item in manifest["items"]:
        object_key = item["object_key"]

        try:
            minio_client.remove_object(bucket_name, object_key)
        except S3Error:
            return jsonify(error=f"Возникла ошибка при удалении файла {object_key}"), 502
    try:
        minio_client.remove_object(bucket_name, manifest_key)
    except S3Error:
        return jsonify(error=f"Возникла ошибка при удалении манифеста"), 502

    audit_event(
        "dataset.objects_deleted",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "manifest_key": manifest_key,
            "deleted_images_count": len(manifest["items"]),
        },
    )
    return jsonify(status="success"), 200