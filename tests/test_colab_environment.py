from __future__ import annotations

import json
import sys
import tarfile
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from colab.build_setup_bundle import BUNDLE_FILES, build_bundle
from colab.environment import (
    BUILD_FINGERPRINT_FILE,
    EnvironmentSetupError,
    RuntimeFacts,
    _validate_archive_members,
    build_fingerprint,
    collect_runtime_facts,
    restore_build_cache,
    save_build_cache,
    setup_environment,
    verify_instrumentation_package,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PROJECT_ROOT / "ns3/dsr_instrumentation"


def runtime_facts() -> RuntimeFacts:
    return RuntimeFacts(
        system="Linux",
        release="test-release",
        machine="x86_64",
        python="3.13.1",
        compiler="g++ test",
        cmake="cmake test",
        ninja="ninja test",
        git="git test",
        cpu_count=2,
        memory_total_bytes=8 * 1024**3,
        disk_total_bytes=50 * 1024**3,
        disk_free_bytes=40 * 1024**3,
        is_colab=True,
    )


class InstrumentationPackageTests(unittest.TestCase):
    def test_package_payload_hashes_match_manifest(self) -> None:
        manifest = verify_instrumentation_package(PACKAGE_DIR)
        self.assertEqual(manifest["source_commit"], "d2add90b452d600cfb4859baed8e9ea633519447")

    def test_package_rejects_modified_patch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "instrumentation"
            import shutil

            shutil.copytree(PACKAGE_DIR, copied)
            patch_file = copied / "ns3-3.48-dsr.patch"
            patch_file.write_bytes(patch_file.read_bytes() + b"\n")
            with self.assertRaises(EnvironmentSetupError):
                verify_instrumentation_package(copied)

    def test_colab_detection_handles_missing_google_namespace(self) -> None:
        with patch.dict("os.environ", {"COLAB_RELEASE_TAG": ""}):
            facts = collect_runtime_facts(PROJECT_ROOT)
        self.assertFalse(facts.is_colab)

    def test_verify_mode_does_not_clone_or_apply_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            package = project / "ns3/dsr_instrumentation"
            package.parent.mkdir(parents=True)
            import shutil

            shutil.copytree(PACKAGE_DIR, package)
            (project / "requirements.txt").write_text("", encoding="utf-8")
            ns3_dir = root / "ns-3.48"
            ns3_dir.mkdir()
            with (
                patch("colab.environment._check_system_dependencies", return_value={}),
                patch("colab.environment._ensure_python_requirements", return_value=[]),
                patch("colab.environment.verify_patched_checkout"),
                patch("colab.environment.collect_runtime_facts", return_value=runtime_facts()),
                patch("colab.environment._read_build_fingerprint", return_value=None),
                patch("colab.environment.ensure_ns3_source") as ensure_source,
                patch("colab.environment._apply_instrumentation") as apply_instrumentation,
            ):
                with self.assertRaises(EnvironmentSetupError):
                    setup_environment(mode="VERIFY", project_dir=project, ns3_dir=ns3_dir)

            ensure_source.assert_not_called()
            apply_instrumentation.assert_not_called()

    def test_verify_mode_rejects_build_cache_writes_before_setup(self) -> None:
        with self.assertRaisesRegex(ValueError, "VERIFY mode cannot save"):
            setup_environment(
                mode="VERIFY",
                project_dir=PROJECT_ROOT,
                build_cache_dir=PROJECT_ROOT / "cache",
                save_cache=True,
            )

    def test_setup_bundle_is_complete_deterministic_and_pinned_in_notebook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "stage2_setup_sources.zip"
            first_hash = build_bundle(bundle)
            first_bytes = bundle.read_bytes()
            second_hash = build_bundle(bundle)

            self.assertEqual(first_hash, second_hash)
            self.assertEqual(first_bytes, bundle.read_bytes())
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(set(archive.namelist()), set(BUNDLE_FILES))
                for relative in BUNDLE_FILES:
                    self.assertEqual(
                        archive.read(relative),
                        (PROJECT_ROOT / relative).read_bytes(),
                    )

            notebook = json.loads(
                (PROJECT_ROOT / "colab/00_environment_setup.ipynb").read_text(
                    encoding="utf-8"
                )
            )
            notebook_source = "\n".join(
                line
                for cell in notebook["cells"]
                if cell["cell_type"] == "code"
                for line in cell["source"]
            )
            self.assertIn(first_hash, notebook_source)
            verification_notebook = json.loads(
                (PROJECT_ROOT / "colab/01_environment_verification.ipynb").read_text(
                    encoding="utf-8"
                )
            )
            verification_source = "\n".join(
                line
                for cell in verification_notebook["cells"]
                if cell["cell_type"] == "code"
                for line in cell["source"]
            )
            self.assertIn("DRIVE_ROOT / 'DISSERTATION'", verification_source)
            self.assertNotIn("MANET_DISSERTATION", verification_source)

    def test_setup_notebook_bootstraps_missing_drive_sources(self) -> None:
        notebook = json.loads(
            (PROJECT_ROOT / "colab/00_environment_setup.ipynb").read_text(
                encoding="utf-8"
            )
        )
        setup_cell = next(
            cell["source"]
            for cell in notebook["cells"]
            if cell.get("id") == "setup-drive"
        )
        source = "\n".join(setup_cell)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "stage2_setup_sources.zip"
            build_bundle(bundle)
            drive_root = root / "drive/MyDrive"
            project = drive_root / "DISSERTATION"
            project.mkdir(parents=True)

            google_module = types.ModuleType("google")
            google_module.__path__ = []
            colab_module = types.ModuleType("google.colab")
            colab_module.drive = types.SimpleNamespace(mount=lambda _: None)
            colab_module.files = types.SimpleNamespace(
                upload=lambda: {"stage2_setup_sources.zip": bundle.read_bytes()}
            )
            patched_source = source.replace(
                "Path('/content/drive/MyDrive')",
                f"Path({str(drive_root)!r})",
            )
            old_path = sys.path.copy()
            try:
                with patch.dict(
                    sys.modules,
                    {"google": google_module, "google.colab": colab_module},
                ):
                    exec(compile(patched_source, "setup-drive-cell", "exec"), {})
            finally:
                sys.path[:] = old_path

            for relative in BUNDLE_FILES:
                self.assertEqual(
                    (project / relative).read_bytes(),
                    (PROJECT_ROOT / relative).read_bytes(),
                )


class BuildCacheTests(unittest.TestCase):
    def test_fingerprint_changes_with_compiler(self) -> None:
        facts = runtime_facts()
        first = build_fingerprint(
            facts,
            patch_sha256="a" * 64,
            ns3_dir=Path("/content/ns-3.48"),
        )
        changed = RuntimeFacts(**{**facts.__dict__, "compiler": "g++ other"})
        second = build_fingerprint(
            changed,
            patch_sha256="a" * 64,
            ns3_dir=Path("/content/ns-3.48"),
        )
        self.assertNotEqual(first, second)

    def test_cache_round_trip_verifies_hash_and_fingerprint(self) -> None:
        facts = runtime_facts()
        patch_hash = "b" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            (source / "build").mkdir(parents=True)
            fingerprint = build_fingerprint(
                facts,
                patch_sha256=patch_hash,
                ns3_dir=source,
            )
            (source / "build" / BUILD_FINGERPRINT_FILE).write_text(
                fingerprint + "\n",
                encoding="utf-8",
            )
            (source / "build" / "artifact.txt").write_text("ok", encoding="utf-8")
            cache_dir = root / "cache"
            archive = save_build_cache(
                source,
                cache_dir,
                fingerprint=fingerprint,
                patch_sha256=patch_hash,
                facts=facts,
            )

            destination = root / "restored"
            destination.mkdir()
            restored = restore_build_cache(
                destination,
                cache_dir,
                fingerprint=fingerprint,
                patch_sha256=patch_hash,
            )

            self.assertTrue(restored)
            self.assertEqual(
                (destination / "build" / "artifact.txt").read_text(encoding="utf-8"),
                "ok",
            )
            self.assertEqual(archive.parent, cache_dir)

    def test_cache_rejects_archive_hash_mismatch(self) -> None:
        facts = runtime_facts()
        patch_hash = "c" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            build_dir = source / "build"
            build_dir.mkdir(parents=True)
            fingerprint = build_fingerprint(
                facts,
                patch_sha256=patch_hash,
                ns3_dir=source,
            )
            (build_dir / BUILD_FINGERPRINT_FILE).write_text(fingerprint, encoding="utf-8")
            cache_dir = root / "cache"
            archive = save_build_cache(
                source,
                cache_dir,
                fingerprint=fingerprint,
                patch_sha256=patch_hash,
                facts=facts,
            )
            archive.write_bytes(archive.read_bytes() + b"tampered")
            destination = root / "restored"
            destination.mkdir()

            with self.assertRaises(EnvironmentSetupError):
                restore_build_cache(
                    destination,
                    cache_dir,
                    fingerprint=fingerprint,
                    patch_sha256=patch_hash,
                )
            self.assertFalse((destination / "build").exists())

    def test_cache_rejects_path_traversal(self) -> None:
        malicious = tarfile.TarInfo("../outside")
        malicious.type = tarfile.REGTYPE
        with self.assertRaises(EnvironmentSetupError):
            _validate_archive_members([malicious])


if __name__ == "__main__":
    unittest.main()
