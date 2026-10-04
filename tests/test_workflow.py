import argparse
import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core
import u30


class WorkflowTests(unittest.TestCase):
    def test_targeted_read_needs_partition_table(self):
        args = argparse.Namespace(only=["nr_runtimenv1"], partition_table=None, out="unused")
        with self.assertRaises(ValueError):
            u30.plan(args)

    def test_targeted_read_rejects_unknown_and_builds_double_read(self):
        with tempfile.TemporaryDirectory(prefix="u30-plan-") as temp:
            table = Path(temp) / "table.bin"
            parts = dict(core.PARTS, nr_runtimenv1=4096)
            table.write_bytes(
                b"".join(
                    n.encode("utf-16le").ljust(72, b"\0") + struct.pack("<I", size // 1024)
                    for n, size in parts.items()
                )
            )
            args = argparse.Namespace(
                only=["missing"], partition_table=table, out=str(Path(temp) / "plan.json")
            )
            with self.assertRaises(ValueError):
                u30.plan(args)
            args.only = ["nr_runtimenv1"]
            with contextlib.redirect_stdout(io.StringIO()):
                u30.plan(args)
            records = json.loads(Path(args.out).read_text())["partitions"]
            self.assertEqual(len(records), 2)
            self.assertEqual(
                {r["filename"] for r in records}, {"nr_runtimenv1.bin", "nr_runtimenv1-verify.bin"}
            )

    def test_boot_control_crc_and_exhausted_slot(self):
        misc = bytearray(core.PARTS["misc"])
        control = bytearray(32)
        control[:4] = b"_b\0\0"
        struct.pack_into("<I", control, 4, 0x42414342)
        control[8:10] = bytes([1, 2])
        for status, valid in [(0x8F, True), (0x1F, True), (0x0F, False), (0, False)]:
            control[14] = status
            struct.pack_into("<I", control, 28, zlib.crc32(control[:28]))
            misc[2048:2080] = control
            if valid:
                self.assertEqual(core.active_b(misc)["suffix"], "_b")
            else:
                with self.assertRaises(ValueError):
                    core.active_b(misc)
        misc[2079] ^= 1
        with self.assertRaises(ValueError):
            core.active_b(misc)

    def test_reader_report_and_double_read(self):
        with tempfile.TemporaryDirectory(prefix="u30-mock-") as temp:
            root = Path(temp)
            binary = root / "native"
            binary.write_bytes(b"not executable")
            plan = root / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "partitions": [
                            {"name": "misc", "size": 4, "filename": "misc.bin"},
                            {"name": "misc", "size": 4, "filename": "misc-verify.bin"},
                        ]
                    }
                )
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "read",
                        "binary": str(binary),
                        "binary_sha256": core.sha(binary),
                        "profile_sha256": core.sha(plan),
                        "usb_location": str(binary),
                        "usb_location_sha256": core.sha(binary),
                    }
                )
            )
            args = argparse.Namespace(
                manifest=manifest,
                profile=None,
                read_plan=plan,
                bus="1",
                ports="2",
                out=root / "out",
                execute=True,
            )

            def execute(command, out, bus, ports, timeout):
                (out / "misc.bin").write_bytes(b"1234")
                (out / "misc-verify.bin").write_bytes(b"1234")
                (out / "transport.log").write_text("READ_VERIFIED_AFTER\nTRIAL_RESET_ACKED\n")
                return 0

            with (
                patch.object(u30, "run_process", execute),
                patch.object(u30.platform, "system", return_value="Darwin"),
                patch.object(u30.subprocess, "check_output", return_value=""),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                u30.run(args)
            result = json.loads(next((root / "out").glob("*/result.json")).read_text())
            self.assertEqual(result["status"], "READBACK_VERIFIED_BOOT_CHECK_PENDING")
            self.assertFalse(result["root_verified"])
            self.assertTrue(result["double_read_matches"]["misc"])

    def test_dry_run_does_not_spawn_or_contact_usb(self):
        with tempfile.TemporaryDirectory(prefix="u30-dry-") as temp:
            root = Path(temp)
            binary = root / "native"
            binary.write_bytes(b"not executable")
            plan = root / "plan.json"
            plan.write_text('{"partitions": []}')
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "mode": "read",
                        "binary": str(binary),
                        "binary_sha256": core.sha(binary),
                        "profile_sha256": core.sha(plan),
                    }
                )
            )
            args = argparse.Namespace(
                manifest=manifest,
                profile=None,
                read_plan=plan,
                bus="1",
                ports="2",
                out=root / "out",
                execute=False,
            )
            with (
                patch.object(
                    u30.subprocess, "Popen", side_effect=AssertionError("Device contacted")
                ),
                patch.object(
                    u30.subprocess, "check_output", side_effect=AssertionError("Device contacted")
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                u30.run(args)

    def test_root_check_rejects_missing_usb_properties(self):
        with tempfile.TemporaryDirectory(prefix="u30-adb-") as temp:
            args = argparse.Namespace(
                serial="TEST_DEVICE",
                samples=2,
                interval=1,
                adb="fake-adb",
                out=str(Path(temp) / "report.json"),
            )
            output = "\n".join(
                [
                    "uid=0(root)",
                    "30.7:MAGISK:R",
                    "sys.boot_completed=1",
                    "init.svc.adbd=running",
                    "ro.adb.secure=1",
                    "service.adb.tcp.port=-1",
                    "ro.boot.slot_suffix=_b",
                    "adb_enabled=1",
                ]
            )
            result = argparse.Namespace(returncode=0, stdout=output, stderr="")
            with (
                patch.object(u30.subprocess, "run", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(ValueError),
            ):
                u30.root_check(args)
            self.assertEqual(json.loads(Path(args.out).read_text())["status"], "NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
