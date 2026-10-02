# packet_loss experiment

- Target: `loss_occurred` (dataset-specific target, not `route_failure`).
- Rows evaluated: 50000.
- Class balance: {'0': 39246, '1': 10754}.
- Validation-F1 selection: `xgboost_baseline`; scores: {'random_forest': 0.6325381935138032, 'xgboost_baseline': 0.9056224899598394}.
- Scope: RF/XGBoost evaluation on this dataset's own target only; this does not validate the dissertation's DSR route-failure framework.

## Outcome-Derived Fields

`cause_label` and `drop_reason` are explicitly excluded as leakage: they describe the cause/reason for an already observed loss and are not available as pre-outcome predictors. Their exclusion is semantic, not merely a side effect of their text dtype.
Audit exclusions: `{'cause_label': {'reason': 'Describes the cause of the observed packet loss; unavailable before the labeled outcome.', 'observed_dtype': 'object', 'also_non_numeric': True, 'excluded_by_explicit_leakage_rule': True}, 'drop_reason': {'reason': 'Describes why the packet was dropped; outcome-derived and unavailable before the labeled outcome.', 'observed_dtype': 'object', 'also_non_numeric': True, 'excluded_by_explicit_leakage_rule': True}}`.
