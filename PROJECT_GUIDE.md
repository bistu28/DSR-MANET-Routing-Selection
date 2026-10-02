# DSR-ML-MANET Project Guide

## 1. Project purpose

This project implements the dissertation framework:

> An Intelligent Multi-Factor Route Selection and Adaptive Recovery Framework for DSR-Based MANET Using Random Forest and XGBoost

The required architecture is:

```text
VS Code: edit and review persistent project files
                    |
                    v
Google Colab: install, build, simulate, train, evaluate
                    |
                    v
DSR simulation -> data collection -> cleaning -> features
                    |
                    v
Random Forest vs XGBoost -> select winner -> tune winner
                    |
                    v
optimized model -> DSR route selection and adaptive recovery
```

VS Code is the development interface. Google Colab is the execution environment. ns-3 is compiled on Colab local storage at `/content/ns-3.47`; it must not be compiled inside Google Drive.

The current implementation provides the reproducible environment, a working DSR smoke simulation, and the complete first ML experiment. ML is not yet integrated into DSR. Integration should begin only after real data and baseline DSR results have been validated.

## 2. Directory structure

```text
DSR-ML-MANET/
├── PROJECT_GUIDE.md                 # This complete operating guide
├── README.md                        # Short project overview
├── requirements.txt                 # Python packages for Colab and ML
├── setup_colab.sh                   # Fresh Colab installation and first run
├── run_colab.sh                     # Repeat simulation and smoke ML run
├── test.ipynb                       # Existing notebook placeholder
│
├── configs/
│   ├── simulation.json              # ns-3 parameters and random seed
│   ├── ml.json                      # split, target, metric, tuning settings
│   └── experiments.json             # A/B/C/D experiment definitions
│
├── ns3/
│   ├── README.md                    # ns-3 execution notes
│   ├── run_configured.py            # Converts simulation JSON to ns-3 arguments
│   ├── scratch/
│   │   └── dsr_manet_smoke.cc       # Minimal 20-node DSR MANET simulation
│   └── results/                     # Persistent copies of ns-3 outputs
│
├── data/
│   ├── README.md                    # Data contract and leakage policy
│   ├── raw/                         # Downloaded public data and raw exports
│   ├── cleaned/                     # Cleaned data and cleaning audit
│   ├── processed/                   # Engineered features and split IDs
│   └── final/                       # Final research-ready datasets
│
├── ml/
│   ├── README.md                    # ML usage summary
│   ├── clean_dataset.py             # Cleaning and audit stage
│   ├── feature_engineering.py       # Numeric feature selection and features
│   ├── generate_smoke_dataset.py    # Deterministic pipeline validation data
│   └── run_experiment.py             # RF/XGBoost comparison and tuning
│
├── models/                          # Saved baseline and tuned models
└── results/                          # Metrics, plots, reports, and comparisons
```

`__pycache__/` folders may appear after running Python. They are generated interpreter cache files and are not research outputs.

## 3. First-time Colab setup

### 3.1 Prepare files in VS Code

1. Open `/Users/bistupaul/Movies/DISSERTATION` in VS Code.
2. Edit C++ files under `ns3/scratch/`, Python files under `ml/`, and JSON files under `configs/`.
3. Keep the existing directory names unchanged.
4. Synchronize the project directory to Google Drive, for example:

```text
/content/drive/MyDrive/DSR-ML-MANET/
```

The local VS Code computer is not assumed to be the execution machine. The files must be available from the mounted Drive path before running Colab.

### 3.2 Start a fresh Colab runtime

Run these cells in order:

```python
from google.colab import drive
drive.mount('/content/drive')
```

```python
import os
PROJECT_DIR = '/content/drive/MyDrive/DSR-ML-MANET'
os.environ['PROJECT_DIR'] = PROJECT_DIR
print(PROJECT_DIR)
```

Run the complete first-time setup:

```python
!bash "$PROJECT_DIR/setup_colab.sh"
```

The setup script:

