#!/usr/bin/env python3
"""Build a hash-pinned, locally adapted macOS writer. Never opens USB."""

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
SIZES = dict(
    misc=1048576,
    splloader=262144,
    sml_b=1048576,
    uboot_b=9437184,
    init_boot_b=8388608,
    trustos_b=6291456,
)
HEX = re.compile(r"[0-9a-f]{64}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Command failed: " + shlex.join(cmd) + "\n" + result.stderr[-8000:])
    return result.stdout


def profile_header(p, path):
    lines = [
        "#pragma once",
        "static const char *candidate_path="
        + json.dumps(str(Path(p["candidate"]).resolve()))
        + ";",
        "static const char *write_target=" + json.dumps(p["target"]) + ";",
        "static const size_t candidate_size=" + str(p["size"]) + ";",
        "static const char *candidate_hash=" + json.dumps(p["candidate_sha256"]) + ";",
        "static const struct pinned_part {const char *name;size_t size;const char *before,*after;} pinned_parts[]={",
    ]
    for name in SIZES:
        lines.append(
            "{%s,%d,%s,%s},"
            % (
                json.dumps(name),
                p["sizes"][name],
                json.dumps(p["before"][name]),
                json.dumps(p["after"][name]),
            )
        )
    path.write_text("\n".join(lines + ["};", ""]))


def command(out, p):
    cmd = [
        "--wait",
        "300",
        "--verbose",
        "1",
        "--kickto",
        "2",
        "exec",
        "verbose",
        "0",
        "path",
        str(out),
    ]
    for phase in ["pre", "post"]:
        for name in SIZES:
            cmd += ["read_part", name, "0", str(p["sizes"][name]), f"{phase}-{name}.bin"]
        cmd += ["verify_before", "write_pinned"] if phase == "pre" else ["verify_after"]
    return cmd + ["reset"]


