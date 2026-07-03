from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

DIAGNOSTICS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIAGNOSTICS_ROOT / "src"))

from sentryalert_diag import atomic, config as diag_config, state
from sentryalert_diag.cli import parse_duration
from sentryalert_diag.exporter import _sentryalert_version
from sentryalert_diag.modules.usb import UsbDiagnosticModule


class DurationTests(unittest.TestCase):
    def test_duration_units(self) -> None:
        self.assertEqual(parse_duration("30m"), 1800)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("45s"), 45)

    def test_duration_rejects_zero(self) -> None:
        with self.assertRaises(Exception):
            parse_duration("0m")

    def test_default_runtime_is_thirty_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            diag_config, "CONFIG_PATH", Path(directory) / "missing.json"
        ):
            self.assertEqual(diag_config.load_config()["default_runtime_seconds"], 1800)


class VersionDetectionTests(unittest.TestCase):
    def test_package_lock_is_used_when_package_json_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package-lock.json").write_text(
                '\ufeff{"version":"0.6.2.8"}\n', encoding="utf-8"
            )
            self.assertEqual(_sentryalert_version(root), "0.6.2.8")


class AtomicStateTests(unittest.TestCase):
    def test_atomic_json_has_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "state.json"
            atomic.atomic_write_json(destination, {"enabled": True})
            self.assertEqual(json.loads(destination.read_text()), {"enabled": True})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_load_falls_back_to_previous_valid_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / "state.json"
            previous = Path(directory) / "state.previous.json"
            current.write_text("{interrupted", encoding="utf-8")
            previous.write_text('{"session_id":"safe"}', encoding="utf-8")
            with mock.patch.object(state, "STATE_PATH", current), mock.patch.object(
                state, "PREVIOUS_STATE_PATH", previous
            ):
                recovered = state.load_state(required=True)
            self.assertEqual(recovered["session_id"], "safe")


class UsbEventTests(unittest.TestCase):
    def test_only_new_matching_kernel_lines_become_events(self) -> None:
        module = UsbDiagnosticModule()
        with mock.patch.object(
            module, "_kernel_lines", side_effect=[["usb 1 connected"], ["usb 1 connected", "usb 1 disconnect"]]
        ):
            self.assertEqual(module.check_events(), [])
            events = module.check_events()
        self.assertEqual(len(events), 1)
        self.assertIn("disconnect", events[0]["message"])

    def test_non_usb_noise_is_ignored(self) -> None:
        module = UsbDiagnosticModule()
        with mock.patch.object(module, "_kernel_lines", side_effect=[[], ["ordinary message"]]):
            module.check_events()
            self.assertEqual(module.check_events(), [])


class ConfigSummaryTests(unittest.TestCase):
    def test_helper_never_outputs_telegram_credentials(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.js"
            token = "123456:VERY_SECRET_BOT_TOKEN"
            chat_id = "99887766"
            config_path.write_text(
                f"module.exports={{telegramAPIToken:'{token}',telegramChatID:'{chat_id}',board:'rz3w'}};\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(DIAGNOSTICS_ROOT / "helpers" / "config-summary.js"), str(config_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertNotIn(token, result.stdout)
            self.assertNotIn(chat_id, result.stdout)
            summary = json.loads(result.stdout)
            self.assertTrue(summary["telegram"]["tokenConfigured"])
            self.assertTrue(summary["telegram"]["chatIdConfigured"])


class EndToEndSessionTests(unittest.TestCase):
    def test_one_second_session_completes_and_exports(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory) / "data"
            data_root.mkdir()
            sentryalert_root = Path(directory) / "SentryAlert"
            sentryalert_root.mkdir()
            (sentryalert_root / "package.json").write_text(
                '{"version":"test"}\n', encoding="utf-8"
            )
            (data_root / "config.json").write_text(
                json.dumps(
                    {
                        "checkpoint_seconds": 1,
                        "command_timeout_seconds": 1,
                        "default_runtime_seconds": 1,
                        "snapshot_cooldown_seconds": 1,
                        "maximum_snapshots": 2,
                        "maximum_log_bytes": 1048576,
                        "sentryalert_root": str(sentryalert_root),
                        "telegram_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                **os.environ,
                "SENTRYALERT_DIAG_DATA_ROOT": str(data_root),
                "SENTRYALERT_DIAG_ALLOW_NONROOT": "1",
                "SENTRYALERT_DIAG_SKIP_SYSTEMD": "1",
                "PYTHONPATH": str(DIAGNOSTICS_ROOT / "src"),
            }
            cli = str(DIAGNOSTICS_ROOT / "src" / "diagnostics_cli.py")
            subprocess.run(
                [sys.executable, cli, "start", "--duration", "1s"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            subprocess.run(
                [sys.executable, cli, "daemon"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
                timeout=15,
            )
            status_result = subprocess.run(
                [sys.executable, cli, "status"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            final_state = json.loads(status_result.stdout)
            self.assertEqual(final_state["status"], "completed")
            bundle = Path(final_state["export_path"])
            self.assertTrue(bundle.is_file())
            with zipfile.ZipFile(bundle) as archive:
                self.assertIn("SUMMARY.txt", archive.namelist())
                self.assertIn("MANIFEST.sha256", archive.namelist())
                bundled_state = json.loads(archive.read("state.json"))
                self.assertEqual(bundled_state["telegram_delivery"]["status"], "pending")

            # Simulate power loss after completion was checkpointed but before
            # export finished. Boot recovery must retry finalization immediately.
            state_path = data_root / "usb-diag" / "state.json"
            interrupted = json.loads(state_path.read_text(encoding="utf-8"))
            interrupted["enabled"] = True
            interrupted["status"] = "finalizing"
            interrupted.pop("export_path", None)
            state_path.write_text(json.dumps(interrupted), encoding="utf-8")
            bundle.unlink()
            subprocess.run(
                [sys.executable, cli, "daemon"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
                timeout=15,
            )
            recovered = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(recovered["status"], "completed")
            self.assertTrue(Path(recovered["export_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
