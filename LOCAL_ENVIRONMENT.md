# Local macOS execution environment

The Stage 2 simulation and data-preparation workflow is local; it does not
require Colab or cloud execution. The verified development setup is:

- macOS on Apple Silicon
- NS-3.48 source commit `d2add90b452d600cfb4859baed8e9ea633519447`
- Apple clang 17, CMake 4.4.3, Ninja, and an NS-3 default-profile build with
  examples/tests enabled
- Homebrew Python 3.13 in an isolated environment at
  `/Users/bistupaul/.venvs/dsr-manet-stage2-py313`
- Python dependency pins in `requirements-local.lock.txt`

Recreate the Python environment without placing it in the repository:

```bash
python3.13 -m venv /Users/bistupaul/.venvs/dsr-manet-stage2-py313
/Users/bistupaul/.venvs/dsr-manet-stage2-py313/bin/python -m pip install \
  -r requirements-local.lock.txt
```

To intentionally update dependencies, first review `requirements.txt`, install
its declared ranges into a disposable local environment, run the focused tests
and data-pipeline checks, and only then refresh `requirements-local.lock.txt`.
Do not silently regenerate or loosen the lock.

Verify the environment and simulator:

```bash
/Users/bistupaul/.venvs/dsr-manet-stage2-py313/bin/python -m pip check
/Users/bistupaul/.venvs/dsr-manet-stage2-py313/bin/python -m unittest discover -s tests -v
bash ns3/dsr_instrumentation/apply.sh /Users/bistupaul/ns-3.48
cd /Users/bistupaul/ns-3.48
./ns3 show config
./ns3 build -j 4
```

The NS-3 checkout is intentionally separate and has local experimental changes.
The apply script verifies the source commit and hashes and is idempotent for the
reviewed patch. Do not reset or clean that checkout.

## Outputs and recovery

Simulation attempts default to `~/Movies/MANET_STAGE2_RUNS`, outside Git. Keep
the execution manifest, attempt logs, and outputs together. After interruption,
rerun the same bounded runner command: completed outputs are revalidated and
skipped; incomplete scenarios resume with a new attempt directory. Never reuse
an output root after changing the matrix, NS-3 commit, instrumentation patch, or
scenario parameters. Inspect a stale lock and verify that no runner is active
before removing it.

Do not run the 180-scenario matrix until the baseline/outage validations,
resource estimate, evidence and readiness gates are reviewed and explicit
approval is recorded.
