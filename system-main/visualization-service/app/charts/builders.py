from __future__ import annotations

from copy import deepcopy
from typing import Any
import math

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_curve,
)


_BASE_LAYOUT = {
    "template": "plotly_dark",
    "paper_bgcolor": "rgba(0, 0, 0, 0)",
    "plot_bgcolor": "rgba(0, 0, 0, 0)",
    "font": {"color": "#e7edf3"},
    "margin": {"l": 58, "r": 24, "t": 28, "b": 54},
    "hovermode": "x unified",
    "legend": {"orientation": "h", "y": -0.22},
}


def _layout(**extra: Any) -> dict[str, Any]:
    result = deepcopy(_BASE_LAYOUT)
    result.update(extra)
    return result


def _metric_trace(
    *,
    x: list[int | float],
    y: list[int | float],
    name: str,
    color: str,
) -> dict[str, Any]:
    return {
        "type": "scatter",
        "mode": "lines+markers",
        "name": name,
        "x": x,
        "y": y,
        "line": {"color": color, "width": 2},
        "marker": {"size": 5},
        "hovertemplate": (
            "Эпоха: %{x}<br>"
            f"{name}: %{{y:.5f}}"
            "<extra></extra>"
        ),
    }


def build_loss_chart(history: dict[str, Any]) -> dict[str, Any] | None:
    epochs = history.get("epoch", [])
    train_loss = history.get("train", {}).get("loss", [])
    test_loss = history.get("test", {}).get("loss", [])

    if not epochs or (not train_loss and not test_loss):
        return None

    data = []

    if train_loss:
        data.append(
            _metric_trace(
                x=epochs,
                y=train_loss,
                name="Train loss",
                color="#39ff88",
            )
        )

    if test_loss:
        data.append(
            _metric_trace(
                x=epochs,
                y=test_loss,
                name="Test loss",
                color="#70a5ff",
            )
        )

    return {
        "id": "loss",
        "title": "Loss по эпохам",
        "description": "Изменение функции потерь на обучающей и тестовой выборках.",
        "data": data,
        "layout": _layout(
            xaxis={"title": {"text": "Эпоха"}},
            yaxis={"title": {"text": "Loss"}},
        ),
    }


def build_accuracy_chart(history: dict[str, Any]) -> dict[str, Any] | None:
    epochs = history.get("epoch", [])
    train_accuracy = history.get("train", {}).get("accuracy", [])
    test_accuracy = history.get("test", {}).get("accuracy", [])

    if not epochs or (not train_accuracy and not test_accuracy):
        return None

    data = []

    if train_accuracy:
        data.append(
            _metric_trace(
                x=epochs,
                y=train_accuracy,
                name="Train accuracy",
                color="#39ff88",
            )
        )

    if test_accuracy:
        data.append(
            _metric_trace(
                x=epochs,
                y=test_accuracy,
                name="Test accuracy",
                color="#70a5ff",
            )
        )

    return {
        "id": "accuracy",
        "title": "Accuracy по эпохам",
        "description": "Доля правильно классифицированных изображений.",
        "data": data,
        "layout": _layout(
            xaxis={"title": {"text": "Эпоха"}},
            yaxis={
                "title": {"text": "Accuracy"},
                "range": [0, 1],
            },
        ),
    }


def build_roc_chart(curves: dict[str, Any]) -> dict[str, Any] | None:
    roc = curves.get("test", {}).get("roc", {})
    fpr = roc.get("fpr", [])
    tpr = roc.get("tpr", [])

    if not fpr or not tpr or len(fpr) != len(tpr):
        return None

    auc = roc.get("auc")
    auc_text = f", AUC = {auc:.4f}" if isinstance(auc, (int, float)) else ""

    return {
        "id": "roc",
        "title": "ROC-кривая",
        "description": (
            "Соотношение True Positive Rate и False Positive Rate"
            " на тестовой выборке."
        ),
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": f"ROC{auc_text}",
                "x": fpr,
                "y": tpr,
                "line": {"color": "#39ff88", "width": 3},
                "hovertemplate": (
                    "FPR: %{x:.4f}<br>"
                    "TPR: %{y:.4f}"
                    "<extra></extra>"
                ),
            },
            {
                "type": "scatter",
                "mode": "lines",
                "name": "Случайный классификатор",
                "x": [0, 1],
                "y": [0, 1],
                "line": {
                    "color": "#8a94a6",
                    "width": 1,
                    "dash": "dash",
                },
                "hoverinfo": "skip",
            },
        ],
        "layout": _layout(
            xaxis={
                "title": {"text": "False Positive Rate"},
                "range": [0, 1],
            },
            yaxis={
                "title": {"text": "True Positive Rate"},
                "range": [0, 1],
            },
        ),
    }