def synthetic_tests(src, flags, work):
    """Synthetic bytes only: no device dumps, USB library calls or hardware."""
    with tempfile.TemporaryDirectory(prefix="native-test-", dir=work) as tmp:
        t = Path(tmp)
        p: dict[str, Any] = {
            "candidate": str(t / "candidate.bin"),
            "target": "init_boot_b",
            "size": 131073,
            "sizes": {n: 257 for n in SIZES},
            "before": {},
            "after": {},
        }
        p["sizes"]["init_boot_b"] = p["size"]
        candidate = bytes(range(256)) * 512 + b"X"
        Path(p["candidate"]).write_bytes(candidate)
        p["candidate_sha256"] = sha(p["candidate"])
        for index, name in enumerate(SIZES):
            before = bytes([index + 1]) * p["sizes"][name]
            after = candidate if name == p["target"] else before
            (t / f"pre-{name}.bin").write_bytes(before)
            (t / f"post-{name}.bin").write_bytes(after)
            p["before"][name] = hashlib.sha256(before).hexdigest()
            p["after"][name] = hashlib.sha256(after).hexdigest()
        profile_header(p, t / "test_profile.h")
        binary = t / "test-guard"
        run(
            [
                "clang",
                "-O2",
                "-DUSE_LIBUSB=1",
                '-DPROFILE_HEADER="test_profile.h"',
                "-I" + str(t),
                "-I" + str(src),
                *flags,
                str(NATIVE / "test_trial.c"),
                str(src / "u30_guard.c"),
                "-o",
                str(binary),
            ]
        )
        cmd = command(t, p)
        total = 0
        for case in [
            "success",
            "write-before-check",
            "before-mismatch",
            "wrong-slot",
            "wrong-size",
            "start-fail",
            "data-fail",
            "end-fail",
            "repeat-write",
            "after-mismatch",
        ]:
            r = subprocess.run(
                [str(binary), case, *cmd], capture_output=True, text=True, timeout=10
            )
            expected = 0 if case == "success" else 1
            if r.returncode != expected:
                raise RuntimeError(f"Synthetic test {case} failed: {r.returncode} {r.stderr}")
            total += 1
        try:
            run([str(binary), "freeze", *cmd])
            total += 1
        finally:
            Path(p["candidate"]).write_bytes(candidate)
        for mutated in [b"bad candidate", candidate[:-1], candidate + b"X"]:
            try:
                Path(p["candidate"]).write_bytes(mutated)
                run([str(binary), "bad-cli", *cmd])
                total += 1
            finally:
                Path(p["candidate"]).write_bytes(candidate)
        for phase in ["pre", "post"]:
            path = t / f"{phase}-misc.bin"
            original = path.read_bytes()
            for mutated in [
                bytes([original[0] ^ 1]) + original[1:],
                original[:-1],
                original + b"X",
            ]:
                try:
                    path.write_bytes(mutated)
                    r = subprocess.run(
                        [str(binary), "hash-corrupt", *cmd],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if r.returncode != 1 or "hash mismatch" not in r.stderr:
                        raise RuntimeError("Synthetic exact hash/size rejection failed")
                    total += 1
                finally:
                    path.write_bytes(original)
        for bad in [
            cmd + ["reset"],
            [x for x in cmd if x != "verify_before"],
            [x for x in cmd if x != "verify_after"],
            ["--wait", "300", "w", p["target"], p["candidate"]],
        ]:
            run([str(binary), "bad-cli", *bad])
            total += 1
        return total


def validate_read_plan(p):
    if (
        set(p) != {"partitions"}
        or not isinstance(p["partitions"], list)
        or not 1 <= len(p["partitions"]) <= 200
    ):
        raise ValueError("Read plan needs 1..200 partitions")
    filenames = set()
    for part in p["partitions"]:
        if set(part) != {"name", "size", "filename"}:
            raise ValueError("Each read needs name,size,filename")
        if not isinstance(part["name"], str) or not re.fullmatch(
            r"[a-z][a-z0-9_]{0,34}", part["name"]
        ):
            raise ValueError("Invalid partition name")
        if (
            not isinstance(part["size"], int)
            or isinstance(part["size"], bool)
            or not 1 <= part["size"] <= 8 * 1024**3
        ):
            raise ValueError("Invalid read size")
        if not isinstance(part["filename"], str) or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,80}\.bin", part["filename"]
        ):
            raise ValueError("Invalid output filename")
        if part["filename"] in filenames:
            raise ValueError("Each output filename must be unique")
        filenames.add(part["filename"])
    if sum(x["size"] for x in p["partitions"]) > 32 * 1024**3:
        raise ValueError("Read plan exceeds 32 GiB")


def read_header(p, path):
    lines = [
        "#pragma once",
        "static const struct read_part {const char *name;size_t size;const char *filename;} read_parts[]={",
    ]
    for part in p["partitions"]:
        lines.append(
            "{%s,%d,%s}," % (json.dumps(part["name"]), part["size"], json.dumps(part["filename"]))
        )
    path.write_text("\n".join(lines + ["};", ""]))


