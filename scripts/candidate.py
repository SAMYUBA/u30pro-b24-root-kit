"""Local-only adapter for pinned, separately obtained upstream inputs."""

import importlib.util
import re
import secrets
import struct
import subprocess
import sys
from pathlib import Path

from core import (
    ROOT,
    checked_package,
    cpio_entries,
    private_directory,
    public_key,
    replace_cpio,
    require,
    save,
    sha,
)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load pinned local upstream module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def image_from_ramdisk(stock, compressed):
    require(stock[:8] == b"ANDROID!" and len(stock) == 8388608, "Wrong init_boot image")
    require(struct.unpack_from("<I", stock, 40)[0] == 4, "Expected boot header v4")
    require(
        struct.unpack_from("<I", stock, 8)[0] == 0
        and struct.unpack_from("<I", stock, 1580)[0] == 0,
        "Only kernel-free unsigned boot-v4 body supported",
    )
    footer = bytearray(stock[-64:])
    require(footer[:4] == b"AVBf", "Missing AVB footer")
    old_offset, length = struct.unpack_from(">QQ", footer, 20)
    require(old_offset + length <= len(stock) - 64 and length > 256, "Invalid vbmeta bounds")
    vbmeta = stock[old_offset : old_offset + length]
    offset = (4096 + len(compressed) + 4095) & ~4095
    require(offset + length <= len(stock) - 64, "Ramdisk too large")
    output = bytearray(len(stock))
    output[:4096] = stock[:4096]
    struct.pack_into("<I", output, 12, len(compressed))
    output[4096 : 4096 + len(compressed)] = compressed
    output[offset : offset + length] = vbmeta
    struct.pack_into(">QQ", footer, 12, offset, offset)
    output[-64:] = footer
    return bytes(output)


