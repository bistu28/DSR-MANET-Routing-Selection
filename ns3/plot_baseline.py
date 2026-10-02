#!/usr/bin/env python3
"""Plot one saved DSR run and write its evidence-based report."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--run", type=int, default=1)
    args = parser.parse_args()

    results_dir = args.results_dir.resolve()
    csv_dir = results_dir / "csv"
    plot_dir = results_dir / "plots"
    report_dir = results_dir / "reports"
    plot_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    suffix = f"seed_{args.seed}_run_{args.run}"
    metrics_path = csv_dir / f"dsr_metrics_{suffix}.csv"
    mobility_path = csv_dir / f"dsr_mobility_{suffix}.csv"
    route_path = csv_dir / f"dsr_route_events_{suffix}.csv"
    flowmon_path = metrics_path.with_suffix(metrics_path.suffix + ".flowmon.xml")
    animation_path = results_dir / "animation" / f"dsr_manet_{suffix}.xml"
    log_path = results_dir / "logs" / f"simulation_{suffix}.log"

    metrics = pd.read_csv(metrics_path)
    selected = metrics[(metrics["random_seed"] == args.seed) & (metrics["random_run"] == args.run)]
    if selected.empty:
        raise SystemExit(f"No metrics row found for seed={args.seed}, run={args.run}: {metrics_path}")
    row = selected.iloc[0]

    plt.style.use("seaborn-v0_8-whitegrid")
    figure, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
    figure.suptitle(f"Baseline DSR delivery | {int(row['node_count'])} nodes | seed {args.seed}, run {args.run}")

    packet_values = [int(row["tx_packets"]), int(row["rx_packets"]), int(row["packet_loss"])]
    packet_labels = ["Transmitted", "Received", "Not received"]
    packet_colors = ["#356f8a", "#3a8b70", "#c16a52"]
    bars = axes[0, 0].bar(packet_labels, packet_values, color=packet_colors, width=0.62)
    axes[0, 0].set_title("Application packets")
    axes[0, 0].set_ylabel("Packets")
    axes[0, 0].bar_label(bars, padding=3)

    pdr = float(row["pdr"]) * 100.0
    axes[0, 1].bar(["PDR"], [pdr], color="#3a8b70", width=0.45)
    axes[0, 1].set_ylim(0, 100)
    axes[0, 1].set_title("Packet delivery ratio")
    axes[0, 1].set_ylabel("Percent")
    axes[0, 1].text(0, min(pdr + 3, 96), f"{pdr:.2f}%", ha="center", fontweight="bold")

    throughput_kbps = float(row["throughput_bps"]) / 1000.0
    axes[1, 0].bar(["Received goodput"], [throughput_kbps], color="#356f8a", width=0.45)
    axes[1, 0].set_title("Application goodput")
    axes[1, 0].set_ylabel("kbps")
    axes[1, 0].text(0, throughput_kbps, f"{throughput_kbps:.3f} kbps", ha="center", va="bottom")

    axes[1, 1].axis("off")
    axes[1, 1].set_title("Delay")
    axes[1, 1].text(
        0.5,
        0.5,
        "Not measured\nDSR packets were not classified by FlowMonitor.\nNo timestamped payload delay trace was enabled.",
        ha="center",
        va="center",
        transform=axes[1, 1].transAxes,
        bbox={"boxstyle": "round,pad=0.6", "facecolor": "#f1f3f2", "edgecolor": "#9aa8a5"},
    )

    delivery_plot = plot_dir / f"dsr_delivery_{suffix}.png"
    figure.savefig(delivery_plot, dpi=180)
    plt.close(figure)

    mobility = pd.read_csv(mobility_path)
    first_time = float(mobility["time"].min())
    last_time = float(mobility["time"].max())
    initial = mobility[mobility["time"] == first_time].sort_values("node_id")
    final = mobility[mobility["time"] == last_time].sort_values("node_id")
    source_id = int(row["source"].split(".")[-1]) - 1
    destination_id = int(row["destination"].split(".")[-1]) - 1
    tracked_ids = set(range(0, int(row["node_count"]), 10)) | {source_id, destination_id}

    figure, axis = plt.subplots(figsize=(8, 7), constrained_layout=True)
    for node_id in sorted(tracked_ids):
        track = mobility[mobility["node_id"] == node_id].sort_values("time")
        axis.plot(track["x_m"], track["y_m"], color="#8c9997", alpha=0.35, linewidth=0.8)
    axis.scatter(initial["x_m"], initial["y_m"], s=16, facecolors="none", edgecolors="#83908d", label=f"t={first_time:g}s")
    axis.scatter(final["x_m"], final["y_m"], s=16, color="#397f78", alpha=0.68, label=f"t={last_time:g}s")
    source_final = final[final["node_id"] == source_id]
    destination_final = final[final["node_id"] == destination_id]
    axis.scatter(source_final["x_m"], source_final["y_m"], marker="*", s=150, color="#d08b3e", label=f"Source {source_id}")
    axis.scatter(destination_final["x_m"], destination_final["y_m"], marker="X", s=90, color="#a64b4b", label=f"Destination {destination_id}")
    axis.set_xlim(0, float(row["area_size"]))
    axis.set_ylim(0, float(row["area_size"]))
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("x (m)")
    axis.set_ylabel("y (m)")
    axis.set_title(f"RandomWalk2d node positions | {len(tracked_ids)} selected trajectories")
    axis.legend(loc="upper left", frameon=True, ncol=2)
    mobility_plot = plot_dir / f"dsr_mobility_{suffix}.png"
    figure.savefig(mobility_plot, dpi=180)
    plt.close(figure)

    config = {}
    if log_path.exists():
        config = dict(line.split("=", 1) for line in log_path.read_text().splitlines() if "=" in line)
    flow_count = 0
    if flowmon_path.exists():
        import xml.etree.ElementTree as ET

        root = ET.parse(flowmon_path).getroot()
        flow_stats = root.find("FlowStats")
        flow_count = len(flow_stats) if flow_stats is not None else 0
    animation_packet_markers = animation_path.read_text(errors="replace").count("<packet")
    route_events = pd.read_csv(route_path)
    route_status = ", ".join(route_events["event_type"].astype(str).unique()) if not route_events.empty else "none"
    delay = "Not measured" if pd.isna(row["delay_ms"]) else f"{float(row['delay_ms']):.3f} ms"

    report_path = report_dir / f"dsr_baseline_report_{suffix}.md"
    report_path.write_text(
        f"""# Baseline DSR Run Report

