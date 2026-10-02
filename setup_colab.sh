#!/usr/bin/env bash
set -euo pipefail

# Run this from a fresh Colab runtime after mounting Drive and exporting PROJECT_DIR.
PROJECT_DIR="${PROJECT_DIR:-/content/drive/MyDrive/DSR-ML-MANET}"
NS3_DIR="/content/ns-3.47"
NS3_VERSION="ns-3.47"

command -v apt-get >/dev/null || { echo "This script must run in Google Colab/Linux."; exit 1; }
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  gcc g++ cmake ninja-build git python3 python3-dev python3-pip pkg-config \
  libsqlite3-dev sqlite3 libxml2-dev libgtk-3-dev libgsl-dev ccache

python3 -m pip install --upgrade pip
python3 -m pip install -r "$PROJECT_DIR/requirements.txt"

if [[ ! -d "$NS3_DIR" ]]; then
  git clone --depth 1 --branch "$NS3_VERSION" https://gitlab.com/nsnam/ns-3-dev.git "$NS3_DIR"
fi
cd "$NS3_DIR"

git describe --tags --always
./ns3 configure --enable-examples --enable-tests -- -DNS3_WARNINGS_AS_ERRORS=OFF
./ns3 build
./ns3 --version
./ns3 run "dsr --PrintHelp"

mkdir -p "$NS3_DIR/scratch" "$NS3_DIR/results"
cp -f "$PROJECT_DIR/ns3/scratch/"*.cc "$NS3_DIR/scratch/" 2>/dev/null || true
cp -f "$PROJECT_DIR/configs/simulation.json" "$NS3_DIR/results/simulation.json"
cp -f "$PROJECT_DIR/ns3/run_configured.py" "$NS3_DIR/results/run_configured.py"
./ns3 build
python3 "$NS3_DIR/results/run_configured.py" --ns3-dir "$NS3_DIR" --config "$NS3_DIR/results/simulation.json"
cp -f "$NS3_DIR/results/"dsr_smoke_seed_*.csv "$PROJECT_DIR/ns3/results/" 2>/dev/null || true
cp -f "$NS3_DIR/results/"dsr_smoke_seed_*.flowmon.xml "$PROJECT_DIR/ns3/results/" 2>/dev/null || true
cp -f "$NS3_DIR/results/simulation.json" "$PROJECT_DIR/ns3/results/" 2>/dev/null || true

echo "Colab setup and DSR smoke simulation completed. Project files: $PROJECT_DIR"
