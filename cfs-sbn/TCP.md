# Native SBN TCP restart comparison

[Issue #3](https://github.com/czelyk/pps-pairing-verification-lab/issues/3) ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· [UDP baseline](README.md)

The first TCP runs with the original command route booted each cFE instance and logged peer connections, yet neither run logged a Fibonacci publication. The original demo routes the trigger from CPU1 to CPU2 over SBN. Those runs cannot determine stale delivery.

A follow-up scheduler trigger also produced no Fibonacci markers in either transport. The final comparison moves CI_LAB from CPU1 to CPU2 for both images. Both images use CPU2's configured local UDP ingress port 1235 and stay on CPU2 before the Fibonacci publication, so the only SBN path under comparison is the telemetry path to CPU3. The only difference between the matched images is the SBN configuration table's protocol name and library entry. The containers use separate Linux loopback network namespaces.

The pinned TCP module sends each application message on its current connection. On disconnect it closes the socket and delegates to the common SBN cleanup, which deletes the outgoing peer pipe and clears subscription state. There is no application-level retransmission queue across reconnection in those code paths. TCP reliability while a connection remains open is a different case from restarting a peer. [TCP send](https://github.com/nasa/SBN/blob/387f660e9df62beaed51b88e093ceac789300b0d/modules/protocol/tcp/fsw/src/sbn_tcp_if.c#L355-L379) Â· [TCP disconnect](https://github.com/nasa/SBN/blob/387f660e9df62beaed51b88e093ceac789300b0d/modules/protocol/tcp/fsw/src/sbn_tcp_if.c#L174-L188) ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â· [Common peer cleanup](https://github.com/nasa/SBN/blob/387f660e9df62beaed51b88e093ceac789300b0d/fsw/src/sbn_app.c#L235-L273)

## Reproduce

~~~powershell
docker build --build-arg SBN_PROTOCOL=TCP --build-arg SBN_LOCAL_SOURCE=1 -t pps-cfs-sbn:tcp-local cfs-sbn
docker build --build-arg SBN_PROTOCOL=UDP --build-arg SBN_LOCAL_SOURCE=1 -t pps-cfs-sbn:udp-local cfs-sbn
$root = (Get-Location).Path
New-Item -ItemType Directory -Path runs -Force | Out-Null
docker run --rm --pull never --network none --sysctl fs.mqueue.msg_max=256 --mount "type=bind,source=$root/cfs-sbn,target=/bench,readonly" --mount "type=bind,source=$root/runs,target=/results" pps-cfs-sbn:tcp-local python3 -B /bench/capture.py /results/tcp-short.json --offline-messages 4 --local-source
docker run --rm --pull never --network none --sysctl fs.mqueue.msg_max=256 --mount "type=bind,source=$root/cfs-sbn,target=/bench,readonly" --mount "type=bind,source=$root/runs,target=/results" pps-cfs-sbn:tcp-local python3 -B /bench/capture.py /results/tcp-long.json --offline-messages 14 --local-source
~~~

The pinned UDP configuration remains the default Docker build. Use a fresh file name for each capture. Run the same two commands with the UDP image and change the output names for the matched controls.

## Matched measurements

| SBN module | Downtime (s) | Published during outage | Old messages received after launch | New messages received / published | First new message after launch (s) | Raw capture |
|---|---:|---:|---:|---:|---:|---|
| UDP | 4.201 | 4 | 0 | 10 / 12 | 2.604 | [JSON](../results/sbn-matched-udp-4.json) |
| TCP | 4.201 | 4 | 0 | 10 / 12 | 2.605 | [JSON](../results/sbn-matched-tcp-4.json) |
| UDP | 14.706 | 14 | 0 | 10 / 12 | 2.804 | [JSON](../results/sbn-matched-udp-14.json) |
| TCP | 14.705 | 14 | 0 | 8 / 12 | 4.796 | [JSON](../results/sbn-matched-tcp-14.json) |

All four pre-outage publications reached the receiver in every run. Neither transport replayed an outage publication. Each transport had one run at each outage duration. The observed recovery times include boot, peer discovery and the arrival of the next new publication. The containers ran on a shared desktop. The times do not estimate a transport performance bound.

## Research decision

The public SBN UDP and TCP paths do not demonstrate the stale-backlog mechanism in these process restarts. The earlier TCP pilot needed an application queue that explicitly replayed messages across reconnect. This narrows the claim and argues against choosing this version as the main IAC topic. A further experiment needs an independently documented, representative producer that retains time messages across recovery, or a distinct question about availability with sourced requirements. This test exercised ordinary telemetry in Linux cFS processes and did not include a physical PPS or clock matching.
