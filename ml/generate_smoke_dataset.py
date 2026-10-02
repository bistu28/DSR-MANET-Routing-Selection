from pathlib import Path
import argparse
import numpy as np
import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--rows", type=int, default=500)
parser.add_argument("--seed", type=int, default=7)
args = parser.parse_args()
rng = np.random.default_rng(args.seed)
rows = args.rows
frame = pd.DataFrame({
    "node_speed": rng.uniform(0, 15, rows),
    "link_quality": rng.uniform(0, 1, rows),
    "rssi_dbm": rng.normal(-65, 8, rows),
    "snr_db": rng.normal(18, 5, rows),
    "end_to_end_delay_ms": rng.gamma(2, 8, rows),
    "packet_loss": rng.uniform(0, 0.5, rows),
    "pdr": rng.uniform(0.5, 1, rows),
    "throughput_bps": rng.uniform(1e4, 2e5, rows),
    "queue_length": rng.poisson(4, rows),
    "remaining_energy": rng.uniform(0.1, 1, rows),
    "hop_count": rng.integers(1, 8, rows),
    "route_stability": rng.uniform(0, 1, rows),
    "route_failure_events_before": rng.poisson(1, rows),
})
score = (frame["node_speed"] / 15 + frame["packet_loss"] + (1 - frame["link_quality"]) + (1 - frame["remaining_energy"]) + frame["route_failure_events_before"] / 5)
frame["route_failure"] = (score + rng.normal(0, 0.2, rows) > 1.7).astype(int)
args.output.parent.mkdir(parents=True, exist_ok=True)
frame.to_csv(args.output, index=False)
print(f"wrote {len(frame)} rows to {args.output}")
