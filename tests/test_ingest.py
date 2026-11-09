"""WP5a: text log ingest (replayspect.ingest, docs/rules-schema.md)."""

import json
from pathlib import Path

import pytest

from replayspect.__main__ import main
from replayspect.ingest import CLOCK_STEP_RUN, IngestError, RulesError, ingest_text, parse_rules, read_rules
from replayspect.trace import Trace
from replayspect.tracefile import parse_trace_file, read_trace_file, trace_file_text

DATA = Path(__file__).parent / "data" / "ingest"

#: A minimal rules file; tests replace parts of it.
BASE = """\
schema: replayspect.rules/1
name: t
actor: client
clock: {format: epoch, unit: s, timezone: "+09:00", tolerance: 5ms}
entry: {pattern: '^(?P<time>[0-9.]+) (?P<text>.*)$'}
rules:
  - name: tx
    match: '^TX (?P<msg>\\w+)(?: (?P<req>r-\\d+))?$'
    event: {kind: send, name: '{msg}', req_id: '{req?}'}
"""


def ingest(log: str, rules: str = BASE):
    return ingest_text(log.encode(), parse_rules(rules), "t.log")


def records(res):
    return [e.to_record() for e in res.events]


# -- the two sample formats -------------------------------------------------------------------


def both():
    return [ingest_text((DATA / f"client-{f}.log").read_bytes(), read_rules(DATA / f"client-{f}.rules.yaml"),
                        f"client-{f}.log") for f in ("ros", "kv")]


def test_two_line_formats_give_the_same_trace_by_changing_only_the_rules():
    ros, kv = both()
    assert trace_file_text(ros.events, ros.header) == trace_file_text(kv.events, kv.header)
    assert [(e.kind, e.name, e.req_id) for e in ros.events] == [
        ("send", "MOVE_UP", "r-0001"), ("send", "STATUS", "s-0001"), ("recv", "ACK", "r-0001"),
        ("recv", "STATUS_REPLY", "s-0001"), ("recv", "ERROR", None), ("handle", "DONE", "r-0001")]
    assert ros.header.origin == "2026-11-10T08:00:00.000000+09:00"
    assert ros.header.source == "adapter:text" and ros.header.seed is None and ros.header.system == "lift.v0"
    assert all(e.fidelity == "exact" and e.source == "adapter:text" for e in ros.events)


def test_counts_blank_ignored_and_unmatched_entries_with_continuation_lines():
    ros, _ = both()
    assert (ros.entries, ros.blank, ros.ignored) == (9, 1, 1)
    assert [u.line for u in ros.unmatched] == [7, 8]
    assert ros.unmatched[1].text.count("\n") == 2  # the traceback joined its entry
    assert ros.events[-1].log == {"line": 12}  # line numbers count every line


def test_written_trace_reads_back_unchanged_and_rewind_shows_the_flags(tmp_path, capsys):
    ros, _ = both()
    out = tmp_path / "client.jsonl"
    out.write_text(trace_file_text(ros.events, ros.header))
    tf = read_trace_file(out)
    assert [e.to_record() for e in tf.trace.events] == records(ros) and tf.header == ros.header
    assert main(["rewind", str(out), "--window", "0", "10s"]) == 0
    text = capsys.readouterr().out
    assert "time 0 is 2026-11-10T08:00:00.000000+09:00 (header origin)" in text
    assert "recv ACK r-0001 [log line 5: out_of_order]" in text
    assert "flagged by the log adapter: out_of_order 1" in text


def test_schema_validates_every_ingested_line():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((Path(__file__).parent.parent / "schemas" / "trace-1.schema.json").read_text())
    ros, _ = both()
    for line in trace_file_text(ros.events, ros.header).splitlines():
        jsonschema.validate(json.loads(line), schema)


# -- event fields ----------------------------------------------------------------------------


def test_req_id_may_be_left_out_and_empty_data_is_not_written():
    res = ingest("1.0 TX MOVE_UP r-0001\n2.0 TX PING\n")
    assert [e.req_id for e in res.events] == ["r-0001", None]
    assert all("data" not in r and "req_id" not in r for r in records(res)[1:])


