# Contract candidates for rev3 (operator note)

2026-11-15. WP6/7a stage 3 (`docs/work-order-wp67a.md`).

**The operator's decision** (2026-11-15, after #54):
- **N1 is adopted** as C14 in `contracts/lift.v0.rev3.yaml`, with a planner-neutral id and wording.
- **N1E and N1D are rejected:** N1 includes them.
- **S04 is not covered.** No `answered_within` kind is added. The reasons are in the #54 review: such a
  rule is met by a reply meant for something else, and the protocol gives no time. The coverage note
  records the gap and the kind it would take.

The rest of this note is the record as it was written for that decision.

testbed-05's slots are development data from now on. Every "catches" below is a **development check**,
like the rev2 checks before testbed-05, not a measurement. rev3 is measured only on a new blind group.

## The five slots, as the tools show them

Material:
- the slots' device logs. Their sha256 equal those recorded at the blind
  (`~/rs-control/testbed-05/blind-logs.sha256`);
- the correct device model's report on each (`replayspect device --complete
  device:recv,send,state,effect --out`). It gives the same first mismatch as the registered analysis;
- the client logs through `ingest` and `rewind`.

The truth files and the unpublished scoring were not used to draft the claims.

| Slot | First mismatch (device clock) | The device's lines for that request | The client's side |
| --- | --- | --- | --- |
| S03 | 28694 ms, `r-0006`: the model sends `ERROR reason=illegal`, the device `ACK reason=illegal` | 28194 recv, `ACK`; 28244 `ERROR`; 28694 recv again, `ACK reason=illegal` | sent once, closed on the `ERROR`, then got an `ACK` |
| S04 | 24395 ms, `r-0005`: the model sends `ERROR reason=illegal`, the device nothing | 23895 recv, `ACK`; 23945 `ERROR`; 24395 recv again, nothing | sent once, closed on the `ERROR`, nothing after |
| S06 | 8745 ms, `r-0002`: the model sends `ERROR reason=illegal`, the device `ACK` | 8245 recv, `ACK`; 8295 `ERROR`; 8745 recv again, `ACK` | sent once, closed on the `ERROR`, then got an `ACK` |
| S10 | 19144 ms, `r-0004`: the model sends `DONE`, the device `ACK` | 15644 recv, `ACK`; move; 18694 `DONE`; 19144 recv again, `ACK` | sent once, closed on the `DONE`, then got an `ACK` |
| S16 | 30646 ms, `r-0006`: the model sends `DONE`, the device `ACK` | 27146 recv, `ACK`; move; 30196 `DONE`; 30646 recv again, `ACK` | sent once, closed on the `DONE`, then got an `ACK` |

In all five slots, a copy of a request reached the device about 450 ms after the device had sent the
request's final answer. The count check names it an extra copy on the link. The protocol document
says what the answer should be (`docs/protocol-lift.md`, lines 37–39): "A known id is answered with the
stored result again (`ACK` while the move is in progress, `DONE` or `ERROR` once it has finished)".

## Claims and candidates

| Claim | Slots | Trigger and effect | Candidate |
| --- | --- | --- | --- |
| A | S03, S06 | When a request is received again after the device sent its `ERROR`, the device answers `ACK` instead of the stored `ERROR`. | **N1E**: no `ACK` for a `req_id` after its `ERROR` was sent |
| B | S10, S16 | When a request is received again after the device sent its `DONE`, the device answers `ACK` instead of the stored `DONE`. | **N1D**: no `ACK` for a `req_id` after its `DONE` was sent |
| A + B | S03, S06, S10, S16 | the advisor's reading: one contract for both | **N1**: no `ACK` for a `req_id` after its `DONE` or `ERROR` was sent |
| C | S04 | When a request is received again after the device sent its `ERROR`, the device sends no reply. | none: the language cannot state it (below) |

The candidate files are in [contract-candidates-rev3/](contract-candidates-rev3/):
- `N1.yaml`, `N1E.yaml` and `N1D.yaml` are each one `never_after` contract, with `event:
  device.send(ACK)`.
- The `after` is `device.send(DONE|ERROR)`, `device.send(ERROR)` and `device.send(DONE)` respectively.
- Each has `grade: stated`, and a `source` citing lines 37–39 with the quote above.

**N1 was already run on the simulator in stage 1** (#52, as the oracle's first `never_after` contract).
On seeds 0–99 the correct lift violated it on 0 seeds, M1 on 89 and M11 on 2. Stage 1 did not confirm
it. Here it goes through `claim check` like the others.

### Claim C: what it would take

S04 asks for a reply that never came. No kind requires that something happens after each occurrence
of an event:
- **`exactly_once`** takes only the first `start` of a key, and needs exactly one `event`. A repeat is the
  second receive of its key, and is answered a second time.
- **`count_le`** cannot see it. When the repeat arrives, the device has already sent `ACK` and `ERROR` for
  that id, so the count of replies is not behind the count of receives.
- **`forbid` with `last(...)`** could state it only by comparing the times of the last receive and the last
  send. That relies on the firmware replying in the same millisecond, which the protocol does not say.
  It is not proposed.

The kind it would take, written in the existing style, **not built**:

```yaml
- id: <new>
  kind: answered_within        # does not exist
  per: req_id
  start: device.recv(MOVE_UP|MOVE_DOWN)
  event: device.send(ACK|DONE|ERROR)
  within: <time>
