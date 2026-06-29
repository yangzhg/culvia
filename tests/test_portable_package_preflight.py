from __future__ import annotations

import io
import json
import stat
import tarfile
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

from tools import build_linux_tgz, build_windows_zip, check_portable_package_preflight


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_TARGET = "x86_64-pc-windows-msvc"
LINUX_TARGET = "x86_64-unknown-linux-gnu"


def write_fake_pe(path: Path, *, machine: int = 0x8664) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pe_offset = 0x80
    payload = bytearray(pe_offset + 24)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    payload[pe_offset : pe_offset + 4] = b"PE\0\0"
    payload[pe_offset + 4 : pe_offset + 6] = machine.to_bytes(2, "little")
    path.write_bytes(bytes(payload))
    return path


def write_fake_elf(path: Path, *, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF" + b"\x02\x01\x01" + b"\0" * 64)
    path.chmod(mode)
    return path


def fake_windows_backend_path(temp: Path, target: str = WINDOWS_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server.exe"


def fake_linux_backend_path(temp: Path, target: str = LINUX_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server"


class PortablePackagePreflightTests(unittest.TestCase):
    def build_windows_archive(self, temp: Path, *, desktop_machine: int = 0x8664) -> Path:
        desktop = write_fake_pe(temp / "culvia-desktop.exe", machine=desktop_machine)
        backend = write_fake_pe(fake_windows_backend_path(temp))
        package_root, _manifest = build_windows_zip.stage_package(
            desktop_binary=desktop,
            backend_binary=backend,
            target=WINDOWS_TARGET,
            output_dir=temp / "dist",
            root=ROOT,
            config={"productName": "Culvia", "version": "0.1.0"},
        )
        return build_windows_zip.build_archive(
            package_root=package_root,
            output_dir=temp / "dist",
            version="0.1.0",
            target="x86_64-pc-windows-msvc",
        )

    def build_linux_archive(self, temp: Path, *, packaged_backend_mode: int | None = None) -> Path:
        desktop = write_fake_elf(temp / "culvia-desktop")
        backend = write_fake_elf(fake_linux_backend_path(temp))
        package_root, _manifest = build_linux_tgz.stage_package(
            desktop_binary=desktop,
            backend_binary=backend,
            target=LINUX_TARGET,
            output_dir=temp / "dist",
            root=ROOT,
            config={"productName": "Culvia", "version": "0.1.0"},
        )
        if packaged_backend_mode is not None:
            (package_root / build_linux_tgz.backend_package_binary(LINUX_TARGET)).chmod(packaged_backend_mode)
        return build_linux_tgz.build_archive(
            package_root=package_root,
            output_dir=temp / "dist",
            version="0.1.0",
            target=LINUX_TARGET,
        )

    def test_valid_windows_zip_passes_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.build_windows_archive(Path(tmp))

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn("windows portable zip binaries match target", [item["name"] for item in payload["checks"]])

    def test_valid_linux_tgz_passes_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.build_linux_archive(Path(tmp))

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(linux_tgz=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn("linux portable tgz launcher wires bundled runtime", [item["name"] for item in payload["checks"]])

    def test_windows_zip_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../evil.txt", "bad")

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip archive paths are safe", payload["failed"])

    def test_linux_tgz_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                info = tarfile.TarInfo("../evil.txt")
                payload = b"bad"
                info.size = len(payload)
                handle.addfile(info, io.BytesIO(payload))

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(linux_tgz=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("linux portable tgz archive paths are safe", payload["failed"])

    def test_windows_zip_rejects_runtime_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_windows_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            (package_root / "culvia_scores.sqlite").write_text("runtime data", encoding="utf-8")
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip excludes runtime artifacts", payload["failed"])

    def test_windows_zip_rejects_credential_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_windows_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            (package_root / ".env").write_text("OPENAI_API_KEY=placeholder", encoding="utf-8")
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip excludes runtime artifacts", payload["failed"])

    def test_windows_zip_rejects_credential_like_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_windows_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            leak = package_root / "share" / "culvia" / "web" / "leak.txt"
            fake_key = "sk-" + "1234567890abcdef"
            leak.write_text(f"debug key {fake_key} should never ship", encoding="utf-8")
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip excludes secrets and credentials", payload["failed"])

    def test_windows_zip_allows_bundled_certifi_ca_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_windows_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            ca_bundle = (
                package_root
                / "runtime"
                / "backend"
                / WINDOWS_TARGET
                / "culvia-server"
                / "_internal"
                / "certifi"
                / "cacert.pem"
            )
            ca_bundle.parent.mkdir(parents=True)
            ca_bundle.write_text("-----BEGIN CERTIFICATE-----\nplaceholder\n-----END CERTIFICATE-----\n", encoding="utf-8")
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])

    def test_windows_zip_allows_dist_info_record_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_windows_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            record = (
                package_root
                / "runtime"
                / "backend"
                / WINDOWS_TARGET
                / "culvia-server"
                / "_internal"
                / "torch-2.12.1.dist-info"
                / "RECORD"
            )
            record.parent.mkdir(parents=True)
            record.write_text("torch/testing/path_mentions_OPENAI_API_KEY.py,,\n", encoding="utf-8")
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])

    def test_windows_zip_rejects_symlink_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "bad.zip"
            info = zipfile.ZipInfo("culvia-0.1.0-windows-x86_64-pc-windows-msvc/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(info, "target")

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip archive has no links or special entries", payload["failed"])

    def test_windows_zip_rejects_wrong_pe_machine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.build_windows_archive(Path(tmp), desktop_machine=0xAA64)

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_zip=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip binaries match target", payload["failed"])

    def test_linux_tgz_rejects_non_executable_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = self.build_linux_archive(Path(tmp), packaged_backend_mode=0o644)

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(linux_tgz=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("linux portable tgz binaries are ELF and executable", payload["failed"])

    def test_linux_tgz_rejects_private_key_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_linux_backend_path(temp))
            package_root, _manifest = build_linux_tgz.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=LINUX_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            private_key_marker = "PRIVATE KEY"
            (package_root / "share" / "culvia" / "web" / "debug.txt").write_text(
                f"-----BEGIN {private_key_marker}-----\nnot-real\n-----END {private_key_marker}-----\n",
                encoding="utf-8",
            )
            archive = build_linux_tgz.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=LINUX_TARGET,
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(linux_tgz=archive)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("linux portable tgz excludes secrets and credentials", payload["failed"])

    def test_cli_requires_at_least_one_artifact(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = check_portable_package_preflight.main(["--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(payload["failed"], ["portable package artifact selected"])


if __name__ == "__main__":
    unittest.main()
