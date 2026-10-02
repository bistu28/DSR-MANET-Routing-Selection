# Baseline DSR Run Report

## Configuration

- Simulator: ns-3.48, local macOS build
- Nodes: 150
- Duration: 100 s
- Area: 500 m x 500 m
- Mobility: RandomWalk2dMobilityModel, maximum speed 5 m/s
- Wi-Fi: 802.11b ad hoc, range propagation model with 250 m maximum range
- Traffic: UDP, 2kbps, 512-byte payloads
- Endpoints: node 0 to node 149
- Random seed/run: 1/1

## Measured Results

- Application packets transmitted: 47
- Application packets received: 45
- Packets not received by the sink: 2
- Packet delivery ratio: 95.74%
- Application payload bytes transmitted: 24064
- Application payload bytes received: 23040
- Received goodput: 1880.82 bit/s
- End-to-end delay: Not measured
- Measurement layer: application_trace

The send interval is 98 s (application starts at 1 s and stops at 99 s). Goodput is received payload bits divided by that interval. Packet loss and PDR compare the application Tx and PacketSink Rx traces for this run.

## Interpretation and Limits

- The local NS-3.48 DSR code required an idempotence guard in `DsrRouting::Start()` because aggregate notifications scheduled queue initialization more than once. Without it, the simulator aborted at time 0 while inserting duplicate priority queues.
- FlowMonitor produced 0 classifiable IPv4 flow entries. DSR encapsulates the UDP payload under its own IP protocol, so this run uses the explicitly labeled application-trace fallback for delivery, loss, PDR, and goodput.
- Delay is unavailable: no timestamped payload header was enabled, and the DSR packets were not classified by FlowMonitor. No delay value is inferred.
- DSR route paths are unavailable through the public route-trace interface used here. The route CSV status is `not_available`; no path was synthesized.
- The NetAnim XML contains 0 packet markers. It is a node-mobility visualization, not a route or packet-forwarding visualization.
- No Random Forest, XGBoost, route scoring, or ML route selection was used.

## Artifacts

- Metrics: `../csv/dsr_metrics_seed_1_run_1.csv`
- Mobility samples: `../csv/dsr_mobility_seed_1_run_1.csv`
- Route availability: `../csv/dsr_route_events_seed_1_run_1.csv`
- FlowMonitor XML: `../csv/dsr_metrics_seed_1_run_1.csv.flowmon.xml`
- NetAnim mobility XML: `../animation/dsr_manet_seed_1_run_1.xml`
- Delivery plot: `../plots/dsr_delivery_seed_1_run_1.png`
- Mobility plot: `../plots/dsr_mobility_seed_1_run_1.png`