```

**Meaning:** every `start` (each occurrence, not only the first) is followed, in trace order and no
later than `within` after it, by an `event` of the same key. Report at the first event past the
deadline, or at the end of the run.
- **Cut start:** can only miss.
- **Window end:** a `start` within `within` of the end is not judged.
- **Device log:** needs both kinds declared complete.

**Would it serve another protocol?** Yes. "Each request is answered within a time" belongs to any
request–response protocol (a door, a charger), and nothing in it is specific to the lift. In this
protocol it would also state two rows that the coverage note marks "no" today:
- line 40: a new id is answered with `ACK`;
- line 49: `STATUS` is answered immediately.

**A choice it forces:** lines 37–40 say a request is answered but give no time.
- `within` would be an assumption, so the contract could not be `grade: stated` as written.
- The candidates are 2 ms (the device-clock allowance used for C9) or the client's 2 s `ACK` timeout
  (line 56) as an outer bound.
- I have not checked such a contract on any data, because the kind does not exist.

**Stopped here for the operator's decision:** add a kind like this, which is a separate piece of work,
or leave S04 uncovered and record it in the coverage note.

## The check

At `5d61dd5` (main after #53). Each candidate was run with only the incidents it claims, each with its
model result, on three normal corpora:
- `real`: the real no-defect device logs;
- `sim`: seeds 0–999 of the correct lift;
- `all`: both. This is the corpus the work order names, and the official run.

The script is `~/rs-control/wp67a-stage3/run_checks.sh`. Its core:

```bash
python3 -m replayspect claim check docs/notes/contract-candidates-rev3/N1.yaml \
    --incident incidents/S03-device.log --model models/S03-device-report.json \
    --incident incidents/S06-device.log --model models/S06-device-report.json \
    --incident incidents/S10-device.log --model models/S10-device-report.json \
    --incident incidents/S16-device.log --model models/S16-device-report.json \
    --normal normal --normal-seeds 0-999 --complete device:recv,send,state,effect --out out/N1-all.json
