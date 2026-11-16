"""Measure PPS message availability and age across loopback TCP reconnects."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import socket
import subprocess
import tempfile
import time

from run_probe import MAX_AGE, NS_PER_MS, PERIOD, ROOT, SEND_OFFSET, WINDOW, replay, sleep_until

SAMPLES = 8
OUTAGE_START = 3
RESUME_PULSE = 4
RESUME_PHASE = 90 * NS_PER_MS
SCENARIOS = ("nominal", "reconnect_latest", "reconnect_fifo")
POLICIES = ("phase_only", "wire_age", "publication_age")


def receive(server, connections):
    rows = []
    for connection in range(connections):
        sock, _ = server.accept()
        with sock, sock.makefile("rb") as stream:
            sock.settimeout(5)
            while line := stream.readline():
                received = time.perf_counter_ns()
                origin, sent = map(int, line.split())
                rows.append({"origin": origin, "wire_send_ns": sent,
                             "received_ns": received, "connection": connection})
    return rows


def connect(address):
    sock = socket.create_connection(address, timeout=5)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def capture(scenario):
    reconnect = scenario != "nominal"
    with socket.socket() as server, ThreadPoolExecutor(max_workers=1) as worker:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(10)
        address = server.getsockname()
        reader = worker.submit(receive, server, 2 if reconnect else 1)
        zero = time.perf_counter_ns() + 100 * NS_PER_MS
        release = zero + RESUME_PULSE * PERIOD + RESUME_PHASE if reconnect else None
        publications = {}
        pending = []
        sock = connect(address)
        try:
            for origin in range(SAMPLES):
                if reconnect and origin == OUTAGE_START:
                    sock.close()
                    sock = None
                sleep_until(zero + origin * PERIOD + SEND_OFFSET)
                publications[origin] = time.perf_counter_ns()
                pending.append(origin)
                if sock is None and origin < RESUME_PULSE:
                    continue
                if sock is None:
                    sleep_until(release)
                    sock = connect(address)
                    if scenario == "reconnect_latest":
                        pending = pending[-1:]
                for queued in pending:
                    sent = time.perf_counter_ns()
                    sock.sendall(f"{queued} {sent}\n".encode("ascii"))
                pending.clear()
        finally:
            if sock is not None:
                sock.close()
        rows = reader.result(timeout=10)
    return {"scenario": scenario, "pulse_zero_ns": zero, "scheduled_reconnect_ns": release,
            "published_ns": list(publications.values()), "received": rows}


def pairing_inputs(capture, from_publication):
    zero = capture["pulse_zero_ns"]
    inputs = []
    for row in capture["received"]:
        received = row["received_ns"]
        pulse, phase = divmod(received - zero, PERIOD)
        source = (capture["published_ns"][row["origin"]] if from_publication
                  else row["wire_send_ns"])
        if received < source:
            raise ValueError("Receipt precedes the selected age reference")
        inputs.append((pulse, phase, received - source))
    return inputs


def evaluate(binary, capture):
    wire_rows = pairing_inputs(capture, from_publication=False)
    publication_rows = pairing_inputs(capture, from_publication=True)
    wire = replay(binary, wire_rows)
    publication = replay(binary, publication_rows)
    for row, wire_result, source_result in zip(capture["received"], wire, publication, strict=True):
        if wire_result[0] != source_result[0]:
            raise ValueError("Phase-only policy changed when its unused age input changed")
        row.update(zip(POLICIES, (*wire_result, source_result[1]), strict=True))


def summarize(capture):
    published = capture["published_ns"]
    received = capture["received"]
    zero = capture["pulse_zero_ns"]
    summary = {
        "published": len(published),
        "received": len(received),
        "omitted_before_wire": sorted(set(range(len(published))) - {r["origin"] for r in received}),
        "max_wire_ms": max(r["received_ns"] - r["wire_send_ns"] for r in received) / NS_PER_MS,
        "max_publication_ms": max(r["received_ns"] - published[r["origin"]] for r in received) / NS_PER_MS,
    }
    for policy in POLICIES:
        right = [r["origin"] for r in received if r[policy] == "accepted"
                 and (r["received_ns"] - zero) // PERIOD == r["origin"]]
        wrong = [r["origin"] for r in received if r[policy] == "accepted" and r["origin"] not in right]
        summary[policy] = {"correct": right, "wrong": wrong,
                           "expired": [r["origin"] for r in received if r[policy] == "expired"]}
    return summary


def verify(report):
    if hashlib.sha256((ROOT / "pairing.c").read_bytes()).hexdigest() != report["pairing_sha256"]:
        raise ValueError("C source differs from the archived measurement")
    if tuple(c["scenario"] for c in report["captures"]) != SCENARIOS:
        raise ValueError("Missing scenarios")
    for capture in report["captures"]:
        scenario = capture["scenario"]
        zero = capture["pulse_zero_ns"]
        published = capture["published_ns"]
        received = capture["received"]
        fifo = scenario == "reconnect_fifo"
        latest = scenario == "reconnect_latest"
        expected_origins = [i for i in range(SAMPLES) if not (latest and i == OUTAGE_START)]
        if [r["origin"] for r in received] != expected_origins or len(published) != SAMPLES:
            raise ValueError(f"Unexpected origin sequence in {scenario}")
        if [r["connection"] for r in received] != [
            int(scenario != "nominal" and i >= OUTAGE_START) for i in expected_origins
        ]:
            raise ValueError(f"Unexpected connection boundaries in {scenario}")

        for policy in POLICIES:
            used_pulses = set()
            for row in received:
                origin = row["origin"]
                sent = row["wire_send_ns"]
                arrived = row["received_ns"]
                if not zero + origin * PERIOD + SEND_OFFSET <= published[origin] <= sent <= arrived:
                    raise ValueError(f"Timestamp order failed in {scenario}")
                actual, phase = divmod(arrived - zero, PERIOD)
                stamp = sent if policy == "wire_age" else published[origin]
                if phase > WINDOW:
                    expected = "outside_window"
                elif policy != "phase_only" and arrived - stamp > MAX_AGE:
                    expected = "expired"
                elif actual in used_pulses:
                    expected = "already_matched"
                else:
                    expected = "accepted"
                    used_pulses.add(actual)
                if row[policy] != expected:
                    raise ValueError(f"Unexpected {policy} decision for {scenario} pulse {origin}")

        summary = summarize(capture)
        for policy in POLICIES:
            expected_wrong = [OUTAGE_START] if fifo and policy != "publication_age" else []
            expected_right = [i for i in expected_origins
                              if not (fifo and (i == OUTAGE_START or
                                               (i == RESUME_PULSE and policy != "publication_age")))]
            if summary[policy]["correct"] != expected_right or summary[policy]["wrong"] != expected_wrong:
                raise ValueError(f"Run did not exercise the expected control for {scenario}/{policy}")
        if report["summary"][scenario] != summary:
            raise ValueError(f"Summary differs from capture for {scenario}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Evidence JSON")
    parser.add_argument("--zig", type=Path, help="Local Zig executable")
    parser.add_argument("--verify", action="store_true", help="Audit an existing capture")
    args = parser.parse_args()
    if args.verify:
        verify(json.loads(args.output.read_text(encoding="utf-8")))
        print("Verified three scenarios and 69 C policy decisions.")
        return
    if args.zig is None:
        parser.error("A run requires --zig.")
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2"]
    zig = str(args.zig.resolve(strict=True))
    with tempfile.TemporaryDirectory(prefix="pps-tcp-") as scratch:
        binary = str(Path(scratch) / "pairing.exe")
        subprocess.run([zig, *flags, str(ROOT / "pairing.c"), "-o", binary], check=True)
        captures = []
        for scenario in SCENARIOS:
            observation = capture(scenario)
            evaluate(binary, observation)
            captures.append(observation)
    report = {
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "zig": subprocess.check_output([zig, "version"], text=True).strip(),
        "compile_flags": flags,
        "pairing_sha256": hashlib.sha256((ROOT / "pairing.c").read_bytes()).hexdigest(),
        "period_ns": PERIOD,
        "send_offset_ns": SEND_OFFSET,
        "phase_window_ns": WINDOW,
        "max_age_ns": MAX_AGE,
        "captures": captures,
        "summary": {c["scenario"]: summarize(c) for c in captures},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2)
        target.write("\n")
    verify(report)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
