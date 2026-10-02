"""Run the ns-3 smoke program from a JSON config or a generated metadata CSV."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess

import pandas as pd


def parse_metadata_rows(csv_path: Path):
    frame = pd.read_csv(csv_path)
    if frame.empty:
        raise ValueError(f"Metadata CSV is empty: {csv_path}")
    return frame


def human_rate_to_ns3(value):
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("kbps"):
            return str(float(text[:-4]) * 1000) + "bps"
        if text.endswith("bps"):
            return text
        if text.endswith("mbps"):
            return str(float(text[:-4]) * 1_000_000) + "bps"
    return str(int(float(value))) + "bps"


parser = argparse.ArgumentParser()
parser.add_argument("--ns3-dir", type=Path, required=True)
parser.add_argument("--config", type=Path, help="JSON config for the smoke DSR experiment")
parser.add_argument("--metadata-csv", type=Path, help="Generated Simulation_data.csv for DSR experiment metadata")
parser.add_argument("--row-index", type=int, default=0, help="Row index to use when running a metadata CSV row")
parser.add_argument("--scenario-id", type=str, help="Scenario ID to select from the metadata CSV")
parser.add_argument("--program", type=str, default="dsr_manet_smoke", choices=["dsr_manet_smoke", "dsr_manet_dataset"])
parser.add_argument("--sampling-interval-s", type=float, help="Mobility trace sample interval in seconds")
args = parser.parse_args()

if args.metadata_csv is not None:
    metadata = parse_metadata_rows(args.metadata_csv)
    row = metadata.loc[metadata["scenario_id"] == args.scenario_id].iloc[0] if args.scenario_id else metadata.iloc[args.row_index]
    config = {
        "scenario_id": str(row["scenario_id"]),
        "node_count": int(row["node_count"]),
        "simulation_time": float(row["simulation_duration_s"]),
        "area_size": float(row["area_x_m"]),
        "area_size_y": float(row["area_y_m"]),
        "node_speed": float(row["speed_mps"]),
        "traffic_rate": human_rate_to_ns3(row["traffic_rate_bps"]),
        "packet_size": int(row["packet_size_bytes"]),
        "source": int(row["source_id"]),
        "destination": int(row["destination_id"]),
        "random_seed": int(row["random_seed"]),
        "random_run": int(row["random_run"]),
        "run_id": int(row["run_id"]),
        "mobility_model": str(row["mobility_model"]),
        "routing_protocol": str(row["routing_protocol"]),
        "wifi_standard": str(row["wifi_standard"]),
        "channel_helper": str(row["channel_helper"]),
        "tx_power_dbm": float(row["tx_power_dbm"]),
        "noise_floor_dbm": float(row["noise_floor_dbm"]),
        "transport_protocol": str(row["transport_protocol"]),
        "application_type": str(row["application_type"]),
        "flow_id": int(row["flow_id"]),
        "enable_animation": False,
        "sampling_interval_s": args.sampling_interval_s if args.sampling_interval_s is not None else 1.0,
        "mobility_pause_s": float(row.get("mobility_pause_s", 2.0)),
        "udp_port": 9000,
        "output_dir": str(args.ns3_dir / "results" / "scenarios" / str(row["scenario_id"])),
    }
else:
    if args.config is None:
        raise SystemExit("Either --config or --metadata-csv must be supplied.")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.sampling_interval_s is not None:
        config["sampling_interval_s"] = args.sampling_interval_s

output_dir = Path(config.get("output_dir", "results"))
if not output_dir.is_absolute():
    output_dir = args.ns3_dir / output_dir
output_dir.mkdir(parents=True, exist_ok=True)
values = {
    "nodeCount": config["node_count"],
    "simulationTime": config["simulation_time"],
    "areaSize": config["area_size"],
    "nodeSpeed": config["node_speed"],
    "trafficRate": config["traffic_rate"],
    "packetSize": config["packet_size"],
    "source": config["source"],
    "destination": config["destination"],
    "randomSeed": config["random_seed"],
    "randomRun": config.get("random_run", 1),
    "port": config.get("udp_port", 9000),
    "outputDir": str(output_dir),
}
if args.program == "dsr_manet_dataset":
    values.update({
        "areaSizeY": config.get("area_size_y", config["area_size"]),
        "samplingInterval": config.get("sampling_interval_s", 1.0),
        "mobilityPause": config.get("mobility_pause_s", 2.0),
        "mobilityModel": config.get("mobility_model", "RandomWalk2dMobilityModel"),
        "routingProtocol": config.get("routing_protocol", "DSR"),
        "enableAnimation": config.get("enable_animation", True),
        "runId": config.get("run_id", config.get("random_run", 1)),
        "scenarioId": config.get("scenario_id", "unidentified"),
        "wifiStandard": config.get("wifi_standard", "802.11b"),
        "channelHelper": config.get("channel_helper", "YansWifiChannel"),
        "txPowerDbm": config.get("tx_power_dbm", 16.04),
        "noiseFloorDbm": config.get("noise_floor_dbm", -95.02),
        "transportProtocol": config.get("transport_protocol", "UDP"),
        "applicationType": config.get("application_type", "CBR"),
        "flowId": config.get("flow_id", 0),
    })
run_args = [f"--{key}={value}" for key, value in values.items()]
subprocess.run(["./ns3", "run", args.program, "--", *run_args], cwd=args.ns3_dir, check=True)