def build_pr_chart(curves: dict[str, Any]) -> dict[str, Any] | None:
    pr = curves.get("test", {}).get("pr", {})
    recall = pr.get("recall", [])
    precision = pr.get("precision", [])

    if not recall or not precision or len(recall) != len(precision):
        return None

    average_precision = pr.get("average_precision")
    ap_text = (
        f", AP = {average_precision:.4f}"
        if isinstance(average_precision, (int, float))
        else ""
    )

    return {
        "id": "precision-recall",
        "title": "Precision–Recall curve",
        "description": "Кривая точности и полноты на тестовой выборке.",
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "name": f"PR{ap_text}",
                "x": recall,
                "y": precision,
                "line": {"color": "#ffca57", "width": 3},
                "hovertemplate": (
                    "Recall: %{x:.4f}<br>"
                    "Precision: %{y:.4f}"
                    "<extra></extra>"
                ),
            }
        ],
        "layout": _layout(
            xaxis={
                "title": {"text": "Recall"},
                "range": [0, 1],
            },
            yaxis={
                "title": {"text": "Precision"},
                "range": [0, 1],
            },
        ),
    }


def build_confusion_matrix_chart(
    matrix: dict[str, Any],
) -> dict[str, Any] | None:
    labels = matrix.get("labels", [])
    values = matrix.get("values", [])

    if not labels or not values:
        return None

    if len(values) != len(labels):
        return None

    if any(len(row) != len(labels) for row in values):
        return None

    return {
        "id": "confusion-matrix",
        "title": "Матрица ошибок",
        "description": (
            "Строка — истинный класс, столбец — предсказанный класс."
        ),
        "data": [
            {
                "type": "heatmap",
                "z": values,
                "x": labels,
                "y": labels,
                "colorscale": [
                    [0, "#121c28"],
                    [0.45, "#1b6c58"],
                    [1, "#39ff88"],
                ],
                "text": values,
                "texttemplate": "%{text}",
                "textfont": {"color": "#e7edf3"},
                "hovertemplate": (
                    "Истинный класс: %{y}<br>"
                    "Предсказанный класс: %{x}<br>"
                    "Количество: %{z}"
                    "<extra></extra>"
                ),
                "colorbar": {
                    "title": {"text": "Число изображений"},
                },
            }
        ],
        "layout": _layout(
            xaxis={"title": {"text": "Предсказанный класс"}},
            yaxis={
                "title": {"text": "Истинный класс"},
                "autorange": "reversed",
            },
        ),
    }


def build_per_class_metrics_chart(
    per_class: dict[str, Any],
) -> dict[str, Any] | None:
    labels = per_class.get("labels", [])
    precision = per_class.get("precision", [])
    recall = per_class.get("recall", [])
    f1 = per_class.get("f1", [])

    if not labels:
        return None

    if not (
        len(labels) == len(precision) == len(recall) == len(f1)
    ):
        return None

    def bar(name: str, values: list[float], color: str) -> dict[str, Any]:
        return {
            "type": "bar",
            "name": name,
            "x": labels,
            "y": values,
            "marker": {"color": color},
            "hovertemplate": (
                "Класс: %{x}<br>"
                f"{name}: %{{y:.4f}}"
                "<extra></extra>"
            ),
        }

    return {
        "id": "per-class-metrics",
        "title": "Метрики по классам",
        "description": "Precision, Recall и F1-score для каждого класса.",
        "data": [
            bar("Precision", precision, "#70a5ff"),
            bar("Recall", recall, "#39ff88"),
            bar("F1-score", f1, "#ffca57"),
        ],
        "layout": _layout(
            barmode="group",
            xaxis={"title": {"text": "Класс"}},
            yaxis={
                "title": {"text": "Значение метрики"},
                "range": [0, 1],
            },
        ),
    }


