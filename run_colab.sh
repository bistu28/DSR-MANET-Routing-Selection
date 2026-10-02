#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/content/drive/MyDrive/DSR-ML-MANET}"
NS3_DIR="/content/ns-3.47"

mkdir -p "$NS3_DIR/scratch" "$NS3_DIR/results"
cp -f "$PROJECT_DIR/ns3/scratch/"*.cc "$NS3_DIR/scratch/"
cp -f "$PROJECT_DIR/configs/simulation.json" "$NS3_DIR/results/simulation.json"
cp -f "$PROJECT_DIR/ns3/run_configured.py" "$NS3_DIR/results/run_configured.py"
cd "$NS3_DIR"
./ns3 build
python3 "$NS3_DIR/results/run_configured.py" --ns3-dir "$NS3_DIR" --config "$NS3_DIR/results/simulation.json"
cp -f "$NS3_DIR/results/"dsr_smoke_seed_*.csv "$PROJECT_DIR/ns3/results/"
cp -f "$NS3_DIR/results/"dsr_smoke_seed_*.flowmon.xml "$PROJECT_DIR/ns3/results/"
python3 "$PROJECT_DIR/ml/run_experiment.py" --input-dir "$PROJECT_DIR/data/raw" --project-dir "$PROJECT_DIR" --smoke-test
