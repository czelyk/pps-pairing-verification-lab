"""Check that measuring only post-publication age has a known blind spot."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from run_probe import NS_PER_MS, PERIOD, ROOT, replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # One pulse at t=0. The second pulse takes place at t=1 second.
    # Publication is delayed to 950 ms and delivery happens at 1050 ms.
    origin_pulse = 0
    published = 950 * NS_PER_MS
    received = 1050 * NS_PER_MS
    latest, phase = divmod(received, PERIOD)
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2"]

    with tempfile.TemporaryDirectory(prefix="pps-source-latency-") as scratch:
        binary = str(Path(scratch) / "pairing.exe")
        subprocess.run([str(args.zig.resolve(strict=True)), *flags,
                        str(ROOT / "pairing.c"), "-o", binary], check=True)
        from_publication = replay(binary, [(latest, phase, received - published)])[0]
        from_origin_pulse = replay(binary, [(latest, phase, received)])[0]

    if from_publication != ("accepted", "accepted"):
        raise ValueError(f"Expected the publication-age blind spot, got {from_publication}")
    if from_origin_pulse != ("accepted", "expired"):
        raise ValueError(f"Expected the original-pulse-age rejection, got {from_origin_pulse}")

    report = {
        "scope": "Deterministic source-delay control with a shared trusted clock",
        "source_sha256": hashlib.sha256((ROOT / "pairing.c").read_bytes()).hexdigest(),
        "origin_pulse": origin_pulse,
        "latest_pulse": latest,
        "publish_ms": published // NS_PER_MS,
        "receipt_ms": received // NS_PER_MS,
        "age_ms_from_publication": (received - published) // NS_PER_MS,
        "age_ms_from_origin_pulse": received // NS_PER_MS,
        "phase_only": from_publication[0],
        "guard_age_from_publication": from_publication[1],
        "guard_age_from_origin_pulse": from_origin_pulse[1],
    }
    rendered = json.dumps(report, indent=2) + "\n"
    with args.output.open("x", encoding="utf-8") as output:
        output.write(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
