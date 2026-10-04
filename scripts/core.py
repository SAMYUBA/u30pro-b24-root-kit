"""Offline primitives. No USB or subprocess side effects at import time."""

import base64
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = {
    "misc": 1048576,
    "splloader": 262144,
    "sml_b": 1048576,
    "uboot_b": 9437184,
    "init_boot_b": 8388608,
    "trustos_b": 6291456,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    path.chmod(0o600)


def cpio_records(data):
    offset = 0
    seen: dict[str, tuple[int, ...]] = {}
    while offset + 110 <= len(data):
        start = offset
        require(data[offset : offset + 6] == b"070701", "Expected newc archive")
        header = data[offset : offset + 110]
        fields = [int(header[6 + i * 8 : 14 + i * 8], 16) for i in range(13)]
        offset += 110
        n = fields[11]
        require(
            n > 0 and offset + n <= len(data) and data[offset + n - 1] == 0, "Invalid CPIO name"
        )
        name = data[offset : offset + n - 1].decode("utf-8")
        require(
            name and not name.startswith("/") and ".." not in name.split("/"), "Unsafe CPIO name"
        )
        begin = (offset + n + 3) & ~3
        end = (begin + fields[6] + 3) & ~3
        require(end <= len(data), "Truncated CPIO content")
        # The stock kernel-generated newc repeats the empty dev directory.
        # Permit identical directory metadata; duplicate files remain ambiguous.
        identity = tuple(fields[i] for i in (1, 2, 3, 6, 9, 10))
        if name in seen:
            require(
                fields[1] & 0o170000 == 0o040000 and fields[6] == 0 and seen[name] == identity,
                "Duplicate non-directory or conflicting CPIO entry",
            )
        seen[name] = identity
        yield name, fields, data[begin : begin + fields[6]], data[start:end]
        offset = end
        if name == "TRAILER!!!":
            require(not any(data[offset:]), "Nonzero data after CPIO trailer")
            return
    raise ValueError("Missing CPIO trailer")


def cpio_entries(data):
    return {
        name: (fields, payload)
        for name, fields, payload, _ in cpio_records(data)
        if name != "TRAILER!!!"
    }


def replace_cpio(data, replacements):
    records = list(cpio_records(data))
    require(
        set(replacements) <= {r[0] for r in records} - {"TRAILER!!!"}, "Replacement entry missing"
    )
    result = bytearray()
    for name, fields, payload, original in records:
        if name not in replacements:
            result.extend(original)
            continue
        payload = replacements[name]
        fields[6] = len(payload)
        result.extend(b"070701" + "".join(f"{n:08x}" for n in fields).encode())
        result.extend(name.encode() + b"\0")
        result.extend(b"\0" * (-len(result) % 4))
        result.extend(payload)
        result.extend(b"\0" * (-len(result) % 4))
    # Preserve existing zero padding without inventing host filesystem metadata.
    result.extend(data[sum(len(r[3]) for r in records) :])
    return bytes(result)


def public_key(data):
    require(
        len(data.splitlines()) == 1 and not data.startswith(b"-----"), "Use one ADB PUBLIC key line"
    )
    try:
        token = data.split()[0]
        raw = base64.b64decode(token, validate=True)
    except (ValueError, IndexError) as exc:
        raise ValueError("Invalid ADB public key") from exc
    require(
        len(raw) == 524 and struct.unpack_from("<I", raw)[0] == 64,
        "Expected Android RSA2048 public key",
    )
    return token + b" u30-local\n"


def usb_binding(bus, ports):
    require(
        re.fullmatch(r"[0-9]{1,3}", bus) is not None and 0 <= int(bus) <= 255, "Invalid USB bus"
    )
    require(
        re.fullmatch(r"[0-9]{1,3}(\.[0-9]{1,3}){0,7}", ports) is not None,
        "Invalid physical port path",
    )
    require(all(1 <= int(p) <= 255 for p in ports.split(".")), "Invalid port number")
    return bus, ports


def validate_profile(profile):
    require(
        profile.get("target") in ("trustos_b", "init_boot_b"),
        "Only trustos_b/init_boot_b may be written",
    )
    require(profile.get("sizes") == PARTS, "Wrong critical partition sizes")
    require(profile.get("size") == PARTS[profile["target"]], "Wrong candidate length")
    for phase in ("before", "after"):
        require(set(profile.get(phase, {})) == set(PARTS), "Six hashes required")
        require(
            all(re.fullmatch("[0-9a-f]{64}", h) for h in profile[phase].values()), "Malformed hash"
        )
    require(
        profile.get("candidate_sha256") == profile["after"][profile["target"]],
        "Candidate/after mismatch",
    )
    require(
        [n for n in PARTS if profile["before"][n] != profile["after"][n]] == [profile["target"]],
        "Exactly one partition must change",
    )
    require(Path(profile["candidate"]).is_absolute(), "Candidate path must be absolute")
    usb_binding(str(profile["usb_bus"]), profile["usb_ports"])
    return profile


def verify_set(directory, expected, sizes=PARTS):
    for name, digest in expected.items():
        path = Path(directory) / (name + ".bin")
        require(path.is_file() and not path.is_symlink(), f"Missing/unsafe {name}")
        require(
            path.stat().st_size == sizes[name] and sha(path) == digest,
            f"Size/hash mismatch: {name}",
        )


def checked_package(package):
    lock = json.loads((ROOT / "sources.lock.json").read_text())
    for relative, expected in lock["package_files"].items():
        path = Path(package) / relative
        require(path.is_file() and sha(path) == expected, f"Upstream file differs: {relative}")
    return lock


def private_directory(path):
    path = Path(path).expanduser().resolve()
    require(
        path != ROOT and ROOT not in path.parents, "Device work must be outside this repository"
    )
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def active_b(misc):
    require(len(misc) == PARTS["misc"], "Wrong misc length")
    control = misc[2048:2080]
    require(control[:4].rstrip(b"\0") == b"_b", "Only active slot B is supported")
    require(
        struct.unpack_from("<I", control, 4)[0] == 0x42414342 and control[8] == 1,
        "Invalid bootloader_control magic/version",
    )
    require(control[9] & 7 == 2, "Expected two slots")
    require(
        zlib.crc32(control[:28]) == struct.unpack_from("<I", control, 28)[0],
        "Invalid boot metadata CRC",
    )
    require(control[14] & 15 and not (control[15] & 1), "Slot B not eligible for boot")
    require(control[14] & 0xF0, "Slot B has no successful boot or remaining tries")
    return {
        "suffix": "_b",
        "priority": control[14] & 15,
        "tries_remaining": (control[14] >> 4) & 7,
        "successful_boot": bool(control[14] & 128),
    }
