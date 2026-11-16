# Native NASA cFS SBN peer restart

[Issue #2](https://github.com/czelyk/pps-pairing-verification-lab/issues/2)

The container builds three Linux cFS processes using NASA's public SBN UDP example. CPU1 accepts the example's ordinary Fibonacci request, CPU2 publishes the numbered result and CPU3 subscribes to it. Two console markers record successful publication and the receiver-side delivery to the Software Bus. The capture script stops CPU3, leaves the other processes running, continues the same traffic and starts a fresh CPU3. It compares message identities before, during and after the restart.

The sample installer predates the selected cFS bundle's table layout. The preparation script retains the example's three-node topology and the default SBN UDP recovery behavior. It adapts the lab scheduler and telemetry subscription tables to the pinned cFS definitions and adds two observational markers. The run uses Docker's private loopback, Linux x86-64, GCC 14.2.0 and CMake 3.31.6. The cFS bundle and SBN revisions are in the Dockerfile.

## Reproduce

~~~powershell
docker build -t pps-cfs-sbn:pilot cfs-sbn
$root = (Get-Location).Path
New-Item -ItemType Directory -Path runs -Force | Out-Null
docker run --rm --pull never --network none --sysctl fs.mqueue.msg_max=256 --mount "type=bind,source=$root/cfs-sbn,target=/bench,readonly" --mount "type=bind,source=$root/runs,target=/results" pps-cfs-sbn:pilot python3 -B /bench/capture.py /results/sbn-restart.json
python -B cfs-sbn/capture.py --verify runs/sbn-restart.json
~~~

The container sets its own POSIX message-queue limit to 256. The default Docker limit stopped core application initialization during the first attempt.

Console collection times classify phases and describe process-level recovery. A command transmission is not a source publication, so only successful CPU2 Software Bus markers are counted as produced. This trace does not exercise the cFE TIME application, a physical PPS, independent clock domains, a radio link, or the TCP protocol module. The measured interval combines process startup, peer discovery and the cadence of the next sample.

[NASA cFS v7.0.1 bundle](https://github.com/nasa/cFS/tree/088b2fa828db9ff7e00733f1908e0eeb59f66ce3) Â· [Pinned SBN example](https://github.com/nasa/SBN/tree/387f660e9df62beaed51b88e093ceac789300b0d/examples/cFS)
## Measured outcome

| Receiver downtime | Source publications while down | Publications after launch / deliveries | Old publications delivered after launch | First delivery after launch |
|---|---:|---:|---:|---:|
| 4.201 s | 4 | 12 / 11 | 0 | 2.008 s |
| 14.705 s | 14 | 12 / 10 | 0 | 3.004 s |

All four nominal publications were delivered in each run. The longer run recorded an explicit disconnect on the sender at 11.001 s after receiver shutdown and a new connection 1.874 s after relaunch. The short run checks process restart with a shorter outage. Across both runs, the receiver delivered none of the 18 messages published while it was down. The first one or two new publications after launch also did not reach the recorder.

This result weakens the stale-backlog research claim for the public SBN UDP example. The integrated path resumes with fresh observations, while losing availability during recovery. The earlier local TCP result depended on a publisher that explicitly retained and replayed its queue. A case for continuing the stale-backlog claim needs a documented transport or application that keeps pending time messages across recovery.

[Short outage capture](../results/sbn-restart-short.json) · [Long outage capture](../results/sbn-restart-long.json)
