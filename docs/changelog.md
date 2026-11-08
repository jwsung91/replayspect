# Changelog

One paragraph per work package of `docs/work-order-v3.md`, newest last.

## WP1: rewind viewer

`replayspect rewind <trace>` reads a trace file (canonical JSON Lines, one
event per line) and nothing else, so it works on simulator traces now and on
log-adapter traces later. By default it prints a two-line summary; `--at`
gives the state after every event up to a virtual time, `--step N` lists the
next N events (negative: the previous ones), `--window T0 T1` (inclusive) and
`--actor` select events, `--ref` reports the first divergence from another
trace and `--contracts` judges the trace, always printing the end time used
for judging first because deadline contracts depend on it (`--end`, default
the last event). Listings are capped by `--limit`; `--full PATH` writes the
whole selection to a new file, never to stdout. A malformed trace file fails
with its file name and line number. `replay --trace-out PATH` writes the
reproduced run as such a trace file. No model, contract or LLM code changed.
