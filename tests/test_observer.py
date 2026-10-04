"""Exercise the finite observer locally; Android commands never reach a device."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "assets/observe.sh.in"


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.first, self.fallback = self.root / "first", self.root / "fallback"
        self.first.mkdir()
        self.fallback.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        mock = """import os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['OBSERVER_CALLS'], 'a') as f:
    f.write(name + ' ' + ' '.join(sys.argv[1:]) + '\\n')
if name == 'settings':
    sys.exit(1)
if name == 'getprop':
    print('synthetic-value')
elif name == 'id':
    print('uid=0(root)')
elif name == 'pidof':
    print('123')
elif name == 'getenforce':
    print('Enforcing')
"""
        for name in ("getprop", "id", "pidof", "getenforce", "settings", "sleep"):
            path = self.bin / name
            path.write_text("#!" + sys.executable + "\n" + mock)
            path.chmod(0o755)

    def enable(self, directory, value="SYNTHETIC-TOKEN\n"):
        (directory / "u30-diag-enable.txt").write_text(value)

    def run_observer(self, args=("--observe",)):
        self.assertTrue(TEMPLATE.exists(), "finite observer template must be implemented")
        script = TEMPLATE.read_text().replace("@TOKEN@", "SYNTHETIC-TOKEN")
        script = script.replace("/mnt/sdcard/DCIM", str(self.first))
        script = script.replace("/data/media/0/DCIM", str(self.fallback))
        script += '\nprintf "FELL_THROUGH\\n"\n'
        path = self.root / "observer.sh"
        path.write_text(script)
        return subprocess.run(
            ["/bin/sh", str(path), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            env=dict(
                os.environ,
                PATH=str(self.bin) + ":/usr/bin:/bin",
                OBSERVER_CALLS=str(self.root / "calls"),
            ),
        )

    def test_missing_and_inexact_marker_never_write(self):
        self.assertEqual(self.run_observer().returncode, 0)
        self.assertFalse((self.first / "u30-diag-runtime.txt").exists())
        for text in ("WRONG\n", "SYNTHETIC-TOKEN\n\n", "SYNTHETIC-TOKEN\nextra\n"):
            with self.subTest(text=text):
                self.enable(self.first, text)
                self.assertEqual(self.run_observer().returncode, 0)
                self.assertFalse((self.first / "u30-diag-runtime.txt").exists())

    def test_fallback_collects_24_snapshots_despite_settings_failure(self):
        self.enable(self.fallback)
        result = self.run_observer()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.fallback / "u30-diag-runtime.txt").read_text()
        self.assertEqual(log.count("snapshot="), 24)
        self.assertIn("adb_enabled=unavailable", log)
        self.assertNotIn("FELL_THROUGH", result.stdout)
        calls = (self.root / "calls").read_text().splitlines()
        self.assertEqual(calls.count("sleep 5"), 24)
        self.assertNotIn("getprop ", calls)

    def test_unwritable_first_output_falls_back(self):
        self.enable(self.first)
        self.enable(self.fallback)
        (self.first / "u30-diag-runtime.txt").symlink_to("/dev/full")
        # A non-regular output is rejected before attempting the second path.
        self.assertEqual(self.run_observer().returncode, 0)
        self.assertTrue((self.fallback / "u30-diag-runtime.txt").is_file())

    def test_symlink_marker_is_not_trusted(self):
        target = self.root / "marker"
        target.write_text("SYNTHETIC-TOKEN\n")
        (self.first / "u30-diag-enable.txt").symlink_to(target)
        self.assertEqual(self.run_observer().returncode, 0)
        self.assertFalse((self.first / "u30-diag-runtime.txt").exists())

    def test_regular_file_write_failure_uses_fallback(self):
        self.enable(self.first)
        self.enable(self.fallback)
        output = self.first / "u30-diag-runtime.txt"
        output.write_text("keep\n")
        output.chmod(0o400)
        if os.getuid() == 0:
            self.skipTest("root bypasses ordinary file permissions")
        self.assertEqual(self.run_observer().returncode, 0)
        self.assertEqual(output.read_text(), "keep\n")
        self.assertIn("snapshot=", (self.fallback / "u30-diag-runtime.txt").read_text())

    def test_no_observe_argument_falls_through_without_observation(self):
        result = self.run_observer(args=())
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "FELL_THROUGH\n")
        self.assertFalse((self.root / "calls").exists())


if __name__ == "__main__":
    unittest.main()