1. Verifies that the runtime is Linux and has `apt-get`.
2. Installs gcc, g++, CMake, Ninja, Git, Python development tools, pip, pkg-config, SQLite development packages, XML/GTK/GSL dependencies, and ccache.
3. Installs Python packages from `requirements.txt`.
4. Clones the stable released ns-3.47 tag into `/content/ns-3.47`.
5. Configures ns-3 with examples and tests enabled.
6. Builds ns-3 locally on Colab storage.
7. Runs `./ns3 --version`.
8. Runs `./ns3 run "dsr --PrintHelp"` to verify the DSR example/module.
9. Copies the persistent C++ source and simulation config into the local ns-3 checkout.
10. Builds the custom program and runs the configured 20-node DSR smoke simulation.
11. Copies CSV, FlowMonitor XML, and the simulation config back to `ns3/results/` on Drive.

### 3.3 Verify ns-3 manually when needed

```python
%cd /content/ns-3.47
!./ns3 --version
!./ns3 run "dsr --PrintHelp"
```

The version must report ns-3.47 or the expected ns-3.47 tag. The DSR help command must finish successfully before custom simulation work continues.

## 4. Repeating a development run

After changing source or configuration in VS Code and synchronizing the files to Drive, run:

```python
!bash "$PROJECT_DIR/run_colab.sh"
```

This script:

1. Copies current `ns3/scratch/*.cc` to `/content/ns-3.47/scratch/`.
2. Copies current `configs/simulation.json` and the config launcher.
3. Rebuilds ns-3 locally.
4. Runs the simulation from the JSON configuration.
5. Copies simulation CSV and FlowMonitor XML back to persistent storage.
6. Runs the deterministic smoke ML pipeline.

Do not edit generated files in `/content/ns-3.47` as the source of truth. Make changes in VS Code, synchronize them, and rerun the script.

## 5. Simulation configuration

Edit `configs/simulation.json` to change the simulation without editing C++:

```json
{
  "node_count": 20,
  "simulation_time": 100.0,
  "area_size": 200.0,
  "node_speed": 5.0,
  "mobility_model": "RandomWalk2dMobilityModel",
  "traffic_rate": "2kbps",
  "packet_size": 512,
  "source": 0,
  "destination": 19,
  "random_seed": 7,
  "random_run": 1,
  "udp_port": 9000,
  "output_dir": "results"
}
```

Important rules:

- `source` and `destination` must be different valid node indices.
- `destination` must be less than `node_count`.
- Every experiment must record `random_seed` and `random_run`.
- `mobility_model` documents the selected model; the current smoke program uses `RandomWalk2dMobilityModel`.
- `output_dir` is recorded, while the Colab launcher writes into the local ns-3 results directory and then copies outputs back.

The launcher `ns3/run_configured.py` maps snake_case JSON names to the C++ command-line names. The C++ program itself accepts `--PrintHelp` and these parameters:

```text
--nodeCount
--simulationTime
--areaSize
--nodeSpeed
--trafficRate
--packetSize
--source
--destination
--randomSeed
--randomRun
--port
--outputDir
```

## 6. Current DSR smoke simulation

The source file `ns3/scratch/dsr_manet_smoke.cc` currently implements:

- 20 nodes by default.
- Wi-Fi ad-hoc mode.
- Random rectangle initial positions.
- RandomWalk2d mobility.
- DSR as the routing protocol.
- One UDP source and one UDP destination.
- 100-second simulation time by default.
- UDP packet generation using the configured rate and packet size.
- FlowMonitor collection.
- A configurable random seed and run number.

The output CSV contains:

```text
flow_id
source
destination
tx_packets
rx_packets
tx_bytes
rx_bytes
packet_loss
pdr
throughput_bps
delay_ms
random_seed
```

The output files are named using the seed, for example:

```text
ns3/results/dsr_smoke_seed_7.csv
ns3/results/dsr_smoke_seed_7.flowmon.xml
ns3/results/simulation.json
```

The first smoke simulation is deliberately baseline DSR only. It does not implement Random Forest, XGBoost, route scoring, cached-route recovery, or model inference.

## 7. Research data collection plan

The final research dataset should eventually include these feature families:

