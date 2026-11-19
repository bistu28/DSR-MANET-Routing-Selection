"""Create a minimal, deterministic source bundle for bootstrapping Colab."""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

from .environment import verify_instrumentation_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = Path(__file__).with_name("stage2_setup_sources.zip")
BUNDLE_FILES = (
    "colab/__init__.py",
    "colab/environment.py",
    "requirements.txt",
    "ns3/dsr_instrumentation/README.md",
    "ns3/dsr_instrumentation/apply.sh",
    "ns3/dsr_instrumentation/manifest.json",
    "ns3/dsr_instrumentation/ns3-3.48-dsr.patch",
    "ns3/dsr_instrumentation/src/dsr/model/stage2-dsr-event-sink.h",
    "ns3/dsr_instrumentation/scratch/dsr_manet_dataset.cc",
)


def build_bundle(destination: Path = BUNDLE_PATH) -> str:
    verify_instrumentation_package(PROJECT_ROOT / "ns3/dsr_instrumentation")
    missing = [relative for relative in BUNDLE_FILES if not (PROJECT_ROOT / relative).is_file()]
    if missing:
        raise FileNotFoundError(f"Setup bundle source files are missing: {missing}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in BUNDLE_FILES:
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (PROJECT_ROOT / relative).read_bytes())

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"{destination}\nsha256:{digest}")
    return digest


if __name__ == "__main__":
    try:
        build_bundle()
    except (OSError, ValueError) as error:
        print(f"Could not create setup bundle: {error}", file=sys.stderr)
        raise
