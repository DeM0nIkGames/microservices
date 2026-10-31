import io
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from random import Random

import httpx
from flask import current_app
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
    roc_curve,
    precision_recall_curve,
    average_precision_score,
)

class CancellationError(RuntimeError):
    pass


def put_json(minio_client, bucket_name, object_key, value):
    data = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    minio_client.put_object(
        bucket_name=bucket_name,
        object_name=object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json; charset=utf-8",
    )


def softmax(logits):
    maximum = max(logits)
    values = [math.exp(value - maximum) for value in logits]
    total = sum(values)
    return [value / total for value in values]


def make_split_metrics(y_true, y_pred, class_ids):
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=class_ids,
        average="macro",
        zero_division=0,
    )

    per_class_precision, per_class_recall, per_class_f1, support = (
        precision_recall_fscore_support(
            y_true,
            y_pred,
            labels=class_ids,
            average=None,
            zero_division=0,
        )
    )

    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(precision),
        "recall_macro": float(recall),
        "f1_macro": float(f1),
    }, {
        "labels": [str(class_id) for class_id in class_ids],
        "precision": [float(value) for value in per_class_precision],
        "recall": [float(value) for value in per_class_recall],
        "f1": [float(value) for value in per_class_f1],
        "support": [int(value) for value in support],
    }