| Factor | Type | Use before failure? |
|---|---|---|
| Node speed or mobility | Feature | Yes |
| Link quality | Feature | Yes |
| RSSI/SNR | Feature | Yes, when available |
| End-to-end delay | Feature | Yes, measured up to prediction time |
| Packet loss | Feature | Yes |
| Packet Delivery Ratio | Feature | Yes |
| Throughput | Feature | Yes |
| Queue length/congestion | Feature | Yes |
| Remaining energy | Feature | Yes |
| Hop count | Feature | Yes |
| Route stability/history | Feature | Yes, historical window only |
| Route failure event | Label/event | Future outcome for the row |
| Recovery event | Post-failure outcome | No, not as an input to that failure |
| DSR discovery information | Feature/event | Only information observed by prediction time |
| RREQ/RREP/RERR information | Feature/event | Timestamp and use only prior messages |

The first target is:

```text
route_failure = 0: the active route remains usable through the prediction window
route_failure = 1: the active route fails within the prediction window
```

A row must have a prediction timestamp. The label may look ahead from that timestamp to determine whether a failure occurs within the configured prediction window, but input features must be measured at or before that timestamp.

Do not use these as features for the same failure prediction:

- future failure timestamps;
- post-failure packet counters;
- recovery duration or recovery success;
- cached-route selection after failure;
- labels or target-derived columns;
- any event recorded after the prediction timestamp.

The current smoke source collects transport-level metrics through FlowMonitor. Mobility, RSSI/SNR, queue occupancy, energy, DSR control messages, route history, and explicit recovery events still require additional ns-3 instrumentation before they can support the final dissertation experiments.

## 8. Dataset placement and cleaning

Place the downloaded public dataset in:

```text
data/raw/
```

The dataset must contain a binary `route_failure` column for the first ML implementation. If the public dataset uses another target name or does not already contain this label, create a documented conversion step before training. Do not invent labels silently.

Run the cleaning and ML pipeline against a specific file:

```bash
python3 ml/run_experiment.py \
  --input-dir data/raw \
  --input-file data/raw/your_dataset.csv \
  --project-dir .
```

To run only cleaning, use the dedicated CLI:

```bash
python3 ml/clean_dataset.py \
  --input-dir data/raw \
  --input-file data/raw/manet_dataset.csv \
  --project-dir . \
  --target link_failure
```

The CLI always writes directly to `data/cleaned/dataset_cleaned.csv` and writes its audit report to `data/cleaned/dataset_cleaned.audit.json`. The current `manet_dataset.csv` contains `link_failure`, while the first ML experiment expects `route_failure`; any mapping between these labels must be explicitly defined and documented.

To clean every CSV independently, without merging datasets, run:

```bash
python3 ml/clean_dataset.py \
  --input-dir data/raw \
  --project-dir . \
  --all
```

The batch command detects `route_failure`, `link_failure`, `loss_occurred`, and other target-like columns per file. It preserves target names and metadata, reports outliers without removing them, leaves missing target values unfilled, skips duplicate files by identical SHA-256 content, and writes `data/cleaned/cleaning_summary.csv`.

In Colab:

```python
!python3 "$PROJECT_DIR/ml/run_experiment.py" \
  --input-dir "$PROJECT_DIR/data/raw" \
  --input-file "$PROJECT_DIR/data/raw/your_dataset.csv" \
  --project-dir "$PROJECT_DIR"
```

The cleaning stage in `ml/clean_dataset.py` performs and records:

1. Column inspection.
2. Column-name normalization to lowercase underscore names.
3. Duplicate counting and removal.
4. Data-type correction for numeric-looking object columns.
5. Missing-value analysis before cleaning.
6. Non-finite value detection.
7. Missing-value handling using numeric medians and categorical modes.
8. IQR outlier analysis.
9. Binary target validation.
10. Leakage-column detection based on names indicating future, post-failure, recovery, outcome, or label information.
11. Class-distribution reporting.

Suspicious values are not silently ignored:

- duplicate counts are recorded;
- non-finite counts are recorded;
- outlier counts are reported and not automatically removed;
- leakage columns and removal reasons are written to the audit report;
- invalid target values stop the pipeline with an error rather than being deleted.

