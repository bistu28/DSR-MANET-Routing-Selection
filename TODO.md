# Project TODO

Stage 2 remains in progress. Do not claim completion or launch the full
180-scenario matrix until the local pilot and resource/readiness gates pass
and explicit approval is recorded.

- [x] Inventory local project, NS-3.48 checkout, toolchain, dependencies, and available disk.
- [x] Confirm the 180-row scenario matrix and preserve existing outputs.
- [x] Add a local resumable scenario runner with validation and an approval guard.
- [x] Build and run isolated instrumented NS-3.48 baseline and controlled-outage checks.
- [ ] Recover authoritative Stage 1 aggregates/manifests and prior pilot evidence, or document their absence.
- [ ] Complete edge-hook regression, 500-node capacity measurement, and logging-overhead estimate; obtain safer disk headroom.
- [x] Produce a preliminary full-matrix runtime, memory, and disk estimate.
- [ ] Obtain explicit approval before running all 180 scenarios.
- [ ] Generate and audit evidence-aligned ML-ready datasets after validated simulations; do not train final models.

See [STAGE2_TODO.md](./STAGE2_TODO.md), [STAGE2_PROGRESS_LOG.md](./STAGE2_PROGRESS_LOG.md),
and [ns3/README.md](./ns3/README.md) for tracked detail and recovery steps.