def read_tests(src, flags, work):
    with tempfile.TemporaryDirectory(prefix="read-test-", dir=work) as tmp:
        t = Path(tmp)
        p = {"partitions": [{"name": "misc", "size": 31, "filename": "misc.bin"}]}
        read_header(p, t / "read_test.h")
        output = t / "misc.bin"
        output.write_bytes(b"X" * 31)
        binary = t / "test-read"
        run(
            [
                "clang",
                "-O2",
                "-DUSE_LIBUSB=1",
                '-DPROFILE_HEADER="read_test.h"',
                "-I" + str(t),
                "-I" + str(src),
                *flags,
                str(NATIVE / "test_read.c"),
                str(NATIVE / "u30_read_guard.c"),
                "-o",
                str(binary),
            ]
        )
        cmd = [
            "--wait",
            "300",
            "--verbose",
            "1",
            "--kickto",
            "2",
            "exec",
            "verbose",
            "0",
            "path",
            str(t),
            "read_part",
            "misc",
            "0",
            "31",
            "misc.bin",
            "verify_after",
            "reset",
        ]
        total = 0
        for case, expected in [("success", 0), ("write", 1), ("repeat", 1)]:
            r = subprocess.run([str(binary), case, *cmd], capture_output=True, text=True, timeout=5)
            if r.returncode != expected:
                raise RuntimeError("Read guard test failed: " + case)
            total += 1
        for payload in [b"", b"X" * 30, b"X" * 32]:
            output.write_bytes(payload)
            r = subprocess.run(
                [str(binary), "success", *cmd], capture_output=True, text=True, timeout=5
            )
            if r.returncode != 1:
                raise RuntimeError("Incomplete read accepted")
            total += 1
        output.unlink()
        r = subprocess.run(
            [str(binary), "success", *cmd], capture_output=True, text=True, timeout=5
        )
        if r.returncode != 1:
            raise RuntimeError("Missing read accepted")
        total += 1
        for bad in [
            cmd[:-2] + ["reset"],
            cmd + ["reset"],
            ["--wait", "300", "w", "misc", "misc.bin"],
        ]:
            run([str(binary), "bad-cli", *bad])
            total += 1
        return total


def validate_profile(p):
    required = {"candidate", "target", "size", "candidate_sha256", "before", "after", "sizes"}
    optional = {"stage", "serial", "usb_bus", "usb_ports", "boot_control", "created_utc"}
    if not required <= set(p) or set(p) - required - optional:
        raise ValueError(
            "Profile requires candidate,target,size,candidate_sha256,before,after,sizes; unknown metadata is rejected"
        )
    if (
        p["target"] not in ("init_boot_b", "trustos_b")
        or p["sizes"] != SIZES
        or any(type(v) is not int for v in p["sizes"].values())
    ):
        raise ValueError("Only audited B-slot partition names and exact sizes are supported")
    if p["size"] != SIZES[p["target"]] or isinstance(p["size"], bool):
        raise ValueError("Candidate size does not match target partition")
    for phase in ["before", "after"]:
        if set(p[phase]) != set(SIZES) or any(
            not isinstance(h, str) or not HEX.fullmatch(h) for h in p[phase].values()
        ):
            raise ValueError("Exactly six lowercase SHA-256 hashes required")
    if not isinstance(p["candidate_sha256"], str) or not HEX.fullmatch(p["candidate_sha256"]):
        raise ValueError("Invalid candidate hash")
    if p["before"][p["target"]] == p["after"][p["target"]]:
        raise ValueError("Target before and after must differ")
    if p["after"][p["target"]] != p["candidate_sha256"]:
        raise ValueError("After hash must equal candidate hash")
    if any(p["before"][n] != p["after"][n] for n in SIZES if n != p["target"]):
        raise ValueError("Only one target partition may change")
    if not isinstance(p["candidate"], str) or not Path(p["candidate"]).is_absolute():
        raise ValueError("Candidate path must be absolute")
    candidate = Path(p["candidate"]).resolve(strict=True)
    if candidate.stat().st_size != p["size"] or sha(candidate) != p["candidate_sha256"]:
        raise ValueError("Candidate bytes do not match profile")
    p["candidate"] = str(candidate)


