"""Run the Android shell helper against a temporary filesystem and device-command doubles."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "assets/root_setup.sh.in"
MOCK = r"""
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['MOCK_ROOT'])
state = json.loads((root / 'state.json').read_text())
with (root / 'calls.jsonl').open('a') as f:
    f.write(json.dumps([name, *args]) + '\n')
if state.get('fail') in (name, name + ':' + (args[0] if args else '')):
    sys.exit(9)
if name == 'id':
    print(state['uid'] if args == ['-u'] else 'uid=0(root)')
elif name == 'getprop':
    print({'ro.serialno': state['serial'], 'ro.adb.secure': state['secure']}.get(args[0], ''))
elif name == 'settings':
    if args == ['get', 'global', 'adb_enabled']:
        print(state['adb'])
    elif args == ['put', 'global', 'adb_enabled', '1']:
        state['adb'] = '1'
    else:
        sys.exit(10)
elif name == 'magisk':
    if args == ['-V']:
        if not state['ready']:
            sys.exit(1)
        print('30700')
    elif args == ['su', '-c', 'id']:
        print('uid=0(root)')
    elif args and args[0] == '--sqlite' and '2000' in args[1] and '2' in args[1]:
        pass
    else:
        sys.exit(11)
(root / 'state.json').write_text(json.dumps(state))
"""


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = dict(uid="0", serial="TEST-SERIAL", secure="1", adb="0", ready=True)
        for name in (
            "id",
            "getprop",
            "settings",
            "setprop",
            "start",
            "stop",
            "restorecon",
            "chown",
            "sleep",
            "magisk",
        ):
            path = self.bin / name
            path.write_text("#!" + sys.executable + "\n" + MOCK)
            path.chmod(0o755)
        (self.root / "debug_ramdisk").mkdir()
        (self.root / "debug_ramdisk/magisk").symlink_to(self.bin / "magisk")
        (self.root / "debug_ramdisk/u30_host_adb.pub").write_text("SYNTHETIC-KEY test-only\n")
        self.adb = self.root / "data/misc/adb"
        self.adb.mkdir(parents=True)
        self.keys = self.adb / "adb_keys"
        self.keys.write_text("EXISTING-KEY\n")
        (self.root / "data/local/tmp").mkdir(parents=True)

    def run_helper(self):
        self.assertTrue(TEMPLATE.exists(), "root helper template must be implemented")
        (self.root / "state.json").write_text(json.dumps(self.state))
        script = TEMPLATE.read_text().replace("@SERIAL@", "TEST-SERIAL")
        script = script.replace("/debug_ramdisk", str(self.root / "debug_ramdisk"))
        script = script.replace("/data/", str(self.root / "data") + "/")
        env = dict(os.environ, MOCK_ROOT=str(self.root), PATH=str(self.bin) + ":/usr/bin:/bin")
        result = subprocess.run(
            ["/bin/sh"],
            input=script,
            text=True,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
        self.state = json.loads((self.root / "state.json").read_text())
        return result

    def calls(self):
        path = self.root / "calls.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_success_preserves_keys_and_enables_authenticated_usb(self):
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state["adb"], "1")
        self.assertEqual(self.keys.read_text(), "EXISTING-KEY\nSYNTHETIC-KEY test-only\n")
        self.assertEqual((self.adb / "adb_keys.u30-original").read_text(), "EXISTING-KEY\n")
        calls = self.calls()
        self.assertIn(["setprop", "service.adb.tcp.port", "-1"], calls)
        self.assertLess(
            calls.index(["setprop", "sys.usb.config", "none"]),
            calls.index(["setprop", "sys.usb.config", "ncm,mtp,adb"]),
        )
        log = (self.root / "data/local/tmp/u30_root_setup.log").read_text()
        self.assertIn("adb_enabled_before=0", log)
        self.assertIn("adb_enabled_after=1", log)
        self.assertNotIn("SYNTHETIC-KEY", log)

    def test_repeated_run_never_duplicates_key_or_overwrites_first_backup(self):
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.keys.read_text().count("SYNTHETIC-KEY"), 1)
        self.assertEqual((self.adb / "adb_keys.u30-original").read_text(), "EXISTING-KEY\n")

    def test_guards_reject_without_device_mutations(self):
        for key, value in [("uid", "2000"), ("serial", "OTHER"), ("secure", "0"), ("adb", "null")]:
            with self.subTest(key=key):
                old = self.state[key]
                self.state[key] = value
                before = len(self.calls())
                self.assertNotEqual(self.run_helper().returncode, 0)
                changes = [
                    x
                    for x in self.calls()[before:]
                    if x[0] in ("setprop", "start", "stop", "chown", "restorecon")
                    or x[:2] == ["settings", "put"]
                ]
                self.assertEqual(changes, [])
                self.assertEqual(self.keys.read_text(), "EXISTING-KEY\n")
                self.state[key] = old

    def test_existing_enabled_setting_is_not_rewritten(self):
        self.state["adb"] = "1"
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertNotIn(["settings", "put", "global", "adb_enabled", "1"], self.calls())

    def test_failed_settings_write_stops_before_usb_changes(self):
        self.state["fail"] = "settings:put"
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(any(x[0] == "setprop" for x in self.calls()))

    def test_symlink_key_target_is_rejected(self):
        self.keys.unlink()
        target = self.root / "victim"
        target.write_text("keep")
        self.keys.symlink_to(target)
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(target.read_text(), "keep")

    def test_magisk_timeout_does_not_grant_policy(self):
        self.state["ready"] = False
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(sum(x == ["magisk", "-V"] for x in self.calls()), 15)
        self.assertFalse(any(x[:2] == ["magisk", "--sqlite"] for x in self.calls()))

    def test_usb_command_failure_is_not_reported_as_success(self):
        self.state["fail"] = "setprop"
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(any(x[:2] == ["magisk", "su"] for x in self.calls()))

    def test_policy_failure_stops_before_su_and_success_log(self):
        self.state["fail"] = "magisk:--sqlite"
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(any(x[:2] == ["magisk", "su"] for x in self.calls()))
        self.assertNotIn(
            "root_setup_finished", (self.root / "data/local/tmp/u30_root_setup.log").read_text()
        )


if __name__ == "__main__":
    unittest.main()
