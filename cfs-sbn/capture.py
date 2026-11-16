"""Capture ordinary publications and deliveries around a local cFS peer restart."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import socket
import struct
import subprocess
from threading import Thread
import time

STAGE = Path("/cfs/build/exe")
MARKER = re.compile(r"PPS_(PUBLISHED|RECEIVED) (\d+) (-?\d+)")
FIB_CMD = 0x1882


def command(mid, port, code=0, payload=b""):
    wire = struct.pack(">HHHBB", mid, 0, len(payload) + 1, code, 0) + payload
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(wire, ("127.0.0.1", port))


def launch(cpu, instance, records, logs):
    directory = STAGE / f"cpu{cpu}"
    process = subprocess.Popen(
        ["stdbuf", "-oL", "-eL", f"./core-cpu{cpu}", "-R", "PO"], cwd=directory,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )

    def collect():
        with process.stdout:
            for line in process.stdout:
                now = time.monotonic_ns()
                logs.append({"cpu": cpu, "instance": instance, "ns": now, "line": line.rstrip()})
                if match := MARKER.search(line):
                    kind, value, status = match.groups()
                    records.append({"cpu": cpu, "instance": instance, "ns": now,
                                    "kind": kind.lower(), "value": int(value), "status": int(status)})

    thread = Thread(target=collect)
    thread.start()
    return process, thread


def stop(process, thread):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
    thread.join(3)
    if thread.is_alive():
        raise RuntimeError("cFS console collector did not close")


def run(offline_messages, command_port):
    records, logs, actions = [], [], []
    processes = {}
    try:
        for cpu in (1, 2, 3):
            processes[cpu] = launch(cpu, 1, records, logs)
            time.sleep(1)
        time.sleep(8)
        for phase, count in (("before", 4), ("offline", offline_messages), ("restart", 12)):
            if phase == "offline":
                stop(*processes.pop(3))
                actions.append({"phase": "receiver_stopped", "ns": time.monotonic_ns()})
            if phase == "restart":
                actions.append({"phase": "receiver_launch", "ns": time.monotonic_ns()})
                processes[3] = launch(3, 2, records, logs)
            for attempt in range(count):
                actions.append({"phase": phase, "command": attempt, "ns": time.monotonic_ns()})
                command(FIB_CMD, command_port)
                time.sleep(1.05)
        time.sleep(1)
    finally:
        for item in processes.values():
            stop(*item)
    return {"records": sorted(records, key=lambda r: r["ns"]),
            "actions": actions, "logs": sorted(logs, key=lambda r: r["ns"])}


def summarize(report):
    transitions = {r["phase"]: r["ns"] for r in report["actions"] if "command" not in r}
    a, b = transitions["receiver_stopped"], transitions["receiver_launch"]
    records = report["records"]
    decoded = []
    for entry in report["logs"]:
        if match := MARKER.search(entry["line"]):
            kind, value, status = match.groups()
            decoded.append({"cpu": entry["cpu"], "instance": entry["instance"], "ns": entry["ns"],
                            "kind": kind.lower(), "value": int(value), "status": int(status)})
    if records != decoded:
        raise ValueError("Decoded observations differ from the raw console")
    produced = [r for r in records if r["cpu"] == 2 and r["kind"] == "published"]
    delivered = [r for r in records if r["cpu"] == 3 and r["kind"] == "received"]
    if any(r["status"] for r in produced + delivered):
        raise ValueError("At least one observed cFE Software Bus operation reported an error")
    grouped = {
        name: [r["value"] for r in produced if start <= r["ns"] < end]
        for name, start, end in (("before", 0, a), ("offline", a, b), ("restart", b, float("inf")))
    }
    before = [r["value"] for r in delivered if r["instance"] == 1]
    after = [r["value"] for r in delivered if r["instance"] == 2]
    if not before or not grouped["offline"] or not after:
        raise ValueError(f"Missing decisive observation, source={grouped}, sink={before, after}")
    if Counter(before) - Counter(grouped["before"]):
        raise ValueError("Pre-restart output did not match a source publication")
    if Counter(after) - Counter(grouped["offline"] + grouped["restart"]):
        raise ValueError("Post-restart output did not match a source publication")
    return {"produced": grouped, "received_before": before, "received_after": after,
            "replayed_after_restart": [v for v in after if v in grouped["offline"]],
            "first_after_restart_ms": (next(r["ns"] for r in delivered if r["instance"] == 2) - b) / 1e6}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--offline-messages", type=int, choices=(4, 14), default=4)
    parser.add_argument("--command-port", type=int, default=1234)
    args = parser.parse_args()
    if args.verify:
        report = json.loads(args.output.read_text())
        if report["summary"] != summarize(report):
            raise ValueError("Archived summary differs from the captured records")
        print("Verified matching message identities across three phases.")
        return
    target = args.output
    with target.open("x") as output:
        report = run(args.offline_messages, args.command_port)
        report["command_port"] = args.command_port
        try:
            report["summary"] = summarize(report)
        finally:
            json.dump(report, output, indent=2)
            output.write("\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
