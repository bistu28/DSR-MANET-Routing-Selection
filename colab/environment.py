"""Reproducible, hash-checked NS-3.48 Colab environment management."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence


NS3_TAG = "ns-3.48"
NS3_COMMIT = "d2add90b452d600cfb4859baed8e9ea633519447"
NS3_REPOSITORY = "https://gitlab.com/nsnam/ns-3-dev.git"
DEFAULT_NS3_DIR = Path("/content/ns-3.48")
CONFIGURE_ARGS = (
    "--enable-examples",
    "--enable-tests",
    "--",
    "-DNS3_WARNINGS_AS_ERRORS=OFF",
)
APT_PACKAGES = (
    "gcc",
    "g++",
    "cmake",
    "ninja-build",
    "git",
    "python3",
    "python3-dev",
    "python3-pip",
    "pkg-config",
    "libsqlite3-dev",
    "sqlite3",
    "libxml2-dev",
    "libgtk-3-dev",
    "libgsl-dev",
    "ccache",
)
REQUIRED_COMMANDS = ("gcc", "g++", "cmake", "ninja", "git", "python3", "pkg-config")
PKG_CONFIG_MODULES = ("sqlite3", "libxml-2.0", "gsl")
BUILD_FINGERPRINT_FILE = ".stage2_build_fingerprint"
ENVIRONMENT_MANIFEST_NAME = "COLAB_ENVIRONMENT_MANIFEST.json"


class EnvironmentSetupError(RuntimeError):
    """Raised when an environment prerequisite or verification fails."""


@dataclass(frozen=True)
class RuntimeFacts:
    system: str
    release: str
    machine: str
    python: str
    compiler: str | None
    cmake: str | None
    ninja: str | None
    git: str | None
    cpu_count: int
    memory_total_bytes: int | None
    disk_total_bytes: int
    disk_free_bytes: int
    is_colab: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    arguments: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        rendered = " ".join(arguments)
        details = result.stderr.strip() or result.stdout.strip()
        raise EnvironmentSetupError(
            f"Command failed with exit code {result.returncode}: {rendered}\n{details}"
        )
    return result


def _version(command: str, *arguments: str) -> str | None:
    if shutil.which(command) is None:
        return None
    result = _run((command, *arguments), check=False)
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).splitlines()[0].strip()


def _memory_total_bytes() -> int | None:
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None


def _is_colab_runtime() -> bool:
    if os.environ.get("COLAB_RELEASE_TAG"):
        return True
    try:
        return importlib.util.find_spec("google.colab") is not None
    except ModuleNotFoundError:
        return False


def collect_runtime_facts(root: Path) -> RuntimeFacts:
    usage = shutil.disk_usage(root)
    return RuntimeFacts(
        system=platform.system(),
        release=platform.release(),
        machine=platform.machine(),
        python=platform.python_version(),
        compiler=_version("g++", "--version"),
        cmake=_version("cmake", "--version"),
        ninja=_version("ninja", "--version"),
        git=_version("git", "--version"),
        cpu_count=os.cpu_count() or 1,
        memory_total_bytes=_memory_total_bytes(),
        disk_total_bytes=usage.total,
        disk_free_bytes=usage.free,
        is_colab=_is_colab_runtime(),
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EnvironmentSetupError(f"Expected a JSON object in {path}")
    return value


def verify_instrumentation_package(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("source_tag") != NS3_TAG or manifest.get("source_commit") != NS3_COMMIT:
        raise EnvironmentSetupError(
            f"Instrumentation manifest is not pinned to {NS3_TAG} at {NS3_COMMIT}"
        )

    patch_entry = manifest.get("patch_file")
    if not isinstance(patch_entry, dict):
        raise EnvironmentSetupError(f"Missing patch_file entry in {manifest_path}")
    package_files = [
        (package_dir / str(patch_entry.get("path", "")), str(patch_entry.get("sha256", ""))),
        (
            package_dir / "src/dsr/model/stage2-dsr-event-sink.h",
            _source_hash(manifest, "src/dsr/model/stage2-dsr-event-sink.h"),
        ),
        (
            package_dir / "scratch/dsr_manet_dataset.cc",
            _source_hash(manifest, "scratch/dsr_manet_dataset.cc"),
        ),
    ]
    for path, expected_hash in package_files:
        if not path.is_file():
            raise EnvironmentSetupError(f"Instrumentation payload is missing: {path}")
        if not expected_hash or sha256_file(path) != expected_hash:
            raise EnvironmentSetupError(f"Instrumentation payload hash mismatch: {path}")
    return manifest


def _source_hash(manifest: dict[str, Any], relative_path: str) -> str:
    entries = manifest.get("patched_source_files")
    if not isinstance(entries, list):
        raise EnvironmentSetupError("Instrumentation manifest has no patched_source_files list")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("path") == relative_path:
            return str(entry.get("sha256", ""))
    raise EnvironmentSetupError(f"No source hash recorded for {relative_path}")


def verify_patched_checkout(ns3_dir: Path, manifest: dict[str, Any]) -> None:
    actual_commit = _run(("git", "rev-parse", "HEAD"), cwd=ns3_dir).stdout.strip()
    if actual_commit != NS3_COMMIT:
        raise EnvironmentSetupError(
            f"NS-3 source commit mismatch: expected {NS3_COMMIT}, got {actual_commit}"
        )
    entries = manifest.get("patched_source_files")
    if not isinstance(entries, list):
        raise EnvironmentSetupError("Instrumentation manifest has no patched_source_files list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise EnvironmentSetupError("Invalid patched source entry in instrumentation manifest")
        relative = Path(str(entry.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise EnvironmentSetupError(f"Unsafe source path in instrumentation manifest: {relative}")
        source = ns3_dir / relative
        expected = str(entry.get("sha256", ""))
        if not source.is_file() or not expected or sha256_file(source) != expected:
            raise EnvironmentSetupError(f"Patched NS-3 source does not match manifest: {source}")


def build_fingerprint(
    facts: RuntimeFacts,
    *,
    patch_sha256: str,
    ns3_dir: Path,
    configure_args: Sequence[str] = CONFIGURE_ARGS,
) -> str:
    payload = {
        "source_commit": NS3_COMMIT,
        "patch_sha256": patch_sha256,
        "system": facts.system,
        "release": facts.release,
        "machine": facts.machine,
        "python_major_minor": ".".join(facts.python.split(".")[:2]),
        "compiler": facts.compiler,
        "cmake": facts.cmake,
        "ninja": facts.ninja,
        "configure_args": list(configure_args),
        "source_path": str(ns3_dir.resolve()),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _check_system_dependencies(*, install_missing: bool) -> dict[str, str | None]:
    missing_commands = [name for name in REQUIRED_COMMANDS if shutil.which(name) is None]
    missing_modules = [
        name
        for name in PKG_CONFIG_MODULES
        if shutil.which("pkg-config") is None
        or _run(("pkg-config", "--exists", name), check=False).returncode != 0
    ]
    if (missing_commands or missing_modules) and install_missing:
        if platform.system() != "Linux" or shutil.which("apt-get") is None:
            raise EnvironmentSetupError(
                "Missing system dependencies and apt-get is unavailable: "
                f"commands={missing_commands}, pkg_config={missing_modules}"
            )
        prefix: tuple[str, ...] = ()
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            if shutil.which("sudo") is None:
                raise EnvironmentSetupError("Installing Colab system packages requires root or sudo")
            prefix = ("sudo",)
        _run((*prefix, "apt-get", "update", "-qq"), timeout=900)
        _run(
            (*prefix, "apt-get", "install", "-y", *APT_PACKAGES),
            timeout=1800,
        )
        return _check_system_dependencies(install_missing=False)
    if missing_commands or missing_modules:
        raise EnvironmentSetupError(
            "Required system dependencies are missing: "
            f"commands={missing_commands}, pkg_config={missing_modules}"
        )
    return {
        "gcc": _version("gcc", "--version"),
        "g++": _version("g++", "--version"),
        "cmake": _version("cmake", "--version"),
        "ninja": _version("ninja", "--version"),
        "git": _version("git", "--version"),
        "pkg-config": _version("pkg-config", "--version"),
    }


def _requirement_names(requirements_file: Path) -> list[str]:
    names: list[str] = []
    for line in requirements_file.read_text(encoding="utf-8").splitlines():
        requirement = line.partition("#")[0].strip()
        if not requirement or requirement.startswith(("-", "http:", "https:")):
            continue
        name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0]
        if name:
            names.append(re.sub(r"[-_.]+", "-", name).casefold())
    return names


def _missing_python_requirements(requirements_file: Path) -> list[str]:
    installed = {
        re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).casefold()
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    }
    return [name for name in _requirement_names(requirements_file) if name not in installed]


def _ensure_python_requirements(
    project_dir: Path,
    *,
    install_missing: bool,
) -> list[str]:
    requirements_file = project_dir / "requirements.txt"
    if not requirements_file.is_file():
        raise EnvironmentSetupError(f"Project requirements file is missing: {requirements_file}")
    missing = _missing_python_requirements(requirements_file)
    if missing and install_missing:
        _run(
            (sys.executable, "-m", "pip", "install", "-r", str(requirements_file)),
            timeout=1800,
        )
        missing = _missing_python_requirements(requirements_file)
    if missing:
        raise EnvironmentSetupError(f"Required Python distributions are missing: {missing}")
    return _requirement_names(requirements_file)


def ensure_ns3_source(ns3_dir: Path) -> None:
    if ns3_dir.exists():
        if not (ns3_dir / ".git").exists():
            raise EnvironmentSetupError(
                f"Refusing to overwrite an existing non-Git NS-3 path: {ns3_dir}"
            )
        commit = _run(("git", "rev-parse", "HEAD"), cwd=ns3_dir).stdout.strip()
        if commit != NS3_COMMIT:
            raise EnvironmentSetupError(
                f"Existing NS-3 checkout is {commit}, expected {NS3_COMMIT}; "
                "select a new NS3_DIR instead of overwriting it."
            )
    else:
        ns3_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(
            (
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                NS3_TAG,
                NS3_REPOSITORY,
                str(ns3_dir),
            ),
            timeout=1800,
        )
    commit = _run(("git", "rev-parse", "HEAD"), cwd=ns3_dir).stdout.strip()
    if commit != NS3_COMMIT:
        raise EnvironmentSetupError(
            f"Cloned NS-3 commit mismatch: expected {NS3_COMMIT}, got {commit}"
        )


def _apply_instrumentation(ns3_dir: Path, package_dir: Path) -> dict[str, Any]:
    manifest = verify_instrumentation_package(package_dir)
    _run(("bash", str(package_dir / "apply.sh"), str(ns3_dir)), timeout=300)
    verify_patched_checkout(ns3_dir, manifest)
    return manifest


def _read_build_fingerprint(ns3_dir: Path) -> str | None:
    marker = ns3_dir / "build" / BUILD_FINGERPRINT_FILE
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip()


def _validate_archive_members(members: Sequence[tarfile.TarInfo]) -> None:
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "build":
            raise EnvironmentSetupError(f"Unsafe build-cache archive path: {member.name}")
        if not (member.isdir() or member.isfile()):
            raise EnvironmentSetupError(f"Unsupported build-cache archive entry: {member.name}")


def _cache_paths(cache_dir: Path, fingerprint: str) -> tuple[Path, Path]:
    archive = cache_dir / f"ns3-3.48-build-{fingerprint}.tar.gz"
    return archive, archive.with_suffix(archive.suffix + ".json")


def restore_build_cache(
    ns3_dir: Path,
    cache_dir: Path | None,
    *,
    fingerprint: str,
    patch_sha256: str,
) -> bool:
    if cache_dir is None:
        return False
    archive, record = _cache_paths(cache_dir, fingerprint)
    if not archive.exists() and not record.exists():
        return False
    if not archive.is_file() or not record.is_file():
        raise EnvironmentSetupError(f"Incomplete build cache pair: {archive} and {record}")
    cache_manifest = _load_json(record)
    if (
        cache_manifest.get("build_fingerprint") != fingerprint
        or cache_manifest.get("source_commit") != NS3_COMMIT
        or cache_manifest.get("patch_sha256") != patch_sha256
        or cache_manifest.get("archive_sha256") != sha256_file(archive)
    ):
        raise EnvironmentSetupError(f"Build cache compatibility or hash check failed: {archive}")
    build_dir = ns3_dir / "build"
    if build_dir.exists():
        raise EnvironmentSetupError(
            f"Refusing to overlay an existing build directory: {build_dir}"
        )
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        _validate_archive_members(members)
        with tempfile.TemporaryDirectory(prefix="stage2-build-restore-", dir=ns3_dir) as temp:
            temp_root = Path(temp)
            tar.extractall(temp_root, members=members)
            extracted = temp_root / "build"
            marker = extracted / BUILD_FINGERPRINT_FILE
            if not marker.is_file() or marker.read_text(encoding="utf-8").strip() != fingerprint:
                raise EnvironmentSetupError("Restored build cache lacks the expected fingerprint marker")
            shutil.move(str(extracted), str(build_dir))
    return True


def save_build_cache(
    ns3_dir: Path,
    cache_dir: Path,
    *,
    fingerprint: str,
    patch_sha256: str,
    facts: RuntimeFacts,
) -> Path:
    build_dir = ns3_dir / "build"
    marker = build_dir / BUILD_FINGERPRINT_FILE
    if not build_dir.is_dir() or not marker.is_file():
        raise EnvironmentSetupError(f"No verified build directory to cache: {build_dir}")
    if marker.read_text(encoding="utf-8").strip() != fingerprint:
        raise EnvironmentSetupError("Build fingerprint changed; refusing to cache incompatible build")
    for current, dirs, files in os.walk(build_dir, followlinks=False):
        for name in (*dirs, *files):
            if (Path(current) / name).is_symlink():
                raise EnvironmentSetupError("Build cache contains symlinks; refusing to archive")

    cache_dir.mkdir(parents=True, exist_ok=True)
    archive, record = _cache_paths(cache_dir, fingerprint)
    if archive.exists() or record.exists():
        if not archive.is_file() or not record.is_file():
            raise EnvironmentSetupError(f"Refusing to overwrite incomplete cache pair: {archive}")
        existing = _load_json(record)
        if (
            existing.get("build_fingerprint") == fingerprint
            and existing.get("archive_sha256") == sha256_file(archive)
        ):
            return archive
        raise EnvironmentSetupError(f"Refusing to overwrite an existing cache: {archive}")

    with tempfile.TemporaryDirectory(prefix="stage2-build-cache-") as temp:
        local_archive = Path(temp) / archive.name
        with tarfile.open(local_archive, "w:gz") as tar:
            tar.add(build_dir, arcname="build", recursive=True)
        archive_hash = sha256_file(local_archive)
        staged_archive = cache_dir / f".{archive.name}.tmp"
        shutil.copyfile(local_archive, staged_archive)
        os.replace(staged_archive, archive)
    cache_manifest = {
        "schema_version": 1,
        "source_commit": NS3_COMMIT,
        "patch_sha256": patch_sha256,
        "build_fingerprint": fingerprint,
        "archive_sha256": archive_hash,
        "runtime": asdict(facts),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    staged_record = record.with_name(f".{record.name}.tmp")
    staged_record.write_text(json.dumps(cache_manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(staged_record, record)
    return archive


def _verify_build(ns3_dir: Path, fingerprint: str) -> None:
    actual = _read_build_fingerprint(ns3_dir)
    if actual != fingerprint:
        raise EnvironmentSetupError(
            f"Build fingerprint mismatch: expected {fingerprint}, got {actual or 'missing'}"
        )
    _run(("./ns3", "run", "dsr --PrintHelp"), cwd=ns3_dir, timeout=300)
    _run(
        ("./ns3", "run", "scratch/dsr_manet_dataset --PrintHelp"),
        cwd=ns3_dir,
        timeout=300,
    )


def _build_ns3(ns3_dir: Path, *, build_jobs: int, fingerprint: str) -> None:
    build_dir = ns3_dir / "build"
    if build_dir.exists() and _read_build_fingerprint(ns3_dir) != fingerprint:
        raise EnvironmentSetupError(
            f"Refusing to rebuild over an unknown or incompatible build: {build_dir}"
        )
    env = os.environ.copy()
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(build_jobs)
    _run(("./ns3", "configure", *CONFIGURE_ARGS), cwd=ns3_dir, env=env, timeout=1800)
    _run(("./ns3", "build"), cwd=ns3_dir, env=env, timeout=7200)
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / BUILD_FINGERPRINT_FILE).write_text(fingerprint + "\n", encoding="utf-8")
    _verify_build(ns3_dir, fingerprint)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def setup_environment(
    *,
    mode: str,
    project_dir: Path,
    ns3_dir: Path = DEFAULT_NS3_DIR,
    build_cache_dir: Path | None = None,
    build_jobs: int | None = None,
    save_cache: bool = False,
) -> dict[str, Any]:
    normalized_mode = mode.upper()
    if normalized_mode not in {"AUTO", "RESTORE", "BUILD", "VERIFY"}:
        raise ValueError(f"Unsupported environment mode: {mode}")
    if normalized_mode == "VERIFY" and save_cache:
        raise ValueError("VERIFY mode cannot save a build cache")
    if save_cache and build_cache_dir is None:
        raise ValueError("save_cache requires build_cache_dir")
    if not project_dir.is_dir():
        raise FileNotFoundError(f"Project directory is unavailable: {project_dir}")
    package_dir = project_dir / "ns3/dsr_instrumentation"
    manifest_path = project_dir / ENVIRONMENT_MANIFEST_NAME
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        instrumentation = verify_instrumentation_package(package_dir)
        install_missing = normalized_mode != "VERIFY"
        dependencies = _check_system_dependencies(install_missing=install_missing)
        python_requirements = _ensure_python_requirements(
            project_dir,
            install_missing=install_missing,
        )
        if normalized_mode == "VERIFY":
            if not ns3_dir.is_dir():
                raise FileNotFoundError(f"NS-3 source directory is unavailable: {ns3_dir}")
        else:
            ensure_ns3_source(ns3_dir)
            instrumentation = _apply_instrumentation(ns3_dir, package_dir)
        verify_patched_checkout(ns3_dir, instrumentation)
        patch_sha256 = str(instrumentation["patch_file"]["sha256"])
        facts = collect_runtime_facts(ns3_dir)
        jobs = build_jobs if build_jobs is not None else min(facts.cpu_count, 2)
        if jobs < 1:
            raise ValueError("build_jobs must be positive")
        fingerprint = build_fingerprint(
            facts,
            patch_sha256=patch_sha256,
            ns3_dir=ns3_dir,
        )

        build_status: str
        current_fingerprint = _read_build_fingerprint(ns3_dir)
        if current_fingerprint == fingerprint:
            if normalized_mode == "BUILD":
                _build_ns3(ns3_dir, build_jobs=jobs, fingerprint=fingerprint)
                build_status = "BUILT"
            else:
                _verify_build(ns3_dir, fingerprint)
                build_status = "VERIFIED_EXISTING"
        else:
            if normalized_mode == "VERIFY":
                raise EnvironmentSetupError("No compatible, fingerprinted NS-3 build is available")
            if (ns3_dir / "build").exists():
                raise EnvironmentSetupError(
                    "An unverified or incompatible build directory exists; "
                    "select a new NS3_DIR rather than replacing it."
                )
            restored = False
            if normalized_mode in {"AUTO", "RESTORE"}:
                restored = restore_build_cache(
                    ns3_dir,
                    build_cache_dir,
                    fingerprint=fingerprint,
                    patch_sha256=patch_sha256,
                )
                if restored:
                    _verify_build(ns3_dir, fingerprint)
                    build_status = "RESTORED_AND_VERIFIED"
                elif normalized_mode == "RESTORE":
                    raise FileNotFoundError(
                        f"No compatible build cache found under {build_cache_dir}"
                    )
                else:
                    _build_ns3(ns3_dir, build_jobs=jobs, fingerprint=fingerprint)
                    build_status = "BUILT"
            else:
                _build_ns3(ns3_dir, build_jobs=jobs, fingerprint=fingerprint)
                build_status = "BUILT"

        if save_cache and build_status in {"BUILT", "VERIFIED_EXISTING"}:
            assert build_cache_dir is not None
            save_build_cache(
                ns3_dir,
                build_cache_dir,
                fingerprint=fingerprint,
                patch_sha256=patch_sha256,
                facts=facts,
            )

        report: dict[str, Any] = {
            "schema_version": 1,
            "status": (
                "BUILD_READY_NOT_REGRESSION_TESTED"
                if facts.is_colab
                else "LOCAL_BUILD_READY_NOT_COLAB_VERIFIED"
            ),
            "operation_mode": normalized_mode,
            "started_at_utc": started_at,
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime": asdict(facts),
            "dependencies": dependencies,
            "python_requirements": python_requirements,
            "ns3": {
                "tag": NS3_TAG,
                "commit": NS3_COMMIT,
                "source_dir": str(ns3_dir),
                "instrumentation_patch_sha256": patch_sha256,
                "instrumentation_status": instrumentation.get("status"),
                "build_fingerprint": fingerprint,
                "build_status": build_status,
                "configure_args": list(CONFIGURE_ARGS),
                "build_jobs": jobs,
            },
            "project_assets": {
                "simulation_config_present": (project_dir / "configs/simulation.json").is_file(),
                "scenario_matrix_present": (project_dir / "data/metadata/Simulation_data.csv").is_file(),
                "stage1_mobility_aggregate_present": (
                    project_dir / "data/mobility/Mobility_data_180_validated.csv.gz"
                ).is_file(),
                "stage1_topology_aggregate_present": (
                    project_dir / "data/topology/Topology_data_180_validated.csv.gz"
                ).is_file(),
                "checkpoint_dir": os.environ.get("STAGE2_CHECKPOINT_DIR"),
            },
        }
        _atomic_write_json(manifest_path, report)
        return report
    except (EnvironmentSetupError, FileNotFoundError, OSError, subprocess.SubprocessError) as error:
        failure_report = {
            "schema_version": 1,
            "status": "FAILED",
            "operation_mode": normalized_mode,
            "started_at_utc": started_at,
            "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            "error_type": type(error).__name__,
            "error": str(error),
            "ns3_source_dir": str(ns3_dir),
        }
        _atomic_write_json(manifest_path, failure_report)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("AUTO", "RESTORE", "BUILD", "VERIFY"), default="AUTO")
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--ns3-dir", type=Path, default=DEFAULT_NS3_DIR)
    parser.add_argument("--build-cache-dir", type=Path)
    parser.add_argument("--build-jobs", type=int)
    parser.add_argument("--save-cache", action="store_true")
    args = parser.parse_args()
    report = setup_environment(
        mode=args.mode,
        project_dir=args.project_dir,
        ns3_dir=args.ns3_dir,
        build_cache_dir=args.build_cache_dir,
        build_jobs=args.build_jobs,
        save_cache=args.save_cache,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
