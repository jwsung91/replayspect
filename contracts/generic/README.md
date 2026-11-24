# Generic rules

Rules that do not depend on one protocol, written once in `rules.yaml` against roles. Each protocol binds
the roles to its own names in a file here (`lift.v0.yaml`, `turntable.v0.yaml`). Loading a binding file
expands every rule into contracts of the existing kinds, with `grade: generic` and a `source` naming the
rule; the judge sees only those contracts. The template form is described in
`src/replayspect/contract/spec.py` ("Roles").

| Rule | In words | Contracts it gives |
| --- | --- | --- |
| G1 | at most one effect of each name per request id | `G1.<effect>`, one per name in `effects` |
| G2 | per request id and reply role, no more replies than requests received | `G2.ack`, `G2.final`, `G2.poll.<poll>` |
| G3 | the two final answers exclude each other, per request id | `G3` |
| G4 | the device sends nothing for a request id it has not received | `G4` |
| G5 | no acknowledgement for a request id after its final answer | `G5` |
| G6 | the final answer of success only after the effect that ends the action | `G6` |
| G6b | the final answer of success only after the state change that ends the action | `G6b` |
| P1 | no stop of the action's effect after the state change that ends it | `P1` |
| P4 (rev2 only) | the state change that starts the action only after the effect that starts it, per request id | `P4` |

The roles a binding declares: `requests`, `acknowledgement`, `final_success`, `final_failure`, `polls`
(poll -> its reply), `effects`, `action` (`starts`, `ends`) and `rest_states`; a rev2 binding also
`progress_states` (the states of an action in progress).

**Two revisions, side by side.** A report names the set it used by path and sha256.

| Revision | Rules file | Bindings | What it holds |
| --- | --- | --- | --- |
| 1 | `rules.yaml` | `lift.v0.yaml`, `turntable.v0.yaml` | G1–G6b, P1. The three files stay byte for byte: earlier reports name them by sha256 |
| 2 | `rules.rev2.yaml` | `lift.v0.rev2.yaml`, `turntable.v0.rev2.yaml` | revision 1's rules, unchanged, and P4 |

A rule names roles; the loader refuses one whose binding lacks a role it uses, so P4 is only in revision 2,
whose bindings declare `progress_states`.

These rules go beside a protocol's own contracts, not instead of them. A planning session still shows its
protocol's contract file (`contracts/lift.v0.yaml`, `contracts/turntable.v0.yaml`); a binding file can be
given wherever a contract file path is taken, for example `claim check`.
