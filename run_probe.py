"""Measure local IPC, then replay that exact trace through two C policies."""

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from multiprocessing import get_context
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

NS_PER_MS = 1_000_000
PERIOD = 1000 * NS_PER_MS
SEND_OFFSET = 20 * NS_PER_MS
WINDOW = 200 * NS_PER_MS
MAX_AGE = 500 * NS_PER_MS
PAUSED_READ = 3
RELEASE_PHASE = 90 * NS_PER_MS
ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Observation:
    origin_pulse: int
    send_ns: int
    receive_ns: int
    zero_ns: int

    @property
    def replay_input(self):
        pulse, phase = divmod(self.receive_ns - self.zero_ns, PERIOD)
        return pulse, phase, self.receive_ns - self.send_ns


def sleep_until(deadline):
    remaining = deadline - time.perf_counter_ns()
    while remaining > 0:
        time.sleep(remaining / 1_000_000_000)
        remaining = deadline - time.perf_counter_ns()


def receiver(inbox, outbox, samples, paused):
    with inbox, outbox:
        outbox.send("ready")
        zero = inbox.recv()
        for read in range(samples):
            if paused and read == PAUSED_READ:
                sleep_until(zero + (PAUSED_READ + 1) * PERIOD + RELEASE_PHASE)
            packet = inbox.recv_bytes(16)
            received = time.perf_counter_ns()
            # Capture completed-read time before decoding the message.
            origin = int.from_bytes(packet[:8], "big")
            sent = int.from_bytes(packet[8:], "big")
            outbox.send((origin, sent, received, zero))


def receive(connection, seconds):
    if not connection.poll(seconds):
        raise TimeoutError("Receiver did not report within the probe timeout")
    return connection.recv()


def capture(samples, paused):
    context = get_context("spawn")
    inbox, sender = context.Pipe(duplex=False)
    result, outbox = context.Pipe(duplex=False)
    worker = context.Process(target=receiver, args=(inbox, outbox, samples, paused))
    worker.start()
    inbox.close()
    outbox.close()
    try:
        with sender, result:
            if receive(result, 5) != "ready":
                raise RuntimeError("Invalid receiver handshake")
            zero = time.perf_counter_ns() + 100 * NS_PER_MS
            sender.send(zero)

            for index in range(samples):
                sleep_until(zero + index * PERIOD + SEND_OFFSET)
                prefix = index.to_bytes(8, "big")
                sent = time.perf_counter_ns()
                sender.send_bytes(prefix + sent.to_bytes(8, "big"))

            observations = [Observation(*receive(result, 5)) for _ in range(samples)]
        worker.join(5)
        if worker.exitcode != 0:
            raise RuntimeError(f"Receiver exit status {worker.exitcode}")
        return observations
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        worker.close()


def replay(binary, rows):
    lines = [f"{WINDOW} {MAX_AGE}"]
    lines.extend(f"{pulse} {phase} {age}" for pulse, phase, age in rows)
    result = subprocess.run(
        [binary], input="\n".join(lines) + "\n",
        text=True, capture_output=True, check=True,
    )
    decisions = [tuple(line.split()) for line in result.stdout.splitlines()]
    if len(decisions) != len(rows) or any(len(row) != 2 for row in decisions):
        raise ValueError(f"Unexpected C output: {result.stdout!r}")
    return decisions


def check_boundaries(binary):
    vectors = [
        (0, WINDOW, MAX_AGE),
        (0, 0, 0),
        (1, WINDOW + 1, 0),
        (2, 0, MAX_AGE + 1),
        (2, 0, 0),
        (1, 0, 0),
    ]
    expected = [
        ("accepted", "accepted"),
        ("already_matched", "already_matched"),
        ("outside_window", "outside_window"),
        ("accepted", "expired"),
        ("already_matched", "accepted"),
        ("already_matched", "already_matched"),
    ]
    actual = replay(binary, vectors)
    if actual != expected:
        raise RuntimeError(f"C decisions {actual} differ from boundary vectors {expected}")
    return len(vectors)


