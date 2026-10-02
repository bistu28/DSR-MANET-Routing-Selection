# DSR-ML-MANET

VS Code is the editing interface; Google Colab is the execution environment. Persistent files live in this project directory, while ns-3 compilation stays on Colab local storage at `/content/ns-3.47`.

## Colab sequence

1. In VS Code, edit this project and sync it to Drive as `DSR-ML-MANET` without changing the directory layout.
2. In Colab, mount Drive and set `PROJECT_DIR` to the mounted project path.
3. Run `!bash "$PROJECT_DIR/setup_colab.sh"`. This installs dependencies, clones and verifies ns-3.47, verifies DSR, builds the smoke source, and copies outputs back.
4. For later iterations run `!bash "$PROJECT_DIR/run_colab.sh"`; it recopies source/configuration, builds locally, runs ns-3, and launches the ML smoke experiment.
5. Refresh the project in VS Code to inspect `ns3/results/`, `data/`, `models/`, and `results/`.

Do not build ns-3 under Drive. Do not use ML features computed after a route failure to predict that failure. The pipeline writes audit reports and uses one fixed split for RF and XGBoost.

The first simulation is deliberately baseline DSR only: 20 nodes, Wi-Fi ad hoc, RandomWalk2d mobility, one UDP source and destination, and 100 seconds. RF/XGBoost integration belongs after the data contract and baseline experiments are validated.