def test_template_types_optional_groups_and_literal_braces():
    rules = BASE.replace("""    event: {kind: send, name: '{msg}', req_id: '{req?}'}""",
                         """    event: {kind: send, name: '{msg}', req_id: '{req?}',
            data: {n: '{n|int}', x: '{x|float}', tag: 'v{{{msg}}}', lit: 3}}""").replace(
        r"(?: (?P<req>r-\d+))?$", r"(?: (?P<req>r-\d+))? n=(?P<n>-?\d+) x=(?P<x>\S+)$")
    res = ingest("1.0 TX GO n=-4 x=2.5\n", rules)
    assert res.events[0].data == {"n": -4, "x": 2.5, "tag": "v{GO}", "lit": 3}
    with pytest.raises(IngestError, match=r"t.log:1: rule 'tx': 'abc' \(group 'n'\) is not an integer"):
        ingest("1.0 TX GO n=abc x=1\n", rules.replace(r"(?P<n>-?\d+)", r"(?P<n>\S+)"))
    with pytest.raises(IngestError, match="not a finite number"):
        ingest("1.0 TX GO n=1 x=nan\n", rules)


def test_first_matching_rule_wins_including_ignore_rules_and_where_filters():
    rules = BASE.replace("rules:\n", """rules:
  - name: quiet
    match: '^TX PING'
    ignore: true
  - name: only-b
    where: {time: '2\\..*'}
    match: '^TX'
    event: {kind: effect, name: B}
""")
    res = ingest("1.0 TX PING\n2.0 TX PING\n2.5 TX GO\n3.0 TX GO\n", rules)
    assert res.ignored == 2
    assert [(e.kind, e.name) for e in res.events] == [("effect", "B"), ("send", "GO")]


# -- time ------------------------------------------------------------------------------------


def test_out_of_order_events_are_sorted_and_flagged_never_dropped():
    res = ingest("1.000 TX A\n1.004 TX B\n1.001 TX C\n0.990 TX D\n2.0 TX E\n")
    assert [e.name for e in res.events] == ["D", "A", "C", "B", "E"]
    flags = {e.name: (e.log or {}).get("flags") for e in res.events}
    assert flags == {"A": None, "B": None, "C": ["out_of_order"], "D": ["out_of_tolerance"], "E": None}
    assert res.events[0].t_us == 0 and res.events[1].t_us == 10_000  # times as logged, from the earliest
    assert res.clock_steps == []


def test_a_run_of_out_of_tolerance_lines_is_reported_as_a_clock_step():
    log = "10.0 TX A\n11.0 TX B\n9.0 TX C\n9.1 TX D\n9.2 TX E\n12.0 TX F\n10.5 TX G\n13.0 TX H\n"
    res = ingest(log)
    assert len([e for e in res.events if e.log.get("flags") == ["out_of_tolerance"]]) == 4
    assert [(c.first_line, c.last_line, c.events, c.back_us) for c in res.clock_steps] == [(3, 5, 3, 2_000_000)]
    assert CLOCK_STEP_RUN == 3  # a lone late line (line 7) is not a step
    text = "\n".join(res.summary("t.log", "o.jsonl", None))
    assert "clock_step suspected 1: lines 3-5 (3 events, 2.000000s back); not corrected" in text


def test_clock_formats_and_time_zones():
    iso = BASE.replace("{format: epoch, unit: s, timezone: \"+09:00\", tolerance: 5ms}",
                       "{format: '%Y-%m-%d_%H:%M:%S.%f', timezone: Asia/Seoul}").replace(
        "(?P<time>[0-9.]+)", "(?P<time>\\S+)")
    res = ingest("2026-11-10_08:00:00.000001 TX A\n", iso)
    assert res.header.origin == "2026-11-10T08:00:00.000001+09:00"
    ms = BASE.replace("unit: s", "unit: ms")
    assert [e.t_us for e in ingest("1000 TX A\n1002.5 TX B\n", ms).events] == [0, 2500]
    naive = BASE.replace("format: epoch, unit: s, timezone: \"+09:00\"", "format: iso8601").replace(
        "(?P<time>[0-9.]+)", "(?P<time>\\S+)")
    with pytest.raises(IngestError, match="t.log:1: rule 'tx': .*no UTC offset.*does not guess"):
        ingest("2026-11-10T08:00:00 TX A\n", naive)
    assert ingest("2026-11-10T08:00:00Z TX A\n", naive).header.origin == "2026-11-10T08:00:00.000000+00:00"


