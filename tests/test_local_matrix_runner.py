from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ns3.run_local_matrix import (
    RunnerError,
    pcap_record_count,
    process_tree_rss_bytes,
    read_matrix,
    scenario_arguments,
    validate_application_trace,
    validate_outage_evidence,
    validate_pcap_event_links,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalMatrixRunnerTests(unittest.TestCase):
    def test_reads_unique_180_scenario_matrix(self) -> None:
        rows = read_matrix(PROJECT_ROOT / "data/metadata/Simulation_data.csv")
        self.assertEqual(len(rows), 180)
        self.assertEqual(len({row["scenario_id"] for row in rows}), 180)

    def test_scenario_arguments_keep_observation_and_output_paths_explicit(self) -> None:
        row = read_matrix(PROJECT_ROOT / "data/metadata/Simulation_data.csv")[0]
        with tempfile.TemporaryDirectory() as temporary:
            attempt = Path(temporary) / row["scenario_id"] / "attempt-001"
            args = scenario_arguments(row, attempt, None)

        values = dict(argument[2:].split("=", 1) for argument in args)
        self.assertEqual(values["scenarioId"], row["scenario_id"])
        self.assertEqual(values["nodeCount"], row["node_count"])
        self.assertEqual(values["randomSeed"], row["random_seed"])
        self.assertEqual(
            values["dsrEventFile"],
            str(attempt / "events/dsr_events.jsonl"),
        )
        self.assertEqual(
            values["dsrPcapFile"],
            str(attempt / "evidence/dsr_control.pcap"),
        )
        self.assertNotIn("failureOutageStartS", values)

    def test_controlled_outage_requires_valid_interval(self) -> None:
        row = read_matrix(PROJECT_ROOT / "data/metadata/Simulation_data.csv")[0]
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RunnerError, "must end before"):
                scenario_arguments(row, Path(temporary), (590, 20, 0))

    def test_pcap_record_count_matches_binary_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "packets.pcap"
            global_header = b"\xd4\xc3\xb2\xa1" + struct.pack(
                "<HHIIII", 2, 4, 0, 0, 65535, 101
            )
            record = struct.pack("<IIII", 1, 2, 3, 3) + b"abc"
            path.write_bytes(global_header + record)
            self.assertEqual(pcap_record_count(path), 1)

    def test_pcap_rejects_truncated_packet_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "packets.pcap"
            global_header = b"\xd4\xc3\xb2\xa1" + struct.pack(
                "<HHIIII", 2, 4, 0, 0, 65535, 101
            )
            record_header = struct.pack("<IIII", 1, 2, 5, 5)
            path.write_bytes(global_header + record_header + b"abc")
            with self.assertRaisesRegex(RunnerError, "Truncated PCAP packet data"):
                pcap_record_count(path)

    def test_application_trace_links_delivery_to_transmit_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "application_packets.csv"
            path.write_text(
                "packet_id,direction,simulation_time_ns,node_id,packet_bytes,delay_ns\n"
                "ns3uid:7,tx,100,1,100,\n"
                "ns3uid:7,rx,150,2,100,50\n",
                encoding="utf-8",
            )
            result = validate_application_trace(path, expected_tx=1, expected_rx=1)

        self.assertEqual(result["delay_sample_count"], 1)
        self.assertAlmostEqual(result["mean_delay_ms"], 0.00005)

    def test_application_trace_rejects_unmatched_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "application_packets.csv"
            path.write_text(
                "packet_id,direction,simulation_time_ns,node_id,packet_bytes,delay_ns\n"
                "ns3uid:8,tx,100,1,100,\n"
                "ns3uid:9,rx,150,2,100,50\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RunnerError, "no transmit record"):
                validate_application_trace(path, expected_tx=1, expected_rx=1)

    def test_pcap_event_link_uses_record_index_timestamp_and_direction(self) -> None:
        events = [
            {
                "event_type": "packet_tx",
                "pcap_record_index": 0,
                "packet_id": "ns3uid:12",
                "simulation_time_ns": 200,
                "node_id": 1,
            }
        ]
        index = [
            {
                "pcap_record_index": 0,
                "packet_id": "ns3uid:12",
                "timestamp_ns": 200,
                "node_id": 1,
                "direction": "tx",
            }
        ]
        self.assertEqual(validate_pcap_event_links(events, index), 1)
        index[0]["direction"] = "rx"
        with self.assertRaisesRegex(RunnerError, "linkage is invalid"):
            validate_pcap_event_links(events, index)

    def test_controlled_outage_requires_applied_events_and_recovery_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "range_interventions.jsonl"
            records = [
                {
                    "status": "scheduled",
                    "start_s": 300,
                    "duration_s": 10,
                    "outage_range_m": 0,
                    "restored_range_m": 250,
                },
                {"simulation_time_ns": 300_000_000_000, "max_range_m": 0},
                {"simulation_time_ns": 310_000_000_000, "max_range_m": 250},
            ]
            path.write_text(
                "\n".join(json.dumps(record) for record in records) + "\n",
                encoding="utf-8",
            )
            events = [
                {"event_type": "broken_link_declared"},
                {"event_type": "recovery_attempt"},
                {"event_type": "recovery_succeeded"},
            ]
            self.assertEqual(
                validate_outage_evidence(path, events, (300, 10, 0)),
                {"recovery_outcome": ["recovery_succeeded"]},
            )
            with self.assertRaisesRegex(RunnerError, "direct DSR"):
                validate_outage_evidence(path, [], (300, 10, 0))

    def test_process_memory_sampler_reports_current_process_tree(self) -> None:
        self.assertGreater(process_tree_rss_bytes(os.getpid()), 0)

    def test_runner_requires_bounded_selection_by_default(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "ns3/run_local_matrix.py"), "--dry-run"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Select --scenario-id or --limit", result.stderr)

    def test_runner_refuses_repository_output_roots(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "ns3/run_local_matrix.py"),
                "--scenario-id",
                "DSR_N100_MLOW_TLOW_S10001_R001",
                "--output-root",
                str(PROJECT_ROOT / "local-output"),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be outside the repository", result.stderr)


if __name__ == "__main__":
    unittest.main()