## Configuration

- Simulator: ns-3.48, local macOS build
- Nodes: {int(row['node_count'])}
- Duration: {float(row['timestamp_s']):g} s
- Area: {float(row['area_size']):g} m x {float(row['area_size']):g} m
- Mobility: {row['mobility_model']}, maximum speed {float(row['node_speed']):g} m/s
- Wi-Fi: 802.11b ad hoc, range propagation model with 250 m maximum range
- Traffic: UDP, {row['traffic_rate']}, {int(row['packet_size'])}-byte payloads
- Endpoints: node {int(config.get('source', 0))} to node {int(config.get('destination', 0))}
- Random seed/run: {args.seed}/{args.run}

## Measured Results

- Application packets transmitted: {int(row['tx_packets'])}
- Application packets received: {int(row['rx_packets'])}
- Packets not received by the sink: {int(row['packet_loss'])}
- Packet delivery ratio: {float(row['pdr']) * 100:.2f}%
- Application payload bytes transmitted: {int(row['tx_bytes'])}
- Application payload bytes received: {int(row['rx_bytes'])}
- Received goodput: {float(row['throughput_bps']):.2f} bit/s
- End-to-end delay: {delay}
- Measurement layer: {row['measurement_layer']}

The send interval is 98 s (application starts at 1 s and stops at 99 s). Goodput is received payload bits divided by that interval. Packet loss and PDR compare the application Tx and PacketSink Rx traces for this run.

## Interpretation and Limits

- The local NS-3.48 DSR code required an idempotence guard in `DsrRouting::Start()` because aggregate notifications scheduled queue initialization more than once. Without it, the simulator aborted at time 0 while inserting duplicate priority queues.
- FlowMonitor produced {flow_count} classifiable IPv4 flow entries. DSR encapsulates the UDP payload under its own IP protocol, so this run uses the explicitly labeled application-trace fallback for delivery, loss, PDR, and goodput.
- Delay is unavailable: no timestamped payload header was enabled, and the DSR packets were not classified by FlowMonitor. No delay value is inferred.
- DSR route paths are unavailable through the public route-trace interface used here. The route CSV status is `{route_status}`; no path was synthesized.
- The NetAnim XML contains {animation_packet_markers} packet markers. It is a node-mobility visualization, not a route or packet-forwarding visualization.
- No Random Forest, XGBoost, route scoring, or ML route selection was used.

## Artifacts

- Metrics: `../csv/dsr_metrics_{suffix}.csv`
- Mobility samples: `../csv/dsr_mobility_{suffix}.csv`
- Route availability: `../csv/dsr_route_events_{suffix}.csv`
- FlowMonitor XML: `../csv/dsr_metrics_{suffix}.csv.flowmon.xml`
- NetAnim mobility XML: `../animation/dsr_manet_{suffix}.xml`
- Delivery plot: `../plots/{delivery_plot.name}`
- Mobility plot: `../plots/{mobility_plot.name}`
""",
        encoding="utf-8",
    )
    print(f"Wrote {delivery_plot}")
    print(f"Wrote {mobility_plot}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()