Cleaning outputs:

```text
data/cleaned/dataset_cleaned.csv
 data/cleaned/dataset_cleaned.audit.json
```

## 9. Feature engineering

`ml/feature_engineering.py` reads the cleaned dataset and writes:

```text
data/processed/features.csv
data/processed/features.features.json
```

The current stage:

- excludes the target;
- excludes timestamp, time, node ID, and flow ID columns;
- selects numeric columns;
- creates `loss_delay_interaction`;
- creates `mobility_risk` from speed and route stability when available;
- records the final feature list.

Categorical variables are not currently one-hot encoded. If the public dataset requires categorical features, add a documented preprocessing stage before comparing models and apply the same transformation to both models.

## 10. Exact ML experiment order

`ml/run_experiment.py` follows this order:

```text
1. Read raw data
2. Clean and audit the dataset
3. Engineer one shared feature matrix
4. Create one stratified train/validation/test split
5. Train Random Forest baseline
6. Train XGBoost baseline
7. Evaluate both baselines on the same untouched test set
8. Select the better baseline using validation F1
9. Tune only the selected model using five-fold CV on train + validation data
10. Evaluate the tuned model once on the untouched test set
11. Save models, metrics, reports, plots, and tuning configuration
```

The baseline metrics are:

- Accuracy
- Precision
- Recall
- F1-score
- ROC-AUC
- Confusion matrix
- Inference time

The predefined selection metric is validation F1 from `configs/ml.json`. The test set is not used to choose the model or hyperparameters.

The ML configuration is:

```json
{
  "target": "route_failure",
  "prediction_window_seconds": 5.0,
  "random_seed": 7,
  "test_size": 0.20,
  "validation_size": 0.20,
  "selection_metric": "f1",
  "n_jobs": -1,
  "tuning_iterations": 12
}
```

## 11. ML outputs

After a successful experiment, expect:

```text
models/
├── random_forest.joblib
├── xgboost_baseline.joblib
├── best_model_tuned.joblib
└── tuning_config.json

results/
├── model_comparison.csv
├── pipeline_summary.json
├── feature_importance.csv
├── roc_curves.png
├── random_forest_confusion_matrix.csv
├── random_forest_classification_report.json
├── xgboost_baseline_confusion_matrix.csv
├── xgboost_baseline_classification_report.json
├── best_model_tuned_confusion_matrix.csv
└── best_model_tuned_classification_report.json
```

The generated split membership is recorded in:

```text
data/processed/split_train.csv
data/processed/split_validation.csv
data/processed/split_test.csv
```

## 12. Smoke-test the ML pipeline before public data

The smoke test creates a deterministic 500-row dataset and runs the complete experiment:

```bash
python3 ml/run_experiment.py \
  --input-dir data/raw \
  --project-dir . \
  --smoke-test
```

This writes `data/raw/smoke_route_failure.csv`. It is only a pipeline validation dataset, not dissertation evidence. Use `--input-file` for a public dataset so the selected input is unambiguous when several CSV files exist in `data/raw/`.

## 13. Four final experiment configurations

`configs/experiments.json` defines the intended comparison:

```text
A. Baseline DSR
B. DSR + Random Forest
C. DSR + XGBoost
D. DSR + Tuned Best Model
```

The final network comparison should report:

- PDR;
- throughput;
- end-to-end delay;
- packet loss;
- routing overhead;
- route failures;
- recovery time;
- recovery success rate.

The ML comparison should report:

- accuracy;
- precision;
- recall;
- F1-score;
- ROC-AUC;
- inference time.

The current code prepares the experiment manifest and baseline artifacts. It does not yet execute the four DSR-integrated conditions. That requires adding route feature extraction, model inference, route scoring, monitoring, cached-route recovery, and DSR rediscovery instrumentation in ns-3.

The intended integrated behavior is:

```text
DSR route discovery
        -> candidate routes
        -> feature extraction
        -> optimized ML model
        -> route failure risk / route quality
        -> multi-factor route selection
        -> active route
        -> continuous monitoring
        -> adaptive recovery when risk increases
             -> cached alternative route
             -> DSR rediscovery if no cached route exists
```

