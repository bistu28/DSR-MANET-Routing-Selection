# Colab setup recovery

The setup notebook expects the linked project root at
`My Drive/DISSERTATION` by default. To use another existing folder under
`MyDrive`, set `STAGE2_PROJECT_DIR` in the runtime before running the first
cell.

If the first cell reports that setup sources are missing:

1. Run `python3 -m colab.build_setup_bundle` in the local project.
2. In Colab, use **File → Upload notebook** and select the current
   `/Users/bistupaul/Movies/DISSERTATION/colab/00_environment_setup.ipynb`.
   The earlier executed copy has stale cell code.
3. Rerun its first code cell.
4. When Colab prompts for a file, upload
   `colab/stage2_setup_sources.zip` from this project.
5. Confirm the cell reports the project path and verifies the instrumentation
   package. If it reports a conflict or hash mismatch, stop; do not overwrite
   Drive files or use a different archive.
6. Run the setup-mode code cell. `AUTO` verifies dependencies and either
   restores a compatible build or builds the pinned NS-3.48 source under
   `/content`.
7. Run the current project-local `colab/01_environment_verification.ipynb` and retain its output and
   environment manifest.

If the setup cell reports that module `colab` is missing, rerun the first cell
successfully before running the setup-mode cell. Do not execute simulations or
the 180-run matrix as part of environment setup.

The build is runtime-local and may not survive a Colab disconnect. On reconnect,
mount Drive and rerun setup in `AUTO` mode; the manager only restores a build
when its runtime/source fingerprint matches. It refuses to overwrite an
incompatible build.
