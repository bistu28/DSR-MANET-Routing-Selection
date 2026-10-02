# link_failure experiment

- Target: `link_failure` (dataset-specific target, not `route_failure`).
- Rows evaluated: 54000.
- Class balance: {'0': 42815, '1': 11185}.
- Validation-F1 selection: `xgboost_baseline`; scores: {'random_forest': 0.6230308409141335, 'xgboost_baseline': 0.7149810708491077}.
- Scope: RF/XGBoost evaluation on this dataset's own target only; this does not validate the dissertation's DSR route-failure framework.

## Timing and Leakage Review

All checked counters are constant zero, so there is no nonzero loss signal with which to test same-row implication. The CSV does not establish whether counters are cumulative, windowed, or timestamp-bounded; prediction-window semantics remain unverified. Treat this as link_failure classification only, not forecasting or route_failure evidence.

Checked counters: `{'tx_packets': {'nonzero_rows': 0, 'unique_values': 1}, 'rx_packets': {'nonzero_rows': 0, 'unique_values': 1}, 'lost_packets': {'nonzero_rows': 0, 'unique_values': 1}, 'delay_sum': {'nonzero_rows': 0, 'unique_values': 1}}`.