```

(N1E: S03 and S06 only; N1D: S10 and S16 only. The `real` and `sim` runs drop `--normal-seeds` or
`--normal`.)

**The real corpus.** It has 213 device logs, one file each:

| Testbed | Files | How they were chosen |
| --- | --- | --- |
| testbed-01 | 39 | every run (no defect switch in that firmware) |
| testbed-02 | 48 | every run (no defect switch in that firmware) |
| testbed-03 | 68 | the device log's `build defect=none` line |
| testbed-04 | 56 | the truth file's `build defect=none` line (the device logs have no build line) |
| testbed-05 | 2 | S08 and S14 |

They are linked as `normal/tbNN-<run>-device.log`. The sha256 of the list is
`7342eff02605d8f7ae8f0a15531d6a8a30b7b62fab4ac8b000465338acbe7cac`: one line per file,
`<sha256>  normal/<name>`, in name order. `claim check` reports this value as `files_sha256`, and
`LC_ALL=C sha256sum normal/* | sha256sum` in that folder gives the same.

These logs are outside the repository, so the real-corpus numbers can be reproduced on one machine
only. The simulator part can be reproduced from the repository alone (below).

### Results

| Candidate | Incidents (first violation; same request as the model's first mismatch) | Corpus | Verdict | Exercised | Normal violations | Keys with an `after` | …with something later by the device (inputs) | …with anything later (inputs) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N1E | S03 `r-0006` yes; S06 `r-0002` yes | real | passes | 5 of 213 | 0 | 16 | 5 (5) | 5 (5) |
| | | sim | passes | 24 of 1000 | 0 | 62 | 25 (24) | 62 (48) |
| | | **all** | **passes** | 29 of 1213 | 0 | 78 | 30 (29) | 67 (53) |
| N1D | S10 `r-0004` yes; S16 `r-0006` yes | real | **untested** | 0 of 213 | 0 | 1255 | 0 (0) | 0 (0) |
| | | sim | passes | 912 of 1000 | 0 | 5902 | 2027 (912) | 5902 (1000) |
| | | **all** | **passes** | 912 of 1213 | 0 | 7157 | 2027 (912) | 5902 (1000) |
| N1 | S03, S06, S10, S16: as above, all yes | real | passes | 5 of 213 | 0 | 1271 | 5 (5) | 5 (5) |
| | | sim | passes | 917 of 1000 | 0 | 5964 | 2052 (917) | 5964 (1000) |
| | | **all** | **passes** | 922 of 1213 | 0 | 7235 | 2057 (922) | 5969 (1005) |

Every candidate's status was `ok` on every normal input. No input was not judged.

The text output of the official N1 run (rerun after #54 from the same folder, which links `docs` to the
repository's, with the candidate file's relative path, so no local path is quoted; the candidate's sha256 and every other line are unchanged):

```text
claim check: 1 candidate(s), 4 incident(s), normal corpus 1213 input(s) (213 file(s), seeds 0-999 of lift.v0, implementation with no defect)
candidates: docs/notes/contract-candidates-rev3/N1.yaml sha256 84c1d85a32ac9b563551912b1319b7654f3c089c3a6f1d36771a3818571626db
device logs declared complete for: device effect, device recv, device send, device state
incident 1: incidents/S03-device.log (device log) sha256 4fc76d60ff2ae849762e1f75e2162fdec10f34fd381827449bb429fbb228549b
  model result: models/S03-device-report.json sha256 c4faf72c5e9dfb10c8a41fff9bc56a8ec487e1f71521df8721e1b778eac7c427
incident 2: incidents/S06-device.log (device log) sha256 8e16488aeee425b7f63320a56d9c5c8e8a89a43480e052ff3cbbe901f7125f08
  model result: models/S06-device-report.json sha256 49ec73c892b86b93b28265b773213acf3d9fd7b82477b0517d69483ff489444b
incident 3: incidents/S10-device.log (device log) sha256 4a2c654c82fa8668de809cc65866e493b70ecddaf89eb650cfe26bf9aa7d14ee
  model result: models/S10-device-report.json sha256 ce38df0e34dd0746858f5f81ccbb0299dd72217ff00218fc537985f53943800e
incident 4: incidents/S16-device.log (device log) sha256 ef805da900027a904a7445b9124826e06a263bc258b32f5d266dfa1547ee566a
  model result: models/S16-device-report.json sha256 279090689d527f1671b7ce4ab1b8bf776d8226fee4c9faff53f9e96765547a1a
normal files: 213, sha256 of the list (sha256, two spaces, path; one per line) 7342eff02605d8f7ae8f0a15531d6a8a30b7b62fab4ac8b000465338acbe7cac

N1 (never_after): passes
  incident 1: violated at t=28.694000s r-0006: ACK after device.send(DONE|ERROR)
    the model's first mismatch: r-0006; same request as the model's first mismatch: yes
  incident 2: violated at t=8.745000s r-0002: ACK after device.send(DONE|ERROR)
    the model's first mismatch: r-0002; same request as the model's first mismatch: yes
  incident 3: violated at t=19.144000s r-0004: ACK after device.send(DONE|ERROR)
    the model's first mismatch: r-0004; same request as the model's first mismatch: yes
  incident 4: violated at t=30.646000s r-0006: ACK after device.send(DONE|ERROR)
    the model's first mismatch: r-0006; same request as the model's first mismatch: yes
  normal: exercised in 922 of 1213; ok 1213
    never_after: keys with an after 7235, of which with something later by device 2057 in 922 input(s) (the measure used), with anything later 5969 in 1005
```

**The simulator part from the repository alone.** The normal-corpus numbers do not depend on the
incidents, so this gives the `sim` rows without the real logs (run at the repository root):

```python
from pathlib import Path
from replayspect.claim import judge_one, sim_input
from replayspect.contract import load_contracts
from replayspect.runner import get_system

system = get_system("lift.v0")
cands = {c: load_contracts(Path(f"docs/notes/contract-candidates-rev3/{c}.yaml")) for c in ("N1E", "N1D", "N1")}
keys = ("keys_with_after", "after_then_event_actor", "after_then_anything")
rows = {c: dict.fromkeys(("exercised", "violations") + keys, 0) for c in cands}
for seed in range(1000):
    inp = sim_input(system, seed)
    for c, cs in cands.items():
        r = judge_one(cs.contracts[0], cs, inp)
        rows[c]["violations"] += len(r["violations"])
        rows[c]["exercised"] += r["status"] == "violated" or r["tried"]["after_then_event_actor"] > 0
        for k in keys:
            rows[c][k] += r["tried"][k]
print(rows)
```

Expected:
- N1E: exercised 24, violations 0, keys 62 / 25 / 62;
- N1D: 912, 0, 5902 / 2027 / 5902;
- N1: 917, 0, 5964 / 2052 / 5964.

## What the numbers say

- **All four incidents fall to N1**, as the advisor read it. In each, the first violation is the request
  of the device model's first mismatch, at the same time. This is a development check on slots that
  were drafted from.
- **No violation anywhere in the normal corpus:** not on the 213 real logs, and not on the 1000 seeds.
- **On hardware, the `DONE` half was never tried.** The real logs hold 1255 requests with a `DONE`.
  For none of them did the device hear of the request again. In this corpus, a copy after the `DONE`
  never reached a device without a defect: the only testbed-05 slots whose plan sent one, S10 and S16,
  ran on changed builds.
- **The `ERROR` half was tried on hardware 5 times,** all in testbed-03 runs R005, R017, R020, R035 and
  R065, each answered correctly.
- **The `DONE` half's support comes from the simulator only.** On the simulator, 2027 requests were heard
  of again after their `DONE`, in 912 seeds, and 25 after their `ERROR`, in 24 seeds. The simulator runs
  the reference implementation, so this shows that the rule holds for the model the firmware was checked
  against, not for the firmware.
- **The measure of "exercised" is the conservative one** (`docs/claims.md`). An unsolicited `ACK` needs no
  trigger, so every real log also showed that no `ACK` came from nowhere after a `DONE`. That is weaker
  evidence than a repeat answered correctly.

## Recommendation

- **Confirm N1** as the rev3 addition.
  - It is one contract, stated by lines 37–39, and caught all four incidents on the right request.
  - It passed with no violation on 1213 normal inputs.
  - Its two halves were each exercised: the `ERROR` half on hardware and the simulator, the `DONE` half on
    the simulator.
- **Drop N1E and N1D.** Each is implied by N1. They were drafted to show that each half was tried
  separately, and the table above shows it.
- **A limit to record if N1 is confirmed:** the `DONE` half has no hardware evidence yet. A real log
  without a defect that has a copy after `DONE` would give it its first one. A testbed-06 plan pool can
  include copies after `DONE` on unchanged builds.
- **Claim C (S04): the operator's decision** (above). I have not drafted a candidate for it.

## After the operator's decision (not done here)

- `contracts/lift.v0.rev3.yaml`: rev2 unchanged, plus the confirmed contracts, with planner-neutral ids
  and wording.
- The oracle: N1 is already written by hand in `tests/lift_oracle.py`, so it would be pointed at the rev3
  file.
- The per-mutant table on seeds 0–999.
- The coverage note's rows (lines 37–39, and the definition of "can state it", which still counts nine
  kinds).
- Already done in this PR: the whole-file word scan covers every file in `contracts/` (it also looks for
  slot names and "operator").