def build(package, work, profile=None, read_plan=None):
    if platform.system() != "Darwin":
        raise ValueError("Native build currently supports macOS only (CommonCrypto)")
    work = work.resolve()
    if work == ROOT or ROOT in work.parents:
        raise ValueError("Work must be outside the public repository")
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", str(work))
        or ".." in str(work)
        or len(str(work)) > 240
    ):
        raise ValueError(
            "Work path must be absolute, ASCII, no spaces or parent components, <=240 characters"
        )
    os.umask(0o077)
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.chmod(0o700)
    src, out = work / "src", work / "build"
    for directory in (src, out, work / "upstream-input"):
        if directory.is_symlink():
            raise ValueError("Build directories must not be symlinks")
        directory.mkdir(exist_ok=True, mode=0o700)
    upstream = package.resolve() / "assets/continuation/reader_source"
    pins = json.loads((NATIVE / "upstream-sha256.json").read_text())
    frozen = work / "upstream-input"
    frozen.mkdir(exist_ok=True)
    for name, digest in pins.items():
        data = (upstream / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Upstream source mismatch: " + name)
        (frozen / name).write_bytes(data)
    upstream = frozen
    spec = importlib.util.spec_from_file_location("native_adapter", NATIVE / "adapt.py")
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load local native adapter")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.adapt(upstream, src)
    for name in ["common.h", "spd_cmd.h", "GITVER.h"]:
        shutil.copyfile(upstream / name, src / name)
    for name in [
        "u30_guard.c",
        "u30_guard.h",
        "u30_usb.c",
        "u30_usb.h",
        "usb-location.c",
        "usb-interfaces.c",
    ]:
        shutil.copyfile(NATIVE / name, src / name)
    if shutil.which("pkg-config"):
        cflags = shlex.split(run(["pkg-config", "--cflags", "libusb-1.0"]))
        ldflags = shlex.split(run(["pkg-config", "--libs", "libusb-1.0"]))
    else:
        prefix = Path(run(["brew", "--prefix", "libusb"]).strip())
        cflags = ["-I" + str(prefix / "include/libusb-1.0")]
        ldflags = ["-L" + str(prefix / "lib"), "-lusb-1.0"]
    tests = synthetic_tests(src, cflags, work)
    config = read_plan if read_plan is not None else profile
    if config is None:
        raise ValueError("Profile or read plan required")
    p = json.loads(config.read_text())
    if read_plan is None:
        validate_profile(p)
        profile_header(p, src / "profile.h")
    else:
        validate_read_plan(p)
        read_header(p, src / "profile.h")
        tests += read_tests(src, cflags, work)
        shutil.copyfile(NATIVE / "u30_read_guard.c", src / "u30_guard.c")
    binary = out / ("u30-reader" if read_plan is not None else "u30-writer")
    run(
        [
            "clang",
            "-O2",
            "-DUSE_LIBUSB=1",
            '-DPROFILE_HEADER="profile.h"',
            *cflags,
            *[str(src / n) for n in ["spd_dump.c", "common.c", "u30_guard.c", "u30_usb.c"]],
            *ldflags,
            "-lpthread",
            "-lm",
            "-o",
            str(binary),
        ]
    )
    for bad in [
        ["w", "trustos_b", "bad.bin"],
        ["erase_all"],
        ["reset"],
        ["--wait", "0", "write_pinned"],
    ]:
        r = subprocess.run([str(binary), *bad], capture_output=True, text=True, timeout=3)
        if r.returncode != 64 or "Waiting for" in r.stderr:
            raise RuntimeError("Compiled CLI rejection test failed")
    locator = out / "usb-location"
    run(["clang", "-O2", *cflags, str(src / "usb-location.c"), *ldflags, "-o", str(locator)])
    interfaces = out / "usb-interfaces"
    run(["clang", "-O2", *cflags, str(src / "usb-interfaces.c"), *ldflags, "-o", str(interfaces)])
    manifest = {
        "mode": "read" if read_plan is not None else "write",
        "binary": str(binary),
        "binary_sha256": sha(binary),
        "profile": str(config.resolve()),
        "profile_sha256": sha(config),
        "usb_interfaces": str(interfaces),
        "usb_interfaces_sha256": sha(interfaces),
        "usb_location": str(locator),
        "usb_location_sha256": sha(locator),
        "synthetic_tests_passed": tests + 4,
        "hardware_tested": False,
        "source_sha256": {f.name: sha(f) for f in src.iterdir() if f.is_file()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", type=Path)
    mode.add_argument("--read-plan", type=Path)
    a = parser.parse_args()
    print(json.dumps(build(a.package, a.work, a.profile, a.read_plan), indent=2))


if __name__ == "__main__":
    main()
