
```bash
python3 ml/run_experiment.py --input-dir data/raw --project-dir . --smoke-test
```

To run only the cleaning stage, use the dedicated CLI. It always saves the cleaned CSV and audit report directly inside `data/cleaned/`:

```bash
python3 ml/clean_dataset.py \
	--input-dir data/raw \
	--input-file data/raw/manet_dataset.csv \
	--project-dir . \
	--target link_failure
```

This creates `data/cleaned/dataset_cleaned.csv` and `data/cleaned/dataset_cleaned.audit.json`. The current `manet_dataset.csv` uses `link_failure`; the first ML experiment expects the explicitly defined `route_failure` target, so do not rename or map that column without documenting the label definition.

To clean every raw CSV independently, without merging files:

```bash
python3 ml/clean_dataset.py \
	--input-dir data/raw \
	--project-dir . \
	--all
```

This creates one `<original_name>_cleaned.csv`, one `<original_name>_audit.json`, and `data/cleaned/cleaning_summary.csv`. Targets are detected per file and preserved under their original normalized names. Missing target values are reported but never imputed. Numeric outliers are reported and retained.

To run feature engineering independently on every cleaned CSV, without merging datasets:

```bash
python3 ml/feature_engineering.py \
	--input-dir data/cleaned \
	--output-dir data/processed \
	--all
```

This creates one `<original_name>_features.csv`, one `<original_name>.features.json`, and `data/processed/feature_engineering_summary.csv`. Metadata and source target columns are retained in each output; metadata and targets are excluded from the model feature list. Files without targets are still processed as generic feature datasets. No feature-engineered files are merged.

`clean_dataset.py` normalizes columns, reports duplicates/missing values/invalid values/outliers, imputes missing values, validates the binary target, and records suspicious leakage columns instead of silently deleting them. `feature_engineering.py` selects numeric pre-failure features and creates only deterministic interactions. `run_experiment.py` uses the same feature matrix, stratified train/validation/test split, and evaluation code for Random Forest and XGBoost; selects on validation F1 after baseline test evaluation; then tunes only the selected model using five-fold CV on train plus validation and evaluates once on the untouched test set.

## Data organization audit

Run the non-merging data-management stage with the project environment:

```bash
venv/bin/python ml/organize_data.py --project-dir .
```

It inventories every raw CSV, regenerates cleaned copies and audits, classifies processed outputs, writes `data/processed/dataset_registry.csv` and `column_mapping.csv`, and creates purpose-specific outputs under `data/final/`. It never changes raw CSVs, renames targets, or joins datasets. The pre-organization hash manifest is retained under `data/manifests_pre_organization/`.