def audited_rows(binary, scenario, observations):
    decisions = replay(binary, [row.replay_input for row in observations])
    rows = []
    for row, (baseline, guard) in zip(observations, decisions, strict=True):
        pulse, phase, age = row.replay_input
        if age < 0:
            raise RuntimeError("Sender and receiver timestamps do not share a time base")
        rows.append({
            "scenario": scenario,
            "source_pulse": row.origin_pulse,
            "scheduled_pulse_ns": row.zero_ns + row.origin_pulse * PERIOD,
            "send_ns": row.send_ns,
            "receive_ns": row.receive_ns,
            "source_offset_ns": row.send_ns - row.zero_ns - row.origin_pulse * PERIOD,
            "latest_pulse": pulse,
            "phase_ns": phase,
            "age_ns": age,
            "phase_only": baseline,
            "source_age_guard": guard,
        })
    return rows


def describe(rows, include_pause):
    ages_ms = [row["age_ns"] / NS_PER_MS for row in rows]
    report = {
        "packets": len(rows),
        "age_ms_median": statistics.median(ages_ms),
        "age_ms_max": max(ages_ms),
    }
    for policy in ("phase_only", "source_age_guard"):
        reference = [
            row for row in rows
            if row[policy] == "accepted"
        ]
        report[policy] = {
            "correct": sum(row["source_pulse"] == row["latest_pulse"] for row in reference),
            "wrong": sum(row["source_pulse"] != row["latest_pulse"] for row in reference),
            "expired": sum(row[policy] == "expired" for row in rows),
            "already_matched": sum(row[policy] == "already_matched" for row in rows),
            "outside_window": sum(row[policy] == "outside_window" for row in rows),
        }
        if include_pause:
            release = rows[0]["scheduled_pulse_ns"] + (PAUSED_READ + 1) * PERIOD + RELEASE_PHASE
            recovered = [
                row for row in reference
                if row["receive_ns"] >= release and row["source_pulse"] == row["latest_pulse"]
            ]
            report[policy]["first_correct_after_release_ms"] = (
                (recovered[0]["receive_ns"] - release) / NS_PER_MS if recovered else None
            )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", required=True, type=Path, help="Path to local Zig 0.14.1")
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--samples", default=12, type=int, choices=range(6, 31), metavar="6..30")
    args = parser.parse_args()
    zig = args.zig.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2"]
    with tempfile.TemporaryDirectory(prefix="pps-pairing-") as scratch:
        binary = str(Path(scratch) / ("pairing.exe" if platform.system() == "Windows" else "pairing"))
        subprocess.run([str(zig), *flags, str(ROOT / "pairing.c"), "-o", binary], check=True)
        boundaries = check_boundaries(binary)
        nominal = audited_rows(binary, "nominal", capture(args.samples, paused=False))
        paused = audited_rows(binary, "controlled_pause", capture(args.samples, paused=True))

    with (args.output / "trace.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=nominal[0])
        writer.writeheader()
        writer.writerows(nominal + paused)
    summary = {
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clock": time.get_clock_info("perf_counter").implementation,
        "zig": subprocess.check_output([str(zig), "version"], text=True).strip(),
        "compile_flags": flags,
        "sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("pairing.c", "run_probe.py", "verify_trace.py")
        },
        "period_ns": PERIOD,
        "send_offset_ns": SEND_OFFSET,
        "window_ns": WINDOW,
        "max_age_ns": MAX_AGE,
        "paused_read": PAUSED_READ,
        "release_phase_ns": RELEASE_PHASE,
        "deterministic_boundary_vectors": boundaries,
        "nominal": describe(nominal, include_pause=False),
        "controlled_pause": describe(paused, include_pause=True),
    }
    report = json.dumps(summary, indent=2) + "\n"
    (args.output / "summary.json").write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
