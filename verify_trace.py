"""Check the capture and replay against the intended pulse and policy contracts."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
POLICIES = ("phase_only", "source_age_guard")
STATUSES = ("accepted", "already_matched", "expired", "outside_window")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_decision(last, pulse, elapsed, limit, expired):
    if elapsed > limit:
        return "outside_window"
    if expired:
        return "expired"
    return "already_matched" if pulse <= last else "accepted"


def verify_scenario(name, rows, config):
    period = config["period_ns"]
    max_window = config["window_ns"]
    age_limit = config["max_age_ns"]
    pause_index = config["paused_read"]
    first_pulse = int(rows[0]["scheduled_pulse_ns"])
    release = first_pulse + period * (pause_index + 1) + config["release_phase_ns"]
    last_pulse = {policy: -1 for policy in POLICIES}
    first_good_after_release = dict.fromkeys(POLICIES)
    counts = {
        policy: {status: 0 for status in (*STATUSES[1:], "wrong", "correct")}
        for policy in POLICIES
    }
    ages_ms = []
    previous_received = -1

    for origin, row in enumerate(rows):
        pulse_time = int(row["scheduled_pulse_ns"])
        sent = int(row["send_ns"])
        received = int(row["receive_ns"])
        require(int(row["source_pulse"]) == origin, "Unexpected source-pulse order")
        require(pulse_time == first_pulse + origin * period, "Inconsistent pulse epoch")
        require(received >= sent >= pulse_time and received >= previous_received,
                "Invalid timestamp ordering")
        previous_received = received
        age = received - sent
        require(age == int(row["age_ns"]), "Age differs from raw timestamps")
        require(sent - pulse_time == int(row["source_offset_ns"]), "Incorrect source offset")
        pulse, phase = divmod(received - first_pulse, period)
        require((pulse, phase) == (int(row["latest_pulse"]), int(row["phase_ns"])),
                "Receiver phase differs from clock reference")
        ages_ms.append(age / 1_000_000)

        for policy in POLICIES:
            expired = policy == "source_age_guard" and age > age_limit
            expected = expected_decision(last_pulse[policy], pulse, phase, max_window, expired)
            require(expected == row[policy], f"Unexpected {policy} result for {name} pulse {origin}")
            if expected == "accepted":
                last_pulse[policy] = pulse
                counts[policy]["correct" if pulse == origin else "wrong"] += 1
                if received >= release and pulse == origin and first_good_after_release[policy] is None:
                    first_good_after_release[policy] = (received - release) / 1_000_000
            else:
                counts[policy][expected] += 1

    report = config[name]
    require(report["packets"] == len(rows), "Summary packet count differs")
    require(report["age_ms_median"] == statistics.median(ages_ms), "Wrong median")
    require(report["age_ms_max"] == max(ages_ms), "Wrong maximum")
    for policy in POLICIES:
        if name == "controlled_pause":
            counts[policy]["first_correct_after_release_ms"] = first_good_after_release[policy]
        require(report[policy] == counts[policy], f"Summary differs for {policy}")

    if name == "nominal":
        require(all(counts[policy]["correct"] == len(rows) for policy in POLICIES),
                "Nominal control missed a correct update")
    else:
        require(int(rows[pause_index]["receive_ns"]) >= release, "Pause was not enforced")
        require(counts["phase_only"]["wrong"] == 1, "Pause failed to exercise the wrong-period control")
        require(counts["source_age_guard"]["wrong"] == 0 and counts["source_age_guard"]["expired"] == 1,
                "Age guard failed the positive control")
        require(counts["source_age_guard"]["correct"] == len(rows) - 1,
                "Age guard dropped an extra update")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    summary = json.loads((args.directory / "summary.json").read_text(encoding="utf-8"))
    for basename, digest in summary["sha256"].items():
        require(hashlib.sha256((ROOT / basename).read_bytes()).hexdigest() == digest,
                f"Source differs from measurement version: {basename}")
    with (args.directory / "trace.csv").open(newline="", encoding="utf-8") as source:
        all_rows = list(csv.DictReader(source))
    for name in ("nominal", "controlled_pause"):
        selected = [row for row in all_rows if row["scenario"] == name]
        require(bool(selected), f"No observations for {name}")
        verify_scenario(name, selected, summary)
    require(
        len(all_rows) == summary["nominal"]["packets"] + summary["controlled_pause"]["packets"],
        "Unexpected trace scenario",
    )
    print(f"Verified {len(all_rows)} observations and {len(all_rows) * len(POLICIES)} policy decisions.")


if __name__ == "__main__":
    main()
