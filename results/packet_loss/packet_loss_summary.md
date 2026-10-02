# packet_loss Experiment Summary

Target: `loss_occurred` (this is `loss_occurred`, not `route_failure`).

Rows: 50,000 cleaned rows; 40,000 train/validation rows and 10,000 held-out test rows.

Class balance: {'0': 39246, '1': 10754}.

Validation F1: Random Forest 0.6325; XGBoost 0.9056. Selected `xgboost_baseline` for tuning.

This is an evaluation of Random Forest/XGBoost on this dataset's own target only. It does not validate the dissertation's DSR route-failure framework.

See [run README](README.md) and [pipeline audit](pipeline_summary.json) for scope and leakage notes.
