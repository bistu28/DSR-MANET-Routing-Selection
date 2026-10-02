#!/usr/bin/env python3
"""Generate evidence-based figures for the project summary Markdown."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS = PROJECT_ROOT / "results"
OUTPUT = RESULTS / "project_summary_assets"


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "#f7f8f6",
            "savefig.facecolor": "white",
        }
    )

    comparison = read_csv(RESULTS / "model_comparison.csv").set_index("model")
    model_order = ["random_forest", "xgboost_baseline", "best_model_tuned"]
    comparison = comparison.loc[model_order]
    metric_names = ["accuracy", "precision", "recall", "f1", "roc_auc"]
    display_names = ["Accuracy", "Precision", "Recall", "F1", "ROC AUC"]
    colors = ["#397f78", "#d08b3e", "#376b87"]

    figure, axis = plt.subplots(figsize=(10, 5.6), constrained_layout=True)
    width = 0.23
    positions = range(len(metric_names))
    for model_index, (model, color) in enumerate(zip(model_order, colors)):
        offsets = [position + (model_index - 1) * width for position in positions]
        values = comparison.loc[model, metric_names].astype(float).tolist()
        bars = axis.bar(offsets, values, width=width, label=model.replace("_", " "), color=color)
        axis.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    axis.set_xticks(list(positions), display_names)
    axis.set_ylim(0, 1.12)
    axis.set_ylabel("Score")
    axis.set_title("Held-out smoke-test performance (100 test rows)")
    axis.legend(frameon=False, ncols=3, loc="lower center", bbox_to_anchor=(0.5, -0.24))
    figure.savefig(OUTPUT / "model_metrics.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    matrix_files = {
        "Random Forest": RESULTS / "random_forest_confusion_matrix.csv",
        "XGBoost baseline": RESULTS / "xgboost_baseline_confusion_matrix.csv",
        "Tuned selected model": RESULTS / "best_model_tuned_confusion_matrix.csv",
    }
    figure, axes = plt.subplots(1, 3, figsize=(11, 4), constrained_layout=True)
    for axis, (title, path) in zip(axes, matrix_files.items()):
        matrix_frame = read_csv(path)
        matrix = matrix_frame.set_index(matrix_frame.columns[0])
        values = matrix.to_numpy(dtype=int)
        image = axis.imshow(values, cmap="YlGnBu", vmin=0, vmax=values.max())
        for row in range(values.shape[0]):
            for column in range(values.shape[1]):
                axis.text(column, row, str(values[row, column]), ha="center", va="center", color="#152328", fontsize=13)
        axis.set_xticks([0, 1], ["Pred 0", "Pred 1"])
        axis.set_yticks([0, 1], ["Actual 0", "Actual 1"])
        axis.set_title(title)
        axis.set_xlabel("Predicted class")
        axis.set_ylabel("Actual class")
    figure.colorbar(image, ax=axes, shrink=0.78, label="Test observations")
    figure.suptitle("Confusion matrices: fixed 100-row test split", fontweight="bold")
    figure.savefig(OUTPUT / "confusion_matrices.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    importance = read_csv(RESULTS / "feature_importance.csv").sort_values("importance", ascending=True).tail(10)
    figure, axis = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
    axis.barh(importance["feature"], importance["importance"], color="#397f78")
    axis.set_xlabel("Reported importance")
    axis.set_title("Top 10 features in saved selected-model importance output")
    axis.grid(axis="x", alpha=0.2)
    figure.savefig(OUTPUT / "feature_importance.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    smoke = read_csv(PROJECT_ROOT / "data/final/smoke_test/features.csv")
    figure, axis = plt.subplots(figsize=(7.5, 5.3), constrained_layout=True)
    palette = {0: "#397f78", 1: "#c45d48"}
    for label, group in smoke.groupby("route_failure"):
        axis.scatter(
            group["link_quality"],
            group["packet_loss"],
            s=26,
            alpha=0.65,
            color=palette[int(label)],
            edgecolors="none",
            label=f"route_failure={int(label)} (n={len(group)})",
        )
    axis.set_xlabel("Link quality (generated, unit interval)")
    axis.set_ylabel("Packet loss (generated, unit interval)")
    axis.set_title("Smoke-data feature scatter, not measured network observations")
    axis.legend(frameon=False, loc="center left", bbox_to_anchor=(1.02, 0.5))
    axis.grid(alpha=0.2)
    figure.savefig(OUTPUT / "smoke_feature_scatter.png", dpi=180, bbox_inches="tight")
    plt.close(figure)

    print(f"Wrote summary figures to {OUTPUT}")


if __name__ == "__main__":
    main()