def test_explicit_origin():
    rules = BASE.replace("tolerance: 5ms}", "tolerance: 5ms, origin: '2026-11-10T08:00:00+09:00'}")
    res = ingest("1794265201.5 TX A\n", rules)
    assert res.events[0].t_us == 1_500_000 and res.header.origin == "2026-11-10T08:00:00.000000+09:00"
    with pytest.raises(IngestError, match="t.log:1: event before clock.origin"):
        ingest("1794265199 TX A\n", rules)


def test_bad_timestamp_names_the_rule_and_line():
    with pytest.raises(IngestError, match=r"t.log:2: rule 'tx': cannot read '1\.2\.3' as an epoch time"):
        ingest("1.0 TX A\n1.2.3 TX B\n")


# -- the log's bytes ---------------------------------------------------------------------------


def test_crlf_is_removed_and_bad_utf8_names_the_line():
    assert records(ingest("1.0 TX A\r\n2.0 TX B\r\n")) == records(ingest("1.0 TX A\n2.0 TX B\n"))
    with pytest.raises(IngestError, match="t.log:2: not UTF-8"):
        ingest_text(b"1.0 TX A\n2.0 TX \xff\n", parse_rules(BASE), "t.log")


def test_log_line_numbers_are_outside_the_digest():
    a = ingest("1.0 TX A\n2.0 TX B\n")
    b = ingest("\n\n1.0 TX A\n\n2.0 TX B\n")
    assert [e.log["line"] for e in b.events] == [3, 5]
    assert Trace.from_events(a.events).digest() == Trace.from_events(b.events).digest()


# -- a bad rules file ------------------------------------------------------------------------


@pytest.mark.parametrize("old,new,msg", [
    ("name: t\n", "name: t\ncolour: red\n", r"unknown key\(s\) colour"),
    ("schema: replayspect.rules/1", "schema: replayspect.rules/2", "schema must be"),
    ("'^TX (?P<msg>", "'^TX ((?P<msg>", r"rule 'tx' match: bad regular expression"),
    ("kind: send", "kind: sent", r"rule 'tx' event.kind 'sent' is not one of"),
    ("name: '{msg}'", "name: '{mesg}'", r"rule 'tx' event.name uses group\(s\) mesg"),
    ("name: '{msg}'", "name: '{msg|int}'", r"rule 'tx' event.name must be text"),
    ("name: '{msg}'", "name: '{msg?}'", r"rule 'tx' event.name cannot be optional"),
    ("name: '{msg}'", "name: 'x{msg|int}'", r"rule 'tx' event.name: \{msg\|int\} must be the whole value"),
    ("name: '{msg}'", "name: '{msg'", r"unmatched brace"),
    ("req_id: '{req?}'", "req_id: '{req?}', data: {link: 1}", "data.link is reserved"),
    ("    event: {kind: send, name: '{msg}', req_id: '{req?}'}\n", "", r"rule 'tx' needs an event"),
    ("actor: client\n", "", r"rule 'tx' event needs an actor"),
    ("timezone: \"+09:00\"", "timezone: Mars/Olympus", "unknown time zone"),
    ("format: epoch, unit: s, timezone: \"+09:00\"", "format: '%H:%M:%S'",
     r"has no UTC offset \(%z\); give clock.timezone"),
    ("unit: s", "unit: min", "clock.unit must be one of"),
    ("tolerance: 5ms", "tolerance: soon", "clock.tolerance must be a time"),
    ("(?P<time>[0-9.]+)", "(?P<when>[0-9.]+)", "entry.pattern has no group 'time'"),
])
def test_bad_rules_fail_with_the_rule_name(old, new, msg):
    text = BASE.replace(old, new)
    assert text != BASE, old
    with pytest.raises(RulesError, match=msg):
        parse_rules(text, "r.yaml")