def model_cycle(run_id):

    collector = current_app.extensions["collector_client"]
    storage = current_app.extensions["storage_client"]
    minio_client = current_app.extensions["minio_client"]
    bucket_name = current_app.config["bucket_name"]
    try:
        run_info = storage.get_run_for_worker(run_id=run_id)
        model_info = storage.get_model_info(actor_id=run_info["user_id"],
                                            model_id=run_info["model_id"])
        dataset_info = storage.get_dataset_info(actor_id=run_info["user_id"],
                                                dataset_id=run_info["dataset_id"])
        manifest_file = collector.get_manifest(actor_id=run_info["user_id"],
                                               dataset_id=run_info["dataset_id"])["items"]
    except httpx.TimeoutException:
        raise ValueError("Ошибка при обращении к сервисам")
    except httpx.HTTPStatusError as error:
        raise ValueError("Ошибка при обращении к сервисам")

    model_url = model_info["import_url"]
    hyperparameters = run_info["hyperparameters"]

    classes = {}
    for item in manifest_file:
        if not item["label"] in classes:
            classes[item["label"]] = [item["id"]]
        else:
            classes[item["label"]].append(item["id"])
    label_to_index = {
        class_id: index
        for index, class_id in enumerate(sorted(classes))
    }
    index_to_label = {
        index: class_id
        for class_id, index in label_to_index.items()
    }

    rng = Random(run_info["seed"])
    training_ids, testing_ids = [], []
    for class_id, item_ids in classes.items():
        rng.shuffle(item_ids)

        split_index = math.floor(
            len(item_ids) * float(run_info["split_config"]["train_percent"][str(class_id)])
        )

        training_ids.extend(item_ids[:split_index])
        testing_ids.extend(item_ids[split_index:])

    rng.shuffle(training_ids)
    rng.shuffle(testing_ids)

    epochs = int(hyperparameters.get("epochs", 1))
    batch_size = int(hyperparameters.get("batch_size", 16))

    train_batches = math.ceil(len(training_ids) / batch_size)
    test_batches = math.ceil(len(testing_ids) / batch_size)

    if training_ids:
        total_batches = epochs * (train_batches + test_batches)
    else:
        total_batches = test_batches
    completed_batches = 0
    last_progress_update = datetime.now(timezone.utc)

    progress = {
        "current_epoch": 0,
        "total_epochs": epochs if training_ids else 1,
        "current_batch": 0,
        "total_batches": total_batches,
        "completed_batches": 0,
        "percent": 0.0,
        "phase": "queued",
        "last_message": "Запуск ожидает выполнения",
    }

    history = {
        "epoch": [],
        "train": {
            "loss": [],
            "accuracy": [],
        },
        "test": {
            "loss": [],
            "accuracy": [],
        },
    }

    log_lines = [
        f"{datetime.now(timezone.utc).isoformat()} Run {run_id} started"
    ]

    def update_progress(force=False):
        nonlocal last_progress_update

        now = datetime.now(timezone.utc)
        if force or now - last_progress_update >= timedelta(seconds=2):
            current_status = storage.get_run_for_worker(run_id=run_id)["status"]
            if current_status == "cancelled": raise CancellationError("Запуск был отменен пользователем")
            
            progress["completed_batches"] = completed_batches
            progress["percent"] = round(
                100 * completed_batches / total_batches,
                2,
            )
            progress["updated_at"] = now.isoformat()

            storage.update_run_progress(
                run_id=run_id,
                progress=progress,
            )
            last_progress_update = now

    def run_split(item_ids, is_train, epoch, phase):
        nonlocal completed_batches

        loss_sum = 0.0
        correct = 0
        total = 0

        all_true = []
        all_predicted = []
        all_probabilities = []
        all_anomaly_scores = []
        all_item_ids = []

        progress["phase"] = phase
        progress["current_epoch"] = epoch
        progress["current_batch"] = 0
        progress["last_message"] = (
            f"{'Обучение' if is_train else 'Тестирование'}: "
            f"эпоха {epoch}/{progress['total_epochs']}"
        )
        update_progress(force=True)

        for batch_number, start in enumerate(
            range(0, len(item_ids), batch_size),
            start=1,
        ):
            batch_ids = item_ids[start:start + batch_size]

            batch = collector.get_batch(
                actor_id=run_info["user_id"],
                dataset_id=dataset_info["id"],
                item_ids=batch_ids,
            )["items"]
            model_batch = [
                {
                    **item,
                    "label": label_to_index[item["label"]],
                }
                for item in batch
            ]

            response = model_client.post(
                f"/sessions/{session_id}/batch",
                json={
                    "is_train": is_train,
                    "images": model_batch,
                },
            )
            response.raise_for_status()
            response_data = response.json()

            batch_loss = float(response_data["loss"])
            logits_batch = response_data["logits"]
            anomaly_scores_batch = [float(score) for score in response_data["anomaly_scores"]]

            original_labels = [item["label"] for item in batch]
            batch_item_ids = [item["id"] for item in batch]

            predicted_indexes = [
                logits.index(max(logits))
                for logits in logits_batch
            ]
            predicted_labels = [
                index_to_label[index]
                for index in predicted_indexes
            ]

            loss_sum += batch_loss * len(batch)
            correct += sum(
                true_label == predicted_label
                for true_label, predicted_label in zip(
                    original_labels,
                    predicted_labels,
                )
            )
            total += len(batch)

            all_true.extend(original_labels)
            all_predicted.extend(predicted_labels)
            all_item_ids.extend(batch_item_ids)
            all_anomaly_scores.extend(anomaly_scores_batch)

            if not is_train:
                all_probabilities.extend(
                    softmax(logits)
                    for logits in logits_batch
                )

            completed_batches += 1
            progress["current_batch"] = batch_number
            progress["last_message"] = (
                f"{'Обучение' if is_train else 'Тестирование'}: "
                f"эпоха {epoch}/{epochs}, батч {batch_number}"
            )
            update_progress()

        return {
            "loss": loss_sum / total,
            "accuracy": correct / total,
            "true_labels": all_true,
            "predicted_labels": all_predicted,
            "probabilities": all_probabilities,
            "anomaly_scores": all_anomaly_scores,
            "item_ids": all_item_ids,
        }

    model_url = model_info["import_url"]
    last_train_result = None
    last_test_result = None

    with httpx.Client(
        base_url=model_url,
        timeout=httpx.Timeout(50.0, connect=10.0),
    ) as model_client:
        session_response = model_client.post(
            "/sessions",
            json={
                "run_id": str(run_id),
                "hyperparameters": hyperparameters,
            },
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]

        try:
            if training_ids:
                for epoch in range(1, epochs + 1):
                    last_train_result = run_split(
                        item_ids=training_ids,
                        is_train=True,
                        epoch=epoch,
                        phase="training",
                    )

                    history["epoch"].append(epoch)
                    history["train"]["loss"].append(last_train_result["loss"])
                    history["train"]["accuracy"].append(
                        last_train_result["accuracy"]
                    )
                    if testing_ids:
                        last_test_result = run_split(
                            item_ids=testing_ids,
                            is_train=False,
                            epoch=epoch,
                            phase="testing",
                        )

                        history["test"]["loss"].append(last_test_result["loss"])
                        history["test"]["accuracy"].append(
                            last_test_result["accuracy"]
                        )
                    log_lines.append(f"Epoch {epoch}/{epochs}: ")
                    if last_train_result:
                        log_lines.append(
                            f"train_loss={last_train_result['loss']:.6f}, "
                            f"train_accuracy={last_train_result['accuracy']:.6f}"
                        )

                    if last_test_result is not None:
                        log_lines.append(
                            f"test_loss={last_test_result['loss']:.6f}, "
                            f"test_accuracy={last_test_result['accuracy']:.6f}"
                        )

            elif testing_ids:
                last_test_result = run_split(
                    item_ids=testing_ids,
                    is_train=False,
                    epoch=1,
                    phase="testing",
                )

                history["test"]["loss"].append(last_test_result["loss"])
                history["test"]["accuracy"].append(
                    last_test_result["accuracy"]
                )
                history["epoch"].append(1)
                log_lines.append(f"Epoch 1/1: ")

                if last_test_result is not None:
                    log_lines.append(
                        f"test_loss={last_test_result['loss']:.6f}, "
                        f"test_accuracy={last_test_result['accuracy']:.6f}"
                    )

                update_progress(force=True)

        finally:
            close_response = model_client.post(
                f"/sessions/{session_id}/close",
                json={},
            )
            close_response.raise_for_status()

        artifacts = {
            "schema_version": 1,
            "metrics": {
                "train": None,
                "test": None,
            },
            "history": history,
        }

    scores = {
        "schema_version": 1,
        "negative_class": sorted(classes)[0],
        "positive_class": sorted(classes)[1],
        "higher_score_is_positive": True,
        "splits": {},
    }

    if last_train_result is not None:
        scores["splits"]["train"] = {
            "item_ids": last_train_result["item_ids"],
            "true_labels": last_train_result["true_labels"],
            "anomaly_scores": last_train_result["anomaly_scores"],
        }

    if last_test_result is not None:
        scores["splits"]["test"] = {
            "item_ids": last_test_result["item_ids"],
            "true_labels": last_test_result["true_labels"],
            "anomaly_scores": last_test_result["anomaly_scores"],
        }

    prefix = f"runs/{run_id}"
    scores_key = f"{prefix}/scores.json"

    put_json(
        minio_client,
        bucket_name,
        scores_key,
        scores,
    )

    artifacts["scores_path"] = scores_key

    if last_train_result is not None:
        train_metrics, _ = make_split_metrics(
            last_train_result["true_labels"],
            last_train_result["predicted_labels"],
            sorted(classes),
        )

        train_metrics["loss"] = last_train_result["loss"]
        artifacts["metrics"]["train"] = train_metrics

    if last_test_result is not None:
        test_metrics, per_class = make_split_metrics(
            last_test_result["true_labels"],
            last_test_result["predicted_labels"],
            sorted(classes),
        )
        test_metrics["loss"] = last_test_result["loss"]

        matrix = confusion_matrix(
            last_test_result["true_labels"],
            last_test_result["predicted_labels"],
            labels=sorted(classes),
        )

        artifacts["metrics"]["test"] = test_metrics
        artifacts["confusion_matrix"] = {
            "labels": [str(class_id) for class_id in sorted(classes)],
            "values": matrix.tolist(),
        }
        artifacts["per_class"] = per_class

        if len(sorted(classes)) == 2:
            positive_index = 1
            positive_label = sorted(classes)[positive_index]

            binary_true = [
                int(label == positive_label)
                for label in last_test_result["true_labels"]
            ]
            if len(set(binary_true)) == 2:
                positive_scores = [
                    probabilities[positive_index]
                    for probabilities in last_test_result["probabilities"]
                ]

            fpr, tpr, _ = roc_curve(binary_true, positive_scores)
            precision, recall, _ = precision_recall_curve(
                binary_true,
                positive_scores,
            )

            artifacts["metrics"]["test"]["roc_auc"] = float(
                roc_auc_score(binary_true, positive_scores)
            )

            artifacts["curves"] = {
                "test": {
                    "roc": {
                        "fpr": fpr.tolist(),
                        "tpr": tpr.tolist(),
                        "auc": artifacts["metrics"]["test"]["roc_auc"],
                    },
                    "pr": {
                        "recall": recall.tolist(),
                        "precision": precision.tolist(),
                        "average_precision": float(
                            average_precision_score(
                                binary_true,
                                positive_scores,
                            )
                        ),
                    },
                },
            }

        groups = defaultdict(list)

        for item_id, true_label, predicted_label in zip(
            last_test_result["item_ids"],
            last_test_result["true_labels"],
            last_test_result["predicted_labels"],
        ):
            if true_label != predicted_label:
                groups[(true_label, predicted_label)].append(item_id)

        misclassified = {
            "schema_version": 1,
            "groups": [
                {
                    "true_label": true_label,
                    "predicted_label": predicted_label,
                    "item_ids": item_ids,
                }
                for (true_label, predicted_label), item_ids in groups.items()
            ],
        }
    else:
        misclassified = {
            "schema_version": 1,
            "groups": [],
        }

    prefix = f"runs/{run_id}"
    artifacts_key = f"{prefix}/artifacts.json"
    misclassified_key = f"{prefix}/misclassified.json"
    log_key = f"{prefix}/training.log"

    artifacts["misclassified_path"] = misclassified_key
    artifacts["log_path"] = log_key

    put_json(minio_client, bucket_name, artifacts_key, artifacts)
    put_json(
        minio_client,
        bucket_name,
        misclassified_key,
        misclassified,
    )

    log_data = "\n".join(log_lines).encode("utf-8")
    minio_client.put_object(
        bucket_name=bucket_name,
        object_name=log_key,
        data=io.BytesIO(log_data),
        length=len(log_data),
        content_type="text/plain; charset=utf-8",
    )

    progress.update(
        {
            "phase": "completed",
            "percent": 100.0,
            "last_message": "Обучение завершено",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    storage.update_run_progress(
        run_id=run_id,
        progress=progress,
    )

    storage.complete_run(
        run_id=run_id,
        metrics=artifacts["metrics"],
        results_path=artifacts_key,
    )