# ns-3 execution

The Colab bootstrap installs ns-3.47 in `/content/ns-3.47`, never on mounted Drive. It copies `ns3/scratch/` into that checkout before building and copies generated artifacts back to this directory.

The first executable is `scratch/dsr_manet_smoke.cc`. It uses 20 mobile Wi-Fi ad-hoc nodes, DSR, one UDP source/destination pair, and a 100 second simulation. It writes a summary CSV and FlowMonitor XML. The smoke program intentionally collects transport/network metrics only; the research instrumentation plan in `data/README.md` separates pre-failure features from post-failure labels.