def build_charts(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    history = artifacts.get("history", {})
    curves = artifacts.get("curves", {})
    confusion_matrix = artifacts.get("confusion_matrix", {})
    per_class = artifacts.get("per_class", {})

    candidates = [
        build_loss_chart(history),
        build_accuracy_chart(history),
        build_roc_chart(curves),
        build_pr_chart(curves),
        build_confusion_matrix_chart(confusion_matrix),
        build_per_class_metrics_chart(per_class),
    ]

    return [chart for chart in candidates if chart is not None]


def percentile_value(values, percentile):
    ordered = sorted(float(value) for value in values)
    if not ordered: raise ValueError("Список anomaly score пуст")
    if len(ordered) == 1: return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    left = math.floor(position)
    right = math.ceil(position)
    if left == right: return ordered[left]
    fraction = position - left
    return (ordered[left] * (1 - fraction) + ordered[right] * fraction)


def find_youden_threshold(true_labels, anomaly_scores, positive_class):
    binary_labels = [int(label == positive_class) for label in true_labels]
    fpr, tpr, thresholds = roc_curve(binary_labels, anomaly_scores)

    candidates = [
        (true_positive_rate - false_positive_rate, threshold)
        for false_positive_rate, true_positive_rate, threshold
        in zip(fpr, tpr, thresholds)
        if math.isfinite(float(threshold))
    ]

    if not candidates: raise ValueError("Не удалось автоматически подобрать порог")
    return float(max(candidates, key=lambda item: item[0])[1])


def calculate_threshold_analysis(
    scores_document,
    percentile=95,
    mode="manual",
):
    splits = scores_document["splits"]
    test = splits["test"]
    class_ids = [scores_document["negative_class"], scores_document["positive_class"]]
    negative_class, positive_class = class_ids

    if mode == "auto":
        threshold = find_youden_threshold(
            true_labels=test["true_labels"],
            anomaly_scores=test["anomaly_scores"],
            positive_class=positive_class,
        )
    else:
        threshold = percentile_value(
            test["anomaly_scores"],
            percentile,
        )

    metrics = {}
    test_confusion_matrix = None
    test_per_class = None
    misclassified = []
    for split_name, split in splits.items():
        true_labels = split["true_labels"]
        anomaly_scores = split["anomaly_scores"]

        predicted_labels = [positive_class if score >= threshold else negative_class for score in anomaly_scores]
        precision, recall, f1, support = (
            precision_recall_fscore_support(
                true_labels,
                predicted_labels,
                labels=class_ids,
                average=None,
                zero_division=0,
            )
        )

        precision_macro, recall_macro, f1_macro, _ = (
            precision_recall_fscore_support(
                true_labels,
                predicted_labels,
                labels=class_ids,
                average="macro",
                zero_division=0,
            )
        )

        metrics[split_name] = {
            "accuracy": float(
                accuracy_score(true_labels, predicted_labels)
            ),
            "precision_macro": float(precision_macro),
            "recall_macro": float(recall_macro),
            "f1_macro": float(f1_macro),
        }

        if split_name == "test":
            matrix = confusion_matrix(
                true_labels,
                predicted_labels,
                labels=class_ids,
            )

            test_confusion_matrix = {
                "labels": [str(value) for value in class_ids],
                "values": matrix.tolist(),
            }

            test_per_class = {
                "labels": [str(value) for value in class_ids],
                "precision": [float(value) for value in precision],
                "recall": [float(value) for value in recall],
                "f1": [float(value) for value in f1],
                "support": [int(value) for value in support],
            }

            for item_id, true_label, predicted_label, score in zip(
                split["item_ids"],
                true_labels,
                predicted_labels,
                anomaly_scores,
            ):
                if true_label != predicted_label:
                    misclassified.append({
                        "item_id": item_id,
                        "true_label": true_label,
                        "predicted_label": predicted_label,
                        "score": float(score),
                    })

    return {
        "threshold": threshold,
        "percentile": percentile,
        "mode": mode,
        "metrics": metrics,
        "confusion_matrix": test_confusion_matrix,
        "per_class": test_per_class,
        "misclassified": misclassified,
    }