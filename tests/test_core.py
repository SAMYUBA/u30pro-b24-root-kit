import base64
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core


def archive(entries):
    out = bytearray()
    for name, value in [*entries, ("TRAILER!!!", b"")]:
        fields = [1, 0o100640, 0, 0, 1, 0, len(value), 0, 0, 0, 0, len(name) + 1, 0]
        out.extend(b"070701" + "".join(f"{x:08x}" for x in fields).encode())
        out.extend(name.encode() + b"\0")
        out.extend(b"\0" * (-len(out) % 4))
        out.extend(value)
        out.extend(b"\0" * (-len(out) % 4))
    return bytes(out)


class CoreTests(unittest.TestCase):
    def test_cpio_replace_preserves_unmodified_entry(self):
        original = archive([("a", b"123"), ("b", b"456")])
        updated = core.replace_cpio(original, {"a": b"long replacement"})
        self.assertEqual(core.cpio_entries(updated)["b"], core.cpio_entries(original)["b"])
        self.assertEqual(core.cpio_entries(updated)["a"][1], b"long replacement")

    def test_cpio_identity(self):
        original = archive([("a", b"123")])
        self.assertEqual(core.replace_cpio(original, {"a": b"123"}), original)

    def test_repeated_stock_empty_directory_is_preserved(self):
        original = archive([("dev", b""), ("dev", b""), ("a", b"123")])
        # Two inode records for one empty directory are legitimate in stock newc.
        original = original.replace(b"000081a0", b"000041a0", 2)
        updated = core.replace_cpio(original, {"a": b"other"})
        self.assertEqual(sum(r[0] == "dev" for r in core.cpio_records(updated)), 2)
        self.assertEqual(core.cpio_entries(updated)["a"][1], b"other")

    def test_bad_cpio(self):
        for blob in [
            b"",
            archive([("../a", b"x")]),
            archive([("a", b"x"), ("a", b"y")]),
            archive([("a", b"x")])[:-5],
        ]:
            with self.subTest(blob=blob[:20]), self.assertRaises(ValueError):
                core.cpio_entries(blob)

    def test_missing_replace(self):
        with self.assertRaises(ValueError):
            core.replace_cpio(archive([("a", b"x")]), {"missing": b"y"})

    def test_public_key_drops_identity_comment(self):
        raw = struct.pack("<I", 64) + bytes(520)
        key = base64.b64encode(raw) + b" someone@somewhere\n"
        self.assertEqual(core.public_key(key), base64.b64encode(raw) + b" u30-local\n")

    def test_private_or_bad_key_rejected(self):
        for key in [
            b"-----BEGIN " + b"PRIVATE KEY-----",
            b"bad",
            base64.b64encode(bytes(524)),
            b"a\nb",
        ]:
            with self.assertRaises(ValueError):
                core.public_key(key)

    def test_bad_profile(self):
        with self.assertRaises(ValueError):
            core.validate_profile({"target": "userdata"})

    def test_usb_binding(self):
        self.assertEqual(core.usb_binding("1", "2.3"), ("1", "2.3"))
        for bus, ports in [("1", ""), ("1", "0"), ("-1", "2"), ("1", "1;reboot"), ("1", "1.")]:
            with self.assertRaises(ValueError):
                core.usb_binding(bus, ports)


if __name__ == "__main__":
    unittest.main()
