# link_failure Experiment Summary

Target: `link_failure` (this is `link_failure`, not `route_failure`).

Rows: 54,000 cleaned rows; 43,200 train/validation rows and 10,800 held-out test rows.

Class balance: {'0': 42815, '1': 11185}.

Validation F1: Random Forest 0.6230; XGBoost 0.7150. Selected `xgboost_baseline` for tuning.

This is an evaluation of Random Forest/XGBoost on this dataset's own target only. It does not validate the dissertation's DSR route-failure framework.

See [run README](README.md) and [pipeline audit](pipeline_summary.json) for scope and leakage notes.
