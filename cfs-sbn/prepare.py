"""Prepare the NASA sample deployment without changing SBN behavior."""

import os
from pathlib import Path
import subprocess
import shutil

root = Path("/cfs")
upstream = Path("/sbn")
example = upstream / "examples/cFS"
links = {
    "sbn": upstream,
    "sbn_udp": upstream / "modules/protocol/udp",
    "sbn_tcp": upstream / "modules/protocol/tcp",
    "sbn_f_remap": upstream / "modules/filter/remap",
    "fib": example / "apps/fib",
}
for name, target in links.items():
    path = root / "apps" / name
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.move(path, root / (name + "-bundle"))
    path.symlink_to(target, target_is_directory=True)

producer = example / "apps/fib/fsw/src/fib_app.c"
source = producer.read_text()
original = """            CFE_SB_TransmitMsg((CFE_MSG_Message_t *)&tlm, true);"""
replacement = """            int32 publish_status = CFE_SB_TransmitMsg((CFE_MSG_Message_t *)&tlm, true);
            OS_printf("PPS_PUBLISHED %lu %ld\\n", (unsigned long)tlm.fib,
                      (long)publish_status);"""
if source.count(original) != 1:
    raise ValueError("Unexpected pinned Fibonacci publication source")
producer.write_text(source.replace(original, replacement))
sink = upstream / "fsw/src/sbn_app.c"
source = sink.read_text()
original = "            CFE_Status = CFE_SB_TransmitMsg(Msg, false);"
marker = r"""            if (ProcessorID == 2 && CFE_PSP_GetProcessorId() == 3 &&
                MsgSz == sizeof(CFE_MSG_TelemetryHeader_t) + sizeof(uint32))
            {
                CFE_SB_MsgId_t observation_id;
                CFE_MSG_GetMsgId(Msg, &observation_id);
                if (CFE_SB_MsgIdToValue(observation_id) == 0x0882 ||
                    CFE_SB_MsgIdToValue(observation_id) == 0x0883)
                {
                    uint32 observation_value;
                    memcpy(&observation_value, (uint8 *)Msg + sizeof(CFE_MSG_TelemetryHeader_t),
                           sizeof(observation_value));
                    OS_printf("PPS_RECEIVED %lu %ld\n", (unsigned long)observation_value,
                              (long)CFE_Status);
                }
            }"""
if source.count(original) != 1:
    raise ValueError("Unexpected pinned SBN delivery source")
sink.write_text(source.replace(original, original + "\n" + marker))
# The cFS bundle attaches TO table flags to CPU1 and CPU2. The
# SBN example loads TO_LAB on CPU3 only.
for cpu in ("cpu1", "cpu2"):
    (root / "sample_defs" / cpu / "install_custom.cmake").unlink()
env = dict(os.environ, MAKEFLAGS="-j4", MISSIONCONFIG="sample")
installer = example / "install"
layout, marker, _ = installer.read_text().partition('cd ${CFS_ROOT}\nrm -rf build')
if not marker:
    raise ValueError("Unexpected example installer build boundary")
layout_only = example / "layout-only"
layout_only.write_text(layout)
subprocess.run(["bash", str(layout_only), str(root)], cwd=example, env=env, check=True)

protocol = os.environ.get("SBN_PROTOCOL", "UDP")
if protocol not in ("UDP", "TCP"):
    raise ValueError("SBN_PROTOCOL must select UDP or TCP")
table = upstream / "fsw/tables/sbn_conf_tbl.c"
if protocol == "TCP":
    udp_table = table.read_text()
    edits = { '"UDP"': ('"TCP"', 4),
              'sbn_udp.so': ('sbn_tcp.so', 1),
              'SBN_UDP_Ops': ('SBN_TCP_Ops', 1) }
    for declared, (replacement, count) in edits.items():
        if udp_table.count(declared) != count:
            raise ValueError(f"Unexpected example table field {declared}")
        udp_table = udp_table.replace(declared, replacement)
    table.write_text(udp_table)


def original(directory, relative):
    return subprocess.check_output(["git", "show", f"HEAD:{relative}"],
                                   cwd=directory, text=True)

options = root / "sample_defs/global_build_options.cmake"
options.write_text(original(root, "sample_defs/global_build_options.cmake") +
                   "\ninclude_directories(/sbn/examples/cFS/apps/fib/fsw/platform_inc /sbn/fsw/platform_inc /cfs/apps/ci_lab/fsw/inc /cfs/apps/to_lab/fsw/inc /cfs/apps/sch_lab/fsw/inc)\n")
for app in ("to_lab", "sch_lab"):
    directory = root / "apps" / app
    (directory / "CMakeLists.txt").write_text(original(directory, "CMakeLists.txt"))
for app, table in (("to_lab", "to_lab_sub.c"), ("sch_lab", "sch_lab_table.c")):
    directory = root / "apps" / app
    text = original(directory, f"fsw/tables/{table}")
    if app == "to_lab":
        text = '#include "fib_app_msgids.h"\n' + text
        old = "{ CFE_SB_MSGID_RESERVED, { 0, 0 }, 0 }"
        new = ("{ CFE_SB_MSGID_WRAP_VALUE(FIB_TLM_MID), { 0, 0 }, 4 },\n"
               "{ CFE_SB_MSGID_WRAP_VALUE(FIB_TLM_REMAP_MID), { 0, 0 }, 4 },\n" + old)
    else:
        text = '#include "sbn_msgids.h"\n' + text
        old = "{CFE_SB_MSGID_RESERVED, 0, 0}"
        new = "{CFE_SB_MSGID_WRAP_VALUE(SBN_CMD_MID), 10, 0}"
    if text.count(old) != 1:
        raise ValueError(f"Unexpected table template: {table}")
    (root / "sample_defs/tables" / table).write_text(text.replace(old, new))
for startup in (root / "sample_defs").glob("cpu*_cfe_es_startup.scr"):
    startup.write_text(startup.read_text().replace("SCH_LAB_APP,", "SCH_LAB,")
                       .replace("TO_LAB_APP,", "TO_LAB,").replace("CI_LAB_APP,", "CI_LAB,").replace("CI_Lab_AppMain,", "CI_LAB_AppMain,"))
if os.environ.get("SBN_LOCAL_SOURCE") == "1":
    targets = root / "sample_defs/targets.cmake"
    config = targets.read_text()
    config = config.replace("SET(cpu1_APPLIST ci_lab)", "SET(cpu1_APPLIST)")
    config = config.replace("SET(cpu2_APPLIST fib)", "SET(cpu2_APPLIST fib ci_lab)")
    targets.write_text(config)
    cpu1 = root / "sample_defs/cpu1_cfe_es_startup.scr"
    cpu2 = root / "sample_defs/cpu2_cfe_es_startup.scr"
    rows = cpu1.read_text().splitlines(keepends=True)
    ci = [row for row in rows if "CI_LAB_AppMain" in row]
    if len(ci) != 1:
        raise ValueError("Expected exactly one CI Lab startup line")
    cpu1.write_text("".join(row for row in rows if row not in ci))
    cpu2.write_text(ci[0] + cpu2.read_text())
subprocess.run(["make", "SIMULATION=native", "prep"], cwd=root, env=env, check=True)
subprocess.run(["make", "install"], cwd=root, env=env, check=True)
if not (root / "build/exe/cpu3/core-cpu3").is_file():
    raise RuntimeError("NASA example did not stage the receiver executable")
