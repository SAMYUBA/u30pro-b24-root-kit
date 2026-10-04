"""Local interoperability transform. Upstream files are never redistributed.

Input is hash-pinned by native_build.py. Anchors are minimal matching context.
"""


def once(s, a, b):
    if s.count(a) != 1:
        raise ValueError("Adapter anchor mismatch")
    return s.replace(a, b, 1)


def adapt(original, destination):
    s = (original / "common.c").read_text()
    s = once(
        s,
        '#include "common.h"',
        '#include "common.h"\n#include "u30_guard.h"\n#include "u30_usb.h"',
    )
    for signature in [
        "void encode_msg(spdio_t *io, int type, const void *data, size_t len) {",
        "void encode_msg_nocpy(spdio_t *io, int type, size_t len) {",
    ]:
        s = once(
            s,
            signature,
            signature
            + '\n\tif (!u30_wire_allowed(type)) ERR_EXIT("READ_ONLY_POLICY: blocked wire command 0x%x\\n", type);',
        )
    s = once(
        s,
        "unsigned src_offs, unsigned src_size) {",
        'unsigned src_offs, unsigned src_size) {\n\tERR_EXIT("READ_ONLY_POLICY: host file upload disabled\\n");',
    )
    start = s.rindex("void ChangeMode(")
    end = s.index("\nvoid call_Initialize_libusb", start)
    mode = s[start:end]
    a = mode.index("\t\tfor (int i = 0; ; i++) {")
    b = mode.index("\n\t\tuint8_t payload", a)
    mode = (
        mode[:a]
        + """\t\terr = u30_open_target(0, (unsigned)ms, &io->dev_handle);
    \t\tif (err) ERR_EXIT("target USB open failed: %s\\n", libusb_error_name(err));
    \t\tcurPort = libusb_get_device(io->dev_handle);
    \t\tcall_Initialize_libusb(io);
    """
        + mode[b:]
    )
    a = mode.rindex("\t\tfor (int i = 0; ; i++) {")
    b = mode.index("\n\t\tif (!at) done = 1;", a)
    mode = (
        mode[:a]
        + """\t\terr = u30_wait_removed(io->dev_handle, 60000);
    \t\tif (err == LIBUSB_ERROR_TIMEOUT && io->recv_buf[2] == BSL_REP_VER) return;
    \t\tif (err) ERR_EXIT("kick disconnect wait failed: %s; no reset sent\\n", libusb_error_name(err));
    \t\tlibusb_close(io->dev_handle);
    \t\tio->dev_handle = NULL;
    \t\tio->recv_buf[2] = 0;
    \t\tcurPort = NULL;
    \t\tm_bOpened = 0;
    \t\tif (done == -1) done = 1;
    """
        + mode[b:]
    )
    # Bounds are checked before reading response type, checksum or version byte.
    mode = mode.replace(
        "if (io->recv_buf[2] == BSL_REP_VER ||",
        'if (bytes_read < 3) ERR_EXIT("Short mode response\\n");\n\t\t\tif (io->recv_buf[2] == BSL_REP_VER ||',
    )
    mode = mode.replace(
        "int chk1, chk2, a = READ16_BE",
        'if (bytes_read < 7) ERR_EXIT("Short framed mode response\\n");\n\t\t\t\tint chk1, chk2, a = READ16_BE',
    )
    mode = mode.replace(
        "if (io->recv_buf[9] < '4') return;",
        "if (bytes_read < 10) ERR_EXIT(\"Short version response\\n\"); if (io->recv_buf[9] < '4') return;",
    )
    s = s[:start] + mode + s[end:]
    s = once(
        s,
        "\tfclose(fo);\n\n\tencode_msg_nocpy(io, BSL_CMD_READ_END, 0);\n\tsend_and_check(io);\n\treturn offset - start;",
        '\tif (fclose(fo)) ERR_EXIT("Closing dump failed\\n");\n\n\tencode_msg_nocpy(io, BSL_CMD_READ_END, 0);\n\tif (send_and_check(io)) return 0;\n\treturn offset - start;',
    )
    s = once(
        s,
        '\tif (!strcmp(name, "super")) dump_partition(io, "metadata", 0, check_partition(io, "metadata", 1), "metadata.bin", step);\n\telse if (!strncmp(name, "userdata", 8))',
        '\t/* Metadata is an explicit separate read in the backup manifest. */\n\tif (!strncmp(name, "userdata", 8))',
    )
    (destination / "common.c").write_text(s)
    s = (original / "spd_dump.c").read_text()
    s = once(
        s,
        '#include "common.h"',
        '#include "common.h"\n#include "u30_guard.h"\n#include "u30_usb.h"',
    )
    s = once(
        s,
        "int main(int argc, char **argv) {",
        'int main(int argc, char **argv) {\n\tif (!u30_validate_cli(argc, argv)) { fprintf(stderr, "READ_ONLY_POLICY: invalid command sequence\\n"); return 64; }',
    )
    a = s.index("\tif (!libusb_has_capability(")
    b = s.index("\n#endif", a)
    s = (
        s[:a]
        + """\tbListenLibusb = 0; /* Mac variant uses synchronous enumeration only. */
    \tif (at || bootmode >= 0) {
    \t\tChangeMode(io, wait / REOPEN_FREQ * 1000, bootmode, at);
    \t\twait = 30 * REOPEN_FREQ;
    \t\tstage = -1;
    \t}
    """
        + s[b:]
    )
    a = s.index('\tif (!m_bOpened) {\n\t\tDBG_LOG("Waiting for dl_diag')
    b = s.index("\n#endif\n\tio->flags |= FLAGS_TRANSCODE;", a)
    s = (
        s[:a]
        + """\tif (!m_bOpened) {
    \t\tDBG_LOG("Waiting for target dl_diag connection (%ds)\\n", wait / REOPEN_FREQ);
    \t\tret = u30_open_target(0x4d00, (unsigned)(wait / REOPEN_FREQ * 1000), &io->dev_handle);
    \t\tif (ret) ERR_EXIT("target USB open failed: %s\\n", libusb_error_name(ret));
    \t\tcurPort = libusb_get_device(io->dev_handle);
    \t\tcall_Initialize_libusb(io);
    \t}
    """
        + s[b:]
    )
    s = once(
        s,
        "\twhile (1) {\n\t\tif (argc > 1) {",
        "\twhile (1) {\n\t\tint synthetic_stage = 0;\n\t\tif (argc > 1) {",
    )
    s = once(
        s,
        '\t\t\t\tstr2[1] = "loadfdl";',
        '\t\t\t\tsynthetic_stage = 1;\n\t\t\t\tstr2[1] = "loadfdl";',
    )
    s = once(
        s, '\t\t\t\tstr2[1] = "exec";', '\t\t\t\tsynthetic_stage = 2;\n\t\t\t\tstr2[1] = "exec";'
    )
    a = s.index("\t\telse {\n\t\t\tchar ifs")
    b = s.index("\n\t\tif (argcount == 1)", a)
    s = s[:a] + "\t\telse { break; } /* No interactive input, including EOF loops. */\n" + s[b:]
    s = once(
        s,
        '\t\tif (!strcmp(str2[1], "sendloop")) {',
        """\t\tint available = synthetic_stage == 1 ? 2 : synthetic_stage == 2 ? 1 : argcount - 1;
    \t\tif (!u30_command_arity(available, str2 + 1, synthetic_stage == 1, fdl1_loaded, fdl2_executed))
    \t\t\tERR_EXIT("READ_ONLY_POLICY: dispatch rejected\\n");
    \t\tif (!strcmp(str2[1], "sendloop")) {""",
    )
    s = once(
        s,
        '\t\t\t\t\t\tencode_msg_nocpy(io, BSL_CMD_ENABLE_RAW_DATA, 0);\n\t\t\t\t\t\tif (!send_and_check(io)) DBG_LOG("ENABLE_WRITE_RAW_DATA\\n");',
        '\t\t\t\t\t\tDa_Info.bSupportRawData = 0;\n\t\t\t\t\t\tDBG_LOG("READ_ONLY_POLICY: raw write mode disabled\\n");',
    )
    s = once(
        s,
        '\t\t\tif (!gPartInfo.size) { DBG_LOG("part not exist\\n"); argc -= 5; argv += 5; continue; }',
        '\t\t\tif (!gPartInfo.size) ERR_EXIT("Read target partition not found\\n");',
    )
    s = once(
        s,
        "\t\t\tdump_partition(io, gPartInfo.name, offset, size, fn, blk_size ? blk_size : DEFAULT_BLK_SIZE);",
        '\t\t\tif (strcmp(name, gPartInfo.name)) ERR_EXIT("Read partition name changed\\n");\n\t\t\tif (dump_partition(io, gPartInfo.name, offset, size, fn, blk_size ? blk_size : DEFAULT_BLK_SIZE) != size) ERR_EXIT("Incomplete partition read; no reset sent\\n");',
    )
    s = once(
        s,
        '\t\tif (!strcmp(str2[1], "sendloop")) {',
        '\t\tif (!strcmp(str2[1], "verify_before") || !strcmp(str2[1], "verify_after")) {\n            u30_verify_set(savepath, !strcmp(str2[1], "verify_after")); argc--; argv++;\n        } else if (!strcmp(str2[1], "write_pinned")) {\n            u30_perform_write(io); argc--; argv++;\n        } else if (!strcmp(str2[1], "sendloop")) {',
    )
    reset_start = s.index('else if (!strcmp(str2[1], "reset"))')
    reset_end = s.index('else if (!strcmp(str2[1], "reboot-recovery"))', reset_start)
    reset = s[reset_start:reset_end]
    reset = once(
        reset,
        "\t\t\tencode_msg_nocpy(io, BSL_CMD_NORMAL_RESET, 0);\n\t\t\tif (!send_and_check(io)) break;",
        '\t\t\tencode_msg_nocpy(io, BSL_CMD_NORMAL_RESET, 0);\n\t\t\tif (send_and_check(io)) ERR_EXIT("TRIAL_RESET_NOT_ACKED; no repeat reset\\n");\n            DBG_LOG("TRIAL_RESET_ACKED\\n");\n            break;',
    )
    s = s[:reset_start] + reset + s[reset_end:]
    (destination / "spd_dump.c").write_text(s)
