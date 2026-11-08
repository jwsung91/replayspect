# Note: more than two participants and more than one channel

Survey only, as of WP2 (main `eeaa084`). No design is decided here, and no
code or schema changed. Example: a mobile base (`base.drive`) carrying a
turntable (`top.turntable`), with the rule "no top-module `motor_start`
while the base is driving".

## 1. What would change, file by file

- `sim/scheduler.py`: no change. It already runs any number of actors; RNG streams are named.
- `sim/link.py`: the channel is hard-wired for two parties.
  - `ENDPOINTS = ("client", "device")` and `DIRECTIONS = ("c2s", "s2c")`.
  - `Channel` has no name. Its RNG streams are `link/c2s`, `link/s2c` and `link/disconnect`.
  - Faults are recorded under the single actor `link`.
  - `MsgKey` is `(dir, msg, req_id, k)` with no channel.
  - `FaultPlan`, `from_trace`, `plan_report` and `check_plan_bounds` all assume one channel.
  - Several channels would need a channel id in `MsgKey`, in `data.link`, in the fault actor and in the RNG stream names.
  - Existing repros keep their digests only if the default channel keeps today's names and fields.
- `sut/lift.py`, `sut/turntable.py`: each builds its own `Scheduler`, `Trace` and `Channel` and writes actors `client`/`device`. Composing them on one scheduler would need constructors that accept a shared scheduler, trace and actor prefix. The base (`base.drive`) does not exist yet.
- `runner.py`:
  - `System` has one `run`, one `contracts_path`, one `ChannelProfile` and one `PlanVocabulary` (commands as `c2s` names).
  - `summary_line` reads `data.link`.
- `shrink.py` (reads `data.link`), `hyp.py` (draws `dir` from `c2s`/`s2c`), `session.py` (records `c2s`/`s2c` profile ranges): per-channel keys would be needed.
- `docs/plan-format.md`: `dir` is `c2s` or `s2c`. This file is planner-visible, so any change alters what planners are told.
- Trace and `docs/trace-schema.md`:
  - Dotted actor names are already reserved and the reader accepts them; `data.link` has no channel field.
  - Renaming `device` to `top.lift` in an existing system would change every digest, because `actor` is in the event core.
- `rewind.py`: needs no change for many actors (`--actor` repeats). `event_line` prints `k` but not a channel.

## 2. Cross-module contracts in the current DSL

Tried with `load_contracts` and `judge` on hand-made events:

- `base.drive.state` and `top.turntable.effect(motor_start)` are **rejected**.
  The pattern grammar is `actor.kind(NAMES)` with `actor` matching
  `[A-Za-z_][A-Za-z0-9_]*`, so the first dot ends the actor name.
- With underscore names the rule can be written, and `judge` reports the violation:
  `kind: forbid`, `event: top_turntable.effect(motor_start)`,
  `when: "last(base_drive.state).name == 'DRIVING'"`.
- The reverse direction ("base starts driving while a top motor runs") fits the same form:
  `event: base_drive.state(DRIVING)`,
  `when: "last(top_turntable.effect(motor_start|motor_stop)).name == 'motor_start'"`.
- Missing pieces:
  - **Dotted actors in patterns.**
  - **More than one comparison.** A condition is exactly one `==` or `!=`. There is no `and`, `or` or `in`, so "driving or turning" needs one contract per state.
  - **One transition table per file.** `transitions` is shared by every `state_machine` contract, so a system file with several state machines mixes their tables.
  - **No way to reuse contracts.** Nothing loads several contract files or puts a prefix on the actor names in `contracts/lift.v0.yaml` (`device.*`) when it is used inside a composed system.
  - **Shared request ids.** `req_id` values (`r-0001`) are not unique across subsystems. Per-`req_id` contracts are filtered by actor today, so they do not collide; a cross-module contract keyed by `req_id` would.
- Side finding: a `forbid` violation's detail prints the parsed condition's Python repr, not the YAML text (this also affects C4 in both example contract files). Since fixed: the detail now quotes the condition text.

## 3. Why not now, and when to look again

- The work order (WP3–WP9) does not include composition. The lift and the turntable are examples, not the product, so composing them is not a goal in itself.
- WP4 is the first test of whether partial logs plus replay find causes at all. Composition multiplies the plan space and the hidden-answer space before that test has a result.
- The surveyed changes touch `MsgKey`, the plan format (planner-visible) and the pattern grammar. Each one risks repro digests or planner-visible text.
- Things that would bring this back after WP4:
  - a WP4 result on single integrations;
  - a real incident or log (WP5) that involves two modules at once;
  - the robot-wide requirements questionnaire (deferred);
  - a cross-module rule that the user states as a contract.