def build(package, backup, destination, key_path, serial, lz4="lz4", observer=False):
    lock = checked_package(package)
    package, backup = Path(package).resolve(), Path(backup).resolve()
    out = private_directory(destination)
    require(not any(out.iterdir()), "Candidate directory must be empty")
    require(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", serial) is not None, "Unsafe serial")
    key = public_key(Path(key_path).read_bytes())
    for name, record in lock["public_stock"].items():
        p = backup / (name + ".bin")
        require(
            p.is_file() and p.stat().st_size == record["bytes"] and sha(p) == record["sha256"],
            f"{name} does not match supported public stock",
        )
    assets = package / "assets/continuation"
    # Verified external Python imports execute only after the entire input allowlist matches.
    sys.path.insert(0, str(assets))
    verifier = load("upstream_avb_verify", assets / "verify_avb_b.py")
    builder = load("upstream_cpio_reader", assets / "Build-MagiskInitBoot.py")
    trust = load(
        "upstream_trust_builder",
        package / "assets/diagnostics/offline_candidates/Build-BSlotTrustOsCandidate.py",
    )
    trust.INPUT = backup
    prefix = trust.build()
    stock_trust = (backup / "trustos_b.bin").read_bytes()
    trust_image = prefix + stock_trust[len(prefix) :]
    trust_path = out / "trustos_b.bin"
    trust_path.write_bytes(trust_image)
    require(sha(trust_path) == lock["trustos_candidate_sha256"], "TrustOS output mismatch")
    postrom = load("upstream_postrom", assets / "Verify-PostromCandidate.py")
    spl = (backup / "splloader.bin").read_bytes()
    fields = postrom.fields(spl)
    cert = spl[fields["cert_offset"] : fields["cert_offset"] + fields["cert_size"]]
    require(
        postrom.pss_valid(cert) and postrom.verify_selected_cert(trust_image, cert[0x22C:0x24C]),
        "TrustOS certificate verification failed",
    )

    stock = (backup / "init_boot_b.bin").read_bytes()
    reference = (
        assets
        / "magisk_metadata_fix_20261001/init_boot_b_MAGISK_30_7_PRESERVED_VBMETA_UNVERIFIED.bin"
    ).read_bytes()
    compressed = reference[4096 : 4096 + struct.unpack_from("<I", reference, 12)[0]]
    require(
        image_from_ramdisk(stock, compressed) == reference,
        "Historical reconstruction is not byte exact",
    )
    template = (assets / "magisk_preparation_20261001/patched_work/ramdisk.cpio").read_bytes()
    require(builder.legacy_lz4(compressed) == template, "Historical ramdisk mismatch")
    before = cpio_entries(template)
    stock_cpio = builder.legacy_lz4(stock[4096 : 4096 + struct.unpack_from("<I", stock, 12)[0]])
    for name, (fields, data) in cpio_entries(stock_cpio).items():
        if name == "init":
            continue
        require(
            name in before
            and before[name][1] == data
            and all(before[name][0][i] == fields[i] for i in (1, 2, 3, 9, 10)),
            f"Stock ramdisk content/metadata changed: {name}",
        )
    helper = (ROOT / "assets/root_setup.sh.in").read_text().replace("@SERIAL@", serial).encode()
    rc = (ROOT / "assets/root_setup.rc").read_bytes()
    if observer:
        token = secrets.token_hex(24)
        prefix = (ROOT / "assets/observe.sh.in").read_text().replace("@TOKEN@", token).encode()
        helper = prefix + b"\n" + helper.split(b"\n", 1)[1]
        rc += b"\non boot\n    exec_background u:r:magisk:s0 root root -- /system/bin/sh /debug_ramdisk/u30_root_setup.sh --observe\n"
        (out / "u30-diag-enable.txt").write_text(token + "\n")
    replacements = {
        "overlay.d/sbin/u30_host_adb.pub": key,
        "overlay.d/sbin/u30_root_setup.sh": helper,
        "overlay.d/u30_root_setup.rc": rc,
    }
    modified = replace_cpio(template, replacements)
    after = cpio_entries(modified)
    require(set(after) == set(before), "Unexpected CPIO entry change")
    for name in before:
        if name not in replacements:
            require(before[name] == after[name], "Unexpected ramdisk mutation")
    (out / "ramdisk.cpio").write_bytes(modified)
    subprocess.run(
        [lz4, "-f", "-l", "-9", str(out / "ramdisk.cpio"), str(out / "ramdisk.lz4")],
        check=True,
        capture_output=True,
    )
    compressed = (out / "ramdisk.lz4").read_bytes()
    require(builder.legacy_lz4(compressed) == modified, "LZ4 roundtrip mismatch")
    image = image_from_ramdisk(stock, compressed)
    image_path = out / "init_boot_b.bin"
    image_path.write_bytes(image)
    header, descriptors, blob, key_blob = verifier.read_vbmeta(image_path)
    _, _, original_blob, original_key = verifier.read_vbmeta(backup / "init_boot_b.bin")
    require(
        blob == original_blob
        and key_blob == original_key
        and verifier.verify_signature(header, blob),
        "OEM metadata not preserved",
    )
    parent, chains, parent_blob, _ = verifier.read_vbmeta(backup / "vbmeta_b.bin")
    require(verifier.verify_signature(parent, parent_blob), "Invalid parent signature")
    import avbtool

    chain = next(
        d
        for d in chains
        if isinstance(d, avbtool.AvbChainPartitionDescriptor) and d.partition_name == "init_boot"
    )
    require(chain.public_key == key_blob, "Parent/child key mismatch")
    report = {
        "status": "OFFLINE_VALIDATED_NOT_HARDWARE_TESTED",
        "serial": serial,
        "firmware": "U30ProV1.0.0B24",
        "hardware": "U30ProHW1.0",
        "model": "MU5358",
        "files": {
            p.name: {"sha256": sha(p), "bytes": p.stat().st_size} for p in (trust_path, image_path)
        },
        "oem_vbmeta_preserved": True,
        "modified_body_oem_signature_valid": False,
        "requires_trustos_bypass": True,
        "private_work": True,
        "finite_observer_enabled": observer,
        "original_stock_directory": str(backup),
        "helper_sha256": sha(ROOT / "assets/root_setup.sh.in"),
        "limitations": "Generalized helper is not byte-identical to the single-device field image. Offline checks are not a new hardware trial.",
    }
    save(out / "candidate.json", report)
    return report
