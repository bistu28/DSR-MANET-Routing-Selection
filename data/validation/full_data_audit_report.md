# Full Data Audit Report

## Summary

- Step 1: 🟢 COMPLETE
- Step 2: 🟡 PARTIAL
- Step 3: 🟡 PARTIAL
- Step 4: 🟡 PARTIAL
- Step 5: 🟡 PARTIAL
- Step 6: 🟡 PARTIAL
- Step 7: 🔴 MISSING
- Step 8: 🟡 PARTIAL
- Step 9: 🔴 MISSING
- Step 10: 🟡 PARTIAL

## Key evidence

- `Simulation_data.csv` exists with 180 manifest rows and 32 columns.
- `Topology_data.csv` exists but only covers 1 scenario (`scenario_id` unique count = 1).
- `Mobility_data.csv` exists but only covers 5 scenarios (`scenario_id` unique count = 5).
- `data/final/` and `data/processed/` are empty.
- Generic routing info exists, but no DSR-specific route state or route recovery metadata was found.

