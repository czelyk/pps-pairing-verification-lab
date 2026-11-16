# TCP reconnect follow-up

[Issue #1](https://github.com/czelyk/pps-pairing-verification-lab/issues/1) · [Raw observations and replay decisions](results/tcp-reconnect.json)

This experiment uses TCP on Windows loopback and application timestamps on one shared monotonic clock. Each of three runs produces eight messages on a one-second software pulse grid. The two reconnect runs close the original connection before pulse 3 publishes and schedule a reconnect 90 ms after pulse 4. The publisher holds actual generated messages in its application queue during the outage. Latest-only sends the newest queued message. FIFO sends both in source order. The new connection does not preserve state from the old connection in this fixture.

The collector measures application publication, the call to send and read completion separately. The wire-age column means elapsed time between the last two markers. It includes socket and thread scheduling. The publication-age column includes the publisher's queue. Both C comparisons use the same recorded receiver times, the original 200 ms phase window and the 500 ms age cutoff. The pulse index assigned at generation is the correctness oracle. The receiver clock and origin timestamps share the same host time base.

| Run | Published / received | Correct using phase alone | Correct using wire age | Correct using publication age |
|---|---:|---:|---:|---:|
| Nominal | 8 / 8 | 8 | 8 | 8 |
| Reconnect, latest-only | 8 / 7 | 7 | 7 | 7 |
| Reconnect, FIFO | 8 / 8 | 6 | 6 | 7 |

Latest-only omitted pulse 3 before sending. Under FIFO, phase-only and wire-age policies each associated pulse 3's message with pulse 4. Their duplicate protection then discarded pulse 4's own message. The old message's measured wire age was 0.0710 ms and its publication age was 1071.1661 ms. The publication-age check expired the old message and accepted the fresh one. It therefore preserved the same seven correct updates as latest-only, with the old message delivered and explicitly rejected.

## Reproduce and audit

~~~powershell
$zig = (Get-Command zig -ErrorAction Stop).Source
python -B tcp_recovery.py runs/tcp-reconnect.json --zig $zig
python -B tcp_recovery.py runs/tcp-reconnect.json --verify
~~~

The verifier reconstructs all 69 C decisions from the timestamps and checks the reconnect boundary, sequence, intended omission and oracle result. The archived run contains the raw observations and the source hash for the C policies.

## Decision

Keep this as a pilot. The test moves from a held reader to a real local connection reopening with two explicit publisher policies. It establishes the result for one scripted reconnect phase and one backlog size. Neither the nominal latency nor the 90 ms reconnect phase represents flight demand or a probability of occurrence. The two policies that avoid a bad pairing both lose the unavailable pulse 3 update. The earlier source-delay control still applies to age measured from publication.

The next deciding experiment needs an integrated flight-software transport with a documented recovery path and separately observed pulse origin. Observe its native backlog behavior across recovery before introducing controlled delivery delays. If it already discards pending messages or enforces age from the pulse at no measurable availability cost, the current research claim adds little.