DSR remains the underlying routing protocol. The ML model must assist route selection and recovery; it must not replace DSR.

## 14. Validation checklist

### Environment and ns-3

- [ ] Drive is mounted and `PROJECT_DIR` points to the persistent project.
- [ ] `/content/ns-3.47` is on Colab local storage.
- [ ] Required apt dependencies install successfully.
- [ ] Python dependencies install from `requirements.txt`.
- [ ] `./ns3 --version` reports the expected version.
- [ ] `./ns3 run "dsr --PrintHelp"` succeeds.
- [ ] ns-3 builds with examples enabled.
- [ ] `dsr_manet_smoke` builds and runs.
- [ ] CSV and FlowMonitor XML are copied to `ns3/results/`.
- [ ] The recorded seed and configuration are preserved.

### Data and ML

- [ ] Raw public data is present in `data/raw/`.
- [ ] The target is defined and binary.
- [ ] Cleaning audit is reviewed.
- [ ] Suspicious values and outlier decisions are documented.
- [ ] Leakage report is reviewed.
- [ ] Class distribution is acceptable or documented.
- [ ] Features are available before the prediction timestamp.
- [ ] RF and XGBoost use the same split and feature matrix.
- [ ] Baselines are evaluated before model selection.
- [ ] Only the selected baseline is tuned.
- [ ] The final test set remains untouched until final evaluation.
- [ ] The tuned model and tuning configuration are saved.

### Reproducibility

- [ ] Run from a fresh Colab runtime.
- [ ] Use a recorded random seed and run number.
- [ ] Keep source/configuration files in persistent storage.
- [ ] Build ns-3 only on `/content`.
- [ ] Copy outputs back to the existing project directories.
- [ ] Record the ns-3 tag, Python package versions, configuration, and dataset identity for every final run.

## 15. Troubleshooting

### `apt-get` is missing

The setup script is intended for Google Colab/Linux. Do not run `setup_colab.sh` on macOS. On macOS, use a virtual environment only for optional local Python checks; run ns-3 through Colab as designed.

### XGBoost cannot load OpenMP on macOS

This is a local macOS dependency issue, not a Colab setup issue. The Colab Linux runtime receives the required runtime through apt. For local testing on Apple Silicon, install the system OpenMP runtime with Homebrew and rerun inside the project virtual environment.

### Target is missing

Pass the correct `--input-file` and inspect the CSV columns. The current first implementation requires a column that normalizes to `route_failure`. Do not rename or derive the target without documenting the label-generation rule.

### Target has values other than 0 and 1

Stop and document the mapping. The pipeline intentionally refuses to silently delete invalid labels.

### Several CSV files are in `data/raw/`

Use `--input-file` explicitly. `--smoke-test` explicitly selects the generated smoke dataset, but normal runs select the first CSV unless an input file is supplied.

### ns-3 changes do not appear in Colab

Confirm that the edited project files were synchronized to Drive, rerun the copy/build step, and check `/content/ns-3.47/scratch/` before executing the simulation.

### Results are missing from VS Code

Confirm that the Colab script completed its copy-back commands and inspect the persistent paths `ns3/results/`, `data/cleaned/`, `data/processed/`, `models/`, and `results/`.

## 16. Recommended next implementation steps

1. Run the fresh-Colab setup and preserve the ns-3 version output.
2. Confirm the 20-node DSR smoke CSV has transmitted and received packets.
3. Define the raw simulation event schema with timestamps and route identifiers.
4. Add pre-failure logging for mobility, link quality, RSSI/SNR, queues, energy, hops, DSR discovery, and route history.
5. Define failure-window label generation without post-failure leakage.
6. Run the ML pipeline on the real dataset and archive its audit and split files.
7. Implement A, baseline DSR, as the network evaluation reference.
8. Add route feature extraction and offline model inference before online integration.
9. Implement B, C, and D as separate reproducible configurations.
10. Add adaptive recovery and compare network and ML metrics across all four conditions.
