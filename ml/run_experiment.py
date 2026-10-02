from __future__ import annotations
from pathlib import Path
import argparse
import json
import sys
import time
import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import RandomizedSearchCV, train_test_split
from xgboost import XGBClassifier
from clean_dataset import clean_frame
from feature_engineering import engineer

def metrics(model, x_test, y_test, name, output_dir):
    start = time.perf_counter(); predictions = model.predict(x_test); elapsed = time.perf_counter() - start
    probabilities = model.predict_proba(x_test)[:, 1]
    values = {"model": name, "accuracy": accuracy_score(y_test, predictions),
              "precision": precision_score(y_test, predictions, zero_division=0),
              "recall": recall_score(y_test, predictions, zero_division=0),
              "f1": f1_score(y_test, predictions, zero_division=0),
              "roc_auc": roc_auc_score(y_test, probabilities),
              "inference_time_seconds": elapsed, "test_rows": len(y_test)}
    matrix = confusion_matrix(y_test, predictions)
    pd.DataFrame(matrix, index=["actual_0", "actual_1"], columns=["predicted_0", "predicted_1"]).to_csv(output_dir / f"{name}_confusion_matrix.csv")
    report = classification_report(y_test, predictions, output_dict=True, zero_division=0)
    (output_dir / f"{name}_classification_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return values, probabilities


def _safe_run_name(value):
    if value is None:
        return None
    if not value or value in {".", ".."} or Path(value).name != value:
        raise argparse.ArgumentTypeError("run-name must be one path component")
    return value


def _link_failure_counter_review(frame, target):
    counters = ["tx_packets", "rx_packets", "lost_packets", "delay_sum"]
    present = [column for column in counters if column in frame.columns]
    counts = {
        column: {
            "nonzero_rows": int(frame[column].ne(0).sum()),
            "unique_values": int(frame[column].nunique(dropna=False)),
        }
        for column in present
    }
    lost_positive = int(frame["lost_packets"].gt(0).sum()) if "lost_packets" in present else None
    failure_with_loss = (
        int((frame[target].eq(1) & frame["lost_packets"].gt(0)).sum())
        if "lost_packets" in present else None
    )
    nonfailure_with_loss = (
        int((frame[target].eq(0) & frame["lost_packets"].gt(0)).sum())
        if "lost_packets" in present else None
    )
    if not lost_positive:
        implication = "not_assessable_no_rows_with_lost_packets_gt_zero"
    elif not nonfailure_with_loss:
        implication = "every_nonzero_loss_row_is_labeled_failure"
    else:
        implication = "nonzero_loss_does_not_mechanically_imply_failure"
    all_counters_zero = bool(present) and all(counts[column]["nonzero_rows"] == 0 for column in present)
    return {
        "checked_columns": present,
        "counter_observations": counts,
        "target_positive_rows": int(frame[target].eq(1).sum()),
        "rows_with_lost_packets_gt_zero": lost_positive,
        "target_positive_rows_with_lost_packets_gt_zero": failure_with_loss,
        "target_zero_rows_with_lost_packets_gt_zero": nonfailure_with_loss,
        "same_row_loss_implication_assessment": implication,
        "all_checked_counters_constant_zero": all_counters_zero,
        "temporal_aggregation_semantics_confirmed_from_csv": False,
        "interpretation": (
            ("All checked counters are constant zero, so there is no nonzero loss signal with which "
             "to test same-row implication. " if all_counters_zero else
             f"Same-row loss assessment: {implication}. ")
            + "The CSV does not establish whether counters are cumulative, windowed, or timestamp-bounded; prediction-window semantics remain unverified. "
            "Treat this as link_failure classification only, not forecasting or route_failure evidence."
        ),
    }


def _write_run_readme(results_dir, target, rows, class_balance, validation_scores, selected, audit):
    counter_review = audit.get("link_failure_counter_review")
    text = [
        f"# {results_dir.name} experiment",
        "",
        f"- Target: `{target}` (dataset-specific target, not `route_failure`).",
        f"- Rows evaluated: {rows}.",
        f"- Class balance: {class_balance}.",
        f"- Validation-F1 selection: `{selected}`; scores: {validation_scores}.",
        "- Scope: RF/XGBoost evaluation on this dataset's own target only; this does not validate the dissertation's DSR route-failure framework.",
    ]
    if counter_review:
        text.extend([
            "",
            "## Timing and Leakage Review",
            "",
            counter_review["interpretation"],
            "",
            f"Checked counters: `{counter_review['counter_observations']}`.",
        ])
    if target == "loss_occurred":
        leakage = audit.get("leakage_columns_excluded_from_features", {})
        text.extend([
            "",
            "## Outcome-Derived Fields",
            "",
            "`cause_label` and `drop_reason` are explicitly excluded as leakage: they describe the cause/reason for an already observed loss and are not available as pre-outcome predictors. Their exclusion is semantic, not merely a side effect of their text dtype.",
            f"Audit exclusions: `{leakage}`.",
        ])
    (results_dir / "README.md").write_text("\n".join(text) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--target", help="Override the target in configs/ml.json.")
    parser.add_argument("--run-name", type=_safe_run_name, help="Namespace artifacts under this run name.")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    project = args.project_dir
    raw_dir = args.input_dir; raw_dir.mkdir(parents=True, exist_ok=True)
    if args.smoke_test:
        smoke = raw_dir / "smoke_route_failure.csv"
        if not smoke.exists():
            import subprocess
            subprocess.run([sys.executable, str(project / "ml/generate_smoke_dataset.py"), "--output", str(smoke)], check=True)
    input_file = args.input_file or (smoke if args.smoke_test else sorted(raw_dir.glob("*.csv"))[0])
    config = json.loads((project / "configs/ml.json").read_text(encoding="utf-8"))
    seed = int(config["random_seed"]); target = args.target or config["target"]
    run_name = args.run_name
    cleaned_dir = project / "data/cleaned" / run_name if run_name else project / "data/cleaned"
    processed_dir = project / "data/processed" / run_name if run_name else project / "data/processed"
    models_dir = project / "models" / run_name if run_name else project / "models"
    results_dir = project / "results" / run_name if run_name else project / "results"
    cleaned_path = cleaned_dir / "dataset_cleaned.csv"
    features_path = processed_dir / "features.csv"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    frame, audit = clean_frame(input_file, cleaned_path, target)
    engineered, features = engineer(cleaned_path, features_path, target)
    features_audit_path = features_path.with_name("features.features.json")
    feature_audit = json.loads(features_audit_path.read_text(encoding="utf-8"))
    audit.update({
        "run_name": run_name,
        "target_column": target,
        "target_distribution": {str(key): int(value) for key, value in frame[target].value_counts().sort_index().items()},
        "feature_columns": features,
        "non_numeric_columns_excluded_from_features": feature_audit["non_numeric_columns_excluded_from_features"],
        "leakage_columns_excluded_from_features": feature_audit["leakage_columns_excluded_from_features"],
    })
    if target == "link_failure":
        audit["link_failure_counter_review"] = _link_failure_counter_review(frame, target)
    x = engineered[features]; y = engineered[target]
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=config["test_size"], stratify=y, random_state=seed)
    val_fraction = config["validation_size"] / (1 - config["test_size"])
    x_train, x_val, y_train, y_val = train_test_split(x_train, y_train, test_size=val_fraction, stratify=y_train, random_state=seed)
    pd.DataFrame({"row_id": x_train.index, "split": "train"}).to_csv(processed_dir / "split_train.csv", index=False)
    pd.DataFrame({"row_id": x_val.index, "split": "validation"}).to_csv(processed_dir / "split_validation.csv", index=False)
    pd.DataFrame({"row_id": x_test.index, "split": "test"}).to_csv(processed_dir / "split_test.csv", index=False)
    n_jobs = int(config["n_jobs"])
    rf = RandomForestClassifier(n_estimators=250, random_state=seed, class_weight="balanced", n_jobs=n_jobs)
    xgb = XGBClassifier(n_estimators=250, max_depth=5, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9,
                        objective="binary:logistic", eval_metric="logloss", random_state=seed, n_jobs=n_jobs)
    models = {"random_forest": rf, "xgboost_baseline": xgb}; validation_scores = {}; test_results = []
    for name, model in models.items():
        model.fit(x_train, y_train)
        validation_scores[name] = f1_score(y_val, model.predict(x_val), zero_division=0)
        result, probabilities = metrics(model, x_test, y_test, name, results_dir)
        test_results.append(result); joblib.dump(model, models_dir / f"{name}.joblib")
        fpr, tpr, _ = roc_curve(y_test, probabilities); plt.plot(fpr, tpr, label=name)
    selected = max(validation_scores, key=validation_scores.get)
    selected_model = models[selected]
    if selected == "random_forest":
        estimator = RandomForestClassifier(random_state=seed, class_weight="balanced", n_jobs=n_jobs)
        params = {"n_estimators": [150, 250, 400], "max_depth": [None, 8, 16], "min_samples_leaf": [1, 2, 4], "max_features": ["sqrt", "log2"]}
    else:
        estimator = XGBClassifier(objective="binary:logistic", eval_metric="logloss", random_state=seed, n_jobs=n_jobs)
        params = {"n_estimators": [150, 250, 400], "max_depth": [3, 5, 7], "learning_rate": [0.03, 0.08, 0.15], "subsample": [0.8, 1.0], "colsample_bytree": [0.8, 1.0]}
    search = RandomizedSearchCV(estimator, params, n_iter=int(config["tuning_iterations"]), scoring="f1", cv=5, random_state=seed, n_jobs=n_jobs, refit=True)
    search.fit(pd.concat([x_train, x_val]), pd.concat([y_train, y_val]))
    tuned_result, tuned_probabilities = metrics(search.best_estimator_, x_test, y_test, "best_model_tuned", results_dir)
    joblib.dump(search.best_estimator_, models_dir / "best_model_tuned.joblib")
    (models_dir / "tuning_config.json").write_text(json.dumps({"selected_baseline": selected, "validation_f1": validation_scores, "best_params": search.best_params_, "metric": "f1", "cv": 5}, indent=2, default=str), encoding="utf-8")
    results = pd.DataFrame(test_results + [tuned_result]); results.to_csv(results_dir / "model_comparison.csv", index=False)
    plt.plot(*roc_curve(y_test, tuned_probabilities)[:2], label="best_model_tuned", linestyle="--"); plt.plot([0, 1], [0, 1], "k:"); plt.xlabel("False positive rate"); plt.ylabel("True positive rate"); plt.legend(); plt.tight_layout(); plt.savefig(results_dir / "roc_curves.png"); plt.close()
    importance = pd.DataFrame({"feature": features, "importance": search.best_estimator_.feature_importances_}).sort_values("importance", ascending=False); importance.to_csv(results_dir / "feature_importance.csv", index=False)
    audit["selected_baseline"] = selected; audit["validation_f1"] = validation_scores; audit["test_evaluation_models"] = list(results["model"])
    audit["class_balance"] = {str(key): int(value) for key, value in y.value_counts().sort_index().items()}
    (results_dir / "pipeline_summary.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    if run_name:
        summary_path = results_dir / f"{run_name}_summary.md"
        summary_path.write_text(
            "\n".join([
                f"# {run_name} Experiment Summary", "",
                f"Target: `{target}` (this is `{target}`, not `route_failure`).", "",
                f"Rows: {len(frame):,} cleaned rows; {len(x_train) + len(x_val):,} train/validation rows and {len(x_test):,} held-out test rows.", "",
                f"Class balance: {audit['class_balance']}.", "",
                f"Validation F1: Random Forest {validation_scores['random_forest']:.4f}; XGBoost {validation_scores['xgboost_baseline']:.4f}. Selected `{selected}` for tuning.", "",
                "This is an evaluation of Random Forest/XGBoost on this dataset's own target only. It does not validate the dissertation's DSR route-failure framework.", "",
                f"See [run README](README.md) and [pipeline audit](pipeline_summary.json) for scope and leakage notes.",
            ]) + "\n",
            encoding="utf-8",
        )
        _write_run_readme(results_dir, target, len(frame), audit["class_balance"], validation_scores, selected, feature_audit | audit)
    print(json.dumps({"selected_baseline": selected, "validation_f1": validation_scores, "test_results": test_results + [tuned_result]}, indent=2))

if __name__ == "__main__":
    main()