def test_duplicate_rule_names_and_ignore_with_event_are_refused():
    dup = BASE + "  - name: tx\n    match: x\n    ignore: true\n"
    with pytest.raises(RulesError, match="r.yaml: rule name\\(s\\) used twice: tx"):
        parse_rules(dup, "r.yaml")
    both_ = BASE.replace("    event:", "    ignore: true\n    event:")
    with pytest.raises(RulesError, match="an ignore rule has no event"):
        parse_rules(both_, "r.yaml")


# -- trace file rules for the new fields ---------------------------------------------------------


def test_trace_reader_checks_log_and_origin():
    head = '{"type":"header","schema":"replayspect.trace/1","origin":"2026-11-10T08:00:00+09:00"}\n'
    ev = '{"seq":0,"t_us":0,"actor":"client","kind":"send","name":"A","log":%s}\n'
    assert parse_trace_file(head + ev % '{"line":3,"flags":["out_of_order"]}').trace.events[0].log["line"] == 3
    with pytest.raises(ValueError, match="log flags must be"):
        parse_trace_file(ev % '{"line":3,"flags":["late"]}')
    with pytest.raises(ValueError, match="log line must be a positive integer"):
        parse_trace_file(ev % '{"line":0}')
    with pytest.raises(ValueError, match="header origin needs a UTC offset"):
        parse_trace_file(head.replace("+09:00", ""))


# -- command line ------------------------------------------------------------------------------


def test_cli_writes_trace_and_unmatched_list_and_never_overwrites(tmp_path, capsys):
    out = tmp_path / "c.jsonl"
    args = ["ingest", str(DATA / "client-ros.log"), "--rules", str(DATA / "client-ros.rules.yaml"),
            "--out", str(out)]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert "entries 9 (blank lines 1): events 6, ignored 1, unmatched 2" in text
    assert "flagged 1: out_of_order 1, out_of_tolerance 0 (tolerance 5000us)" in text
    assert read_trace_file(out).header.origin == "2026-11-10T08:00:00.000000+09:00"
    listed = (tmp_path / "c.jsonl.unmatched.txt").read_text()
    assert listed.startswith("7: [INFO] [1794265204.000000] [ui]: operator pressed STOP\n8: ")
    assert "\n    " in listed
    assert main(args) == 2
    assert "exists; not overwriting it" in capsys.readouterr().err


def test_cli_reports_bad_rules_with_status_2(tmp_path, capsys):
    bad = tmp_path / "r.yaml"
    bad.write_text(BASE.replace("kind: send", "kind: sent"))
    log = tmp_path / "t.log"
    log.write_text("1.0 TX A\n")
    assert main(["ingest", str(log), "--rules", str(bad), "--out", str(tmp_path / "o.jsonl")]) == 2
    assert "rule 'tx' event.kind 'sent'" in capsys.readouterr().err
    assert not (tmp_path / "o.jsonl").exists()


def test_cli_records_a_contract_file(tmp_path):
    out = tmp_path / "c.jsonl"
    contracts = Path(__file__).parent.parent / "contracts" / "lift.v0.yaml"
    assert main(["ingest", str(DATA / "client-kv.log"), "--rules", str(DATA / "client-kv.rules.yaml"),
                 "--out", str(out), "--contracts", str(contracts)]) == 0
    assert read_trace_file(out).header.contracts["sha256"]


def test_the_rules_schema_doc_example_gives_the_trace_it_shows():
    import re

    doc = (Path(__file__).parent.parent / "docs" / "rules-schema.md").read_text()
    ex = doc.split("## Example")[1].split("## Top level")[0]
    log, rules, trace = (re.search(rf"```{k}\n(.*?)```", ex, re.S).group(1) for k in ("text", "yaml", "json"))
    res = ingest_text(log.encode(), parse_rules(rules))
    assert trace_file_text(res.events, res.header) == trace
