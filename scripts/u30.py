#!/usr/bin/env python3
"""U30 B24: private local inputs, explicit stages, no implicit device writes."""

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from core import (
    ROOT,
    PARTS,
    active_b,
    checked_package,
    private_directory,
    require,
    save,
    sha,
    usb_binding,
    validate_profile,
)


def read_json(path):
    return json.loads(Path(path).read_text())


def doctor(_):
    commands = {n: shutil.which(n) for n in ("clang", "brew", "pkg-config", "lz4", "7zz", "adb")}
    print(
        json.dumps(
            {
                "os": platform.system(),
                "architecture": platform.machine(),
                "informational_only_not_flash_readiness": True,
                "python": platform.python_version(),
                "python_supported": sys.version_info >= (3, 11),
                "native_flash_supported": platform.system() == "Darwin",
                "tools": commands,
                "free_gib": round(shutil.disk_usage(Path.cwd()).free / 2**30, 1),
                "device_contacted": False,
            },
            indent=2,
        )
    )


def fetch(a):
    destination = private_directory(a.directory)
    lock = read_json(ROOT / "sources.lock.json")
    for item in lock["volumes"]:
        path = destination / item["name"]
        if path.exists():
            require(
                path.stat().st_size == item["bytes"] and sha(path) == item["sha256"],
                f"Existing volume is corrupt: {path.name}; retain separately for diagnosis",
            )
            continue
        if not a.download:
            print(json.dumps(item))
            continue
        require(
            shutil.disk_usage(destination).free > item["bytes"] + 2**30,
            "Insufficient download space",
        )
        part = path.with_suffix(path.suffix + ".partial")
        require(
            not part.exists(), "Partial file exists; inspect/remove that file manually before retry"
        )
        request = urllib.request.Request(item["url"], headers={"User-Agent": "u30-root-kit"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("xb") as stream:
            shutil.copyfileobj(response, stream, 2**20)
        require(
            part.stat().st_size == item["bytes"] and sha(part) == item["sha256"],
            "Downloaded volume size/hash mismatch",
        )
        part.rename(path)
        print("verified " + item["name"], flush=True)


def verify_package(a):
    lock = checked_package(a.package)
    print(f"PASS: {len(lock['package_files'])} pinned external inputs; no device contacted")


def candidates(a):
    from candidate import build

    result = build(a.package, a.backup, a.out, a.adb_public_key, a.serial, a.lz4, a.observer)
    print(json.dumps({"status": result["status"], "files": result["files"]}, indent=2))


def profile(a):
    destination = private_directory(Path(a.out).parent) / Path(a.out).name
    lock = read_json(ROOT / "sources.lock.json")
    usb_binding(a.bus, a.ports)
    before = {}
    for name, size in PARTS.items():
        first, second = Path(a.before) / (name + ".bin"), Path(a.second) / (name + ".bin")
        require(first.resolve() != second.resolve(), "Independent read files required")
        require(
            first.is_file()
            and second.is_file()
            and first.stat().st_size == second.stat().st_size == size,
            f"Incomplete reads: {name}",
        )
        require(sha(first) == sha(second), f"Double-read mismatch: {name}")
        before[name] = sha(first)
    boot = active_b((Path(a.before) / "misc.bin").read_bytes())
    for name in ("splloader", "sml_b", "uboot_b"):
        require(before[name] == lock["public_stock"][name]["sha256"], f"Unsupported {name}")
    target = "trustos_b" if a.stage == "trustos" else "init_boot_b"
    candidate = Path(a.candidate).resolve()
    require(
        candidate.is_file() and candidate.stat().st_size == PARTS[target],
        "Candidate missing/wrong length",
    )
    digest = sha(candidate)
    stock_init = lock["public_stock"]["init_boot_b"]["sha256"]
    stock_trust = lock["public_stock"]["trustos_b"]["sha256"]
    if a.stage == "trustos":
        require(
            before["init_boot_b"] == stock_init and before["trustos_b"] == stock_trust,
            "TrustOS stage requires matching stock",
        )
        require(digest == lock["trustos_candidate_sha256"], "Wrong TrustOS candidate")
    else:
        require(
            before["trustos_b"] == lock["trustos_candidate_sha256"],
            "Patched TrustOS must already be verified",
        )
        if a.stage == "root":
            require(
                before["init_boot_b"] == stock_init,
                "Root stage starts from stock init_boot; diagnose modified state separately",
            )
            report = read_json(candidate.parent / "candidate.json")
            require(
                report["files"]["init_boot_b.bin"]["sha256"] == digest
                and report["serial"] == a.serial,
                "Candidate report/identity mismatch",
            )
        else:
            require(digest == stock_init, "Restore must use original matching init_boot")
    after = dict(before, **{target: digest})
    result = {
        "stage": a.stage,
        "serial": a.serial,
        "target": target,
        "candidate": str(candidate),
        "candidate_sha256": digest,
        "size": PARTS[target],
        "sizes": PARTS,
        "before": before,
        "after": after,
        "usb_bus": a.bus,
        "usb_ports": a.ports,
        "boot_control": boot,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    validate_profile(result)
    save(destination, result)
    print("Profile saved locally; review before native build. No device contacted.")


def plan(a):
    require(not a.only or a.partition_table, "--only requires a verified partition table")
    if not a.partition_table:
        sizes = PARTS
    else:
        data = Path(a.partition_table).read_bytes()
        require(data and len(data) % 76 == 0, "Invalid 76-byte partition records")
        sizes = {}
        for offset in range(0, len(data), 76):
            name = data[offset : offset + 72].decode("utf-16le").split("\0", 1)[0]
            require(
                re.fullmatch("[A-Za-z0-9_]+", name) is not None and name not in sizes,
                "Unsafe/duplicate partition name",
            )
            size = int.from_bytes(data[offset + 72 : offset + 76], "little") * 1024
            require(0 < size <= 128 * 2**30, "Invalid partition size")
            sizes[name] = size
        excluded = {
            "userdata",
            "cache",
            "blackbox",
            "sd_klog",
            "sysdumpdb",
            "fulldumpdb",
            "uboot_log",
            "reserve1",
            "reserve2",
        }
        sizes = {n: s for n, s in sizes.items() if n not in excluded}
        require(
            all(sizes.get(n) == s for n, s in PARTS.items() if n != "splloader"),
            "Partition layout differs",
        )
        sizes["splloader"] = PARTS["splloader"]  # Logical reader size, not raw table span.
    if a.only:
        require(
            len(a.only) == len(set(a.only)) and set(a.only) <= set(sizes),
            "Unknown, excluded or duplicate read target",
        )
        sizes = {name: sizes[name] for name in a.only}
    items = [{"name": n, "size": s, "filename": n + ".bin"} for n, s in sizes.items()]
    # All reads twice; conservative and slower. Live NV differences are reviewed, not silently waived.
    items += [{"name": n, "size": s, "filename": n + "-verify.bin"} for n, s in sizes.items()]
    out = private_directory(Path(a.out).parent) / Path(a.out).name
    save(out, {"partitions": items})
    print(
        json.dumps(
            {"read_files": len(items), "total_bytes": 2 * sum(sizes.values()), "writes": False}
        )
    )


def split_reads(a):
    source = Path(a.directory)
    out = private_directory(a.out)
    require(not any(out.iterdir()), "Split destination must be empty")
    for name, size in PARTS.items():
        p, q = source / (name + ".bin"), source / (name + "-verify.bin")
        require(
            p.is_file()
            and q.is_file()
            and p.stat().st_size == q.stat().st_size == size
            and sha(p) == sha(q),
            "Critical double-read mismatch: " + name,
        )
    for directory, suffix in [("first", ""), ("second", "-verify")]:
        (out / directory).mkdir(mode=0o700)
        for name in PARTS:
            shutil.copyfile(source / (name + suffix + ".bin"), out / directory / (name + ".bin"))
    print(
        "Six critical pairs verified and split; this does not validate omitted NV or full recovery."
    )


def run_process(command, out, bus, ports, timeout):
    save(out / "request.json", {"command": command, "usb_bus": bus, "usb_ports": ports})
    with (out / "transport.log").open("xb") as log:
        child = subprocess.Popen(
            command,
            cwd=out,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, U30_USB_BUS=bus, U30_USB_PORTS=ports),
        )
        print(
            "WAITING_FOR_DEVICE: connect powered-off device to pinned physical USB port", flush=True
        )
        try:
            return child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            return -1


def run(a):
    manifest = read_json(a.manifest)
    # native_build owns the exact manifest schema; build path is local and hash-bound.
    binary = Path(manifest["binary"])
    require(sha(binary) == manifest["binary_sha256"], "Native binary changed")
    bus, ports = usb_binding(a.bus, a.ports)
    if a.profile:
        require(manifest["mode"] == "write", "Wrong native build mode")
        config = validate_profile(read_json(a.profile))
        require(sha(a.profile) == manifest["profile_sha256"], "Profile changed since compile")
        require(
            (bus, ports) == (str(config["usb_bus"]), config["usb_ports"]),
            "USB binding differs from profile",
        )
        require(sha(config["candidate"]) == config["candidate_sha256"], "Candidate changed")
    else:
        require(manifest["mode"] == "read", "Wrong native build mode")
        config = read_json(a.read_plan)
        require(sha(a.read_plan) == manifest["profile_sha256"], "Read plan changed")
    parent = private_directory(a.out)
    out = parent / (
        "run-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    command = [
        str(binary),
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
    if a.profile:
        for phase in ("pre", "post"):
            for name, size in PARTS.items():
                command += ["read_part", name, "0", str(size), f"{phase}-{name}.bin"]
            command += ["verify_before", "write_pinned"] if phase == "pre" else ["verify_after"]
        required_space = 2 * sum(PARTS.values()) + 2**30
    else:
        for item in config["partitions"]:
            command += ["read_part", item["name"], "0", str(item["size"]), item["filename"]]
        command += ["verify_after"]
        required_space = sum(i["size"] for i in config["partitions"]) + 2**30
    command += ["reset"]
    if not a.execute:
        print(
            json.dumps(
                {"mode": "DRY_RUN", "command": command, "required_free_bytes": required_space},
                indent=2,
            )
        )
        return
    require(platform.system() == "Darwin", "Native execution supported only on macOS")
    require(shutil.disk_usage(parent).free >= required_space, "Insufficient backup space")
    inventory = manifest["usb_location"]
    require(sha(inventory) == manifest["usb_location_sha256"], "USB inventory binary changed")
    attached = subprocess.check_output([inventory], text=True, timeout=15)
    require(not attached.strip(), "Power off and unplug the target before starting listener")
    out.mkdir(mode=0o700)
    code = run_process(command, out, bus, ports, 600 if a.profile else 7200)
    files: list[dict[str, Any]] = []
    valid = code == 0
    expected_files = []
    if a.profile:
        for phase, mapping in [("pre", "before"), ("post", "after")]:
            expected_files += [
                (f"{phase}-{name}.bin", size, config[mapping][name]) for name, size in PARTS.items()
            ]
    else:
        expected_files = [(item["filename"], item["size"], None) for item in config["partitions"]]
    for name, size, digest in expected_files:
        path = out / name
        actual_size = path.stat().st_size if path.is_file() else None
        actual_hash = sha(path) if path.is_file() else None
        valid = valid and actual_size == size and (digest is None or digest == actual_hash)
        files.append({"file": name, "bytes": actual_size, "sha256": actual_hash})
    log = (out / "transport.log").read_text(errors="replace")
    valid = valid and "TRIAL_RESET_ACKED" in log
    if a.profile:
        valid = valid and "TRIAL_VERIFIED_AFTER" in log
    else:
        valid = valid and "READ_VERIFIED_AFTER" in log
        records = {f["file"]: f for f in files}
        doubles = {
            f["file"][:-4]: f["sha256"] == records[f["file"][:-4] + "-verify.bin"]["sha256"]
            for f in files
            if not f["file"].endswith("-verify.bin") and f["file"][:-4] + "-verify.bin" in records
        }
        valid = valid and all(doubles.values())
    report = {
        "status": "READBACK_VERIFIED_BOOT_CHECK_PENDING"
        if valid
        else "STOP_INSPECT_NO_BLIND_RETRY",
        "exit_code": code,
        "files": files,
        "root_verified": False,
    }
    if not a.profile:
        report["double_read_matches"] = doubles
    save(out / "result.json", report)
    print(json.dumps({"status": report["status"], "output": str(out)}, indent=2))
    require(valid, "Readback failed; inspect local logs. No automatic retry or recovery.")


def root_check(a):
    require(re.fullmatch("[A-Za-z0-9_-]{1,64}", a.serial) is not None, "Invalid serial")
    require(2 <= a.samples <= 60 and 1 <= a.interval <= 60, "Invalid sampling window")
    command = 'id; /debug_ramdisk/magisk -v; for p in sys.boot_completed sys.usb.config sys.usb.state init.svc.adbd ro.adb.secure service.adb.tcp.port ro.boot.slot_suffix; do echo "$p=$(getprop $p)"; done; echo "adb_enabled=$(settings get global adb_enabled)"; cat /proc/uptime'
    samples = []
    for i in range(a.samples):
        r = subprocess.run(
            [a.adb, "-s", a.serial, "shell", "/debug_ramdisk/su", "-c", "'" + command + "'"],
            text=True,
            capture_output=True,
            timeout=15,
        )
        properties = dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)
        valid = (
            r.returncode == 0
            and not r.stderr
            and all(
                s in r.stdout
                for s in [
                    "uid=0(root)",
                    "sys.boot_completed=1",
                    "init.svc.adbd=running",
                    "ro.adb.secure=1",
                    "service.adb.tcp.port=-1",
                    "ro.boot.slot_suffix=_b",
                    "adb_enabled=1",
                ]
            )
        )
        valid = valid and all(
            "adb" in properties.get(key, "").split(",")
            for key in ("sys.usb.config", "sys.usb.state")
        )
        valid = valid and re.search(r"(?m)^30\.7:MAGISK:[A-Za-z]+$", r.stdout) is not None
        samples.append(
            {
                "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "valid": bool(valid),
                "stdout": r.stdout,
                "stderr": r.stderr,
            }
        )
        print(f"sample {i + 1}/{a.samples}: " + ("PASS" if valid else "FAIL"), flush=True)
        if not valid:
            break
        if i < a.samples - 1:
            time.sleep(a.interval)
    out = private_directory(Path(a.out).parent) / Path(a.out).name
    passed = len(samples) == a.samples and all(s["valid"] for s in samples)
    save(
        out,
        {
            "status": "ADB_ROOT_WINDOW_VERIFIED" if passed else "NOT_VERIFIED",
            "samples": samples,
            "operator_home_wifi_confirmation_required": True,
        },
    )
    require(passed, "ADB root validation failed")


def main():
    os.umask(0o077)
    require(sys.version_info >= (3, 11), "Python 3.11+ required")
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("doctor")
    q.set_defaults(func=doctor)
    q = sub.add_parser("fetch")
    q.add_argument("--directory", required=True)
    q.add_argument("--download", action="store_true")
    q.set_defaults(func=fetch)
    q = sub.add_parser("verify-package")
    q.add_argument("--package", required=True)
    q.set_defaults(func=verify_package)
    q = sub.add_parser("candidate")
    for name in ("package", "backup", "out", "serial", "adb-public-key"):
        q.add_argument("--" + name, required=True)
    q.add_argument("--lz4", default="lz4")
    q.add_argument("--observer", action="store_true")
    q.set_defaults(func=candidates)
    q = sub.add_parser("profile")
    q.add_argument("--stage", choices=["trustos", "root", "restore-root"], required=True)
    for name in ("before", "second", "candidate", "serial", "bus", "ports", "out"):
        q.add_argument("--" + name, required=True)
    q.set_defaults(func=profile)
    q = sub.add_parser("read-plan")
    q.add_argument("--partition-table")
    q.add_argument("--only", nargs="+")
    q.add_argument("--out", required=True)
    q.set_defaults(func=plan)
    q = sub.add_parser("split-reads")
    q.add_argument("--directory", required=True)
    q.add_argument("--out", required=True)
    q.set_defaults(func=split_reads)
    q = sub.add_parser("run")
    group = q.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile")
    group.add_argument("--read-plan")
    for name in ("manifest", "bus", "ports", "out"):
        q.add_argument("--" + name, required=True)
    q.add_argument("--execute", action="store_true")
    q.set_defaults(func=run)
    q = sub.add_parser("root-check")
    q.add_argument("--adb", default="adb")
    q.add_argument("--serial", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--samples", type=int, default=7)
    q.add_argument("--interval", type=int, default=10)
    q.set_defaults(func=root_check)
    args = p.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        p.exit(1, f"STOP: {exc}\n")


if __name__ == "__main__":
    main()
