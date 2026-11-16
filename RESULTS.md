# Host IPC pilot

One Windows capture per scenario, with 12 messages from an independent producer process in each. The collector scheduled one pulse per second and published a message 20 ms after each scheduled pulse. Publication was timed immediately before the pipe write and receipt immediately after the pipe read. Recorded age includes serialization, transport and receiver scheduling between those timestamps. Both policies use the same 200 ms post-pulse window, the same deduplication rule and the same ordered measurements. The additional age check uses a fixed 500 ms cutoff. These values describe the fixture.

In the controlled pause, the receiver intentionally stopped reading at the fourth message and resumed 90 ms after the next ideal pulse. The old and current messages were both queued when service resumed. The oracle labels the intended pulse at the generator. The C code receives the latest pulse index, arrival phase and age. It does not receive the generator label.

| Scenario | Messages | Maximum measured age | Phase only, correct / wrong | Phase and age, correct / wrong |
|---|---:|---:|---:|---:|
| Nominal local pipe | 12 | 0.2531 ms | 12 / 0 | 12 / 0 |
| Controlled receiver pause | 12 | 1,070.0816 ms | 10 / 1 | 11 / 0 |

In the pause run the phase-only policy used the old message for the current pulse. Its deduplication rule then rejected the fresh message for that pulse. The first correct update after the scheduled release arrived at 930.6124 ms with phase alone and 0.5892 ms with the age check. These times are directly observed in one scripted host run.

## Counterexample to publication-age checking

A separate deterministic fixture published a message at 950 ms after its originating pulse and delivered it at 1,050 ms. The age measured from publication was only 100 ms. Both the phase-only and publication-age policies accepted the message against the next pulse. Supplying the age from the true originating pulse made the same C age check expire it. This control uses a shared clock and assumes the true originating pulse timestamp is available. It does not propose a method for acquiring that timestamp across clock domains.

## Evidence checks

Zig 0.14.1 compiled the C11 program with warnings treated as errors. Six deterministic boundary vectors covered equality at the cutoffs, duplicate and reversed pulse order, and expiry. A separate Python verifier recomputed the arithmetic, all 48 policy decisions for 24 recorded messages, and the recovery metrics from the raw timestamps. The counterexample was compiled and run separately against the same C source.

## Research decision

Keep as a pilot. The nominal IPC run establishes the measurement procedure on the desktop. The controlled pause and source-delay case distinguish queue age from end-to-end age. They establish no timing distribution for an integrated flight-software link and no target-side recovery benefit.

The next test must use a reproducible timing path with a separately observed pulse, publication and receive-service boundary. First characterize nominal service and a documented recovery condition without intentionally holding the receiver. Keep a held receiver as a labeled control. Compare a competent end-to-end freshness check with an independent oracle. Drop the research claim if the representative path cannot cross a pulse or if the established check resolves the tested cases without a measurable availability, timing or implementation trade-off. This is the distinction needed before pursuing an IAC submission.
