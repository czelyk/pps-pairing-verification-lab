# PPS Pairing Verification Lab

Which timestamp should a spacecraft time client use to reject a delayed time message when the one-pulse-per-second (PPS) signal travels on a separate path?

This pilot measures timing over a local pipe between two Windows processes. A software pulse schedule provides the reference. Both C policies replay the same trace. One checks arrival phase and accepts at most one reference per pulse. The other also checks the message's measured age. The project is a candidate for spacecraft software verification research.

## Run the pilot

Use Python 3.12 and Zig 0.14.1. The scripts use the Python standard library. A run takes about 25 seconds at the default sample count. Pass an existing local Zig executable and a fresh output path.

```powershell
$zig = (Get-Command zig -ErrorAction Stop).Source
python -B run_probe.py --zig $zig --output runs/host-check
python -B verify_trace.py runs/host-check
python -B check_source_latency.py --zig $zig --output runs/source-latency-check.json
```

To audit the archived capture without Zig, run `python -B verify_trace.py results/host-ipc-pilot`.

- [Results, method and next decision](RESULTS.md)
- [Raw timestamps and C decisions](results/host-ipc-pilot/trace.csv)
- [Run summary and source hashes](results/host-ipc-pilot/summary.json)
- [Source-delay control](results/source-latency-control.json)
- [TCP reconnect follow-up and raw trace](TCP-RECONNECT.md)
- [Integrated NASA cFS SBN restart measurements](cfs-sbn/README.md)
- [Native SBN TCP versus UDP restart comparison](cfs-sbn/TCP.md)

NASA documents split timing paths in [THEMIS](https://spdf.gsfc.nasa.gov/pub/data/themis/documents/tdas/docs/thm_soc_135_time_conventions.pdf) and explains the timing services in [cFS training](https://ntrs.nasa.gov/citations/20210022378). The [VarCORE+ evaluation](https://par.nsf.gov/servlets/purl/10515502) studies consistency across cFE TIME configurations. Age limits are established practice in [chrony's reference-clock configuration](https://chrony-project.org/doc/latest/chrony.conf.html#refclock). Study scope and measurement decisions are in the results.

This fixture uses its own C implementation and an ideal software pulse grid on a shared monotonic host clock. Flight hardware, independent oscillators and an integrated cFE transport are outside the measured setup.
