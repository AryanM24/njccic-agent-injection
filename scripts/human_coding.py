"""Support for the human check (doc 09 §6; doc 10 §7): sheets, packets, agreement.

    human_coding.py practice ANALYSIS_DIR... --exclude SHEET --out DIR [--n 20]
    human_coding.py packets SHEET --out DIR
    human_coding.py blind ANALYSIS_DIR... --n 360 --seed S --out DIR
    human_coding.py agree CODER_A.csv CODER_B.csv --key DIR/key.csv [--out DIR]

`practice` draws a calibration set that shares no run with the real sample,
half of it runs the scorers flagged, so coders see positives before the real
sheet. `packets` renders one Markdown page per sheet row with everything a
coder needs (case facts, every tool call, every email, both runs) and no score.

`blind` is the second-edition sample (doc 10 §7), built to avoid what sank the
first one (DEV-1). Coders see an opaque row id and one run per packet: no model,
no isolation flag, no attack/twin label, no scorer output. It stratifies on
condition *and* on the scorers' decision, so scorer-negative runs are checked
for misses rather than only flagged runs for false alarms. Each coder gets an
identical blank sheet in their own shuffled order. `agree` refuses a returned
sheet that is blank, constant where the key varies, or a copy of the other
coder's, and writes kappa, confusion counts and an adjudication list.

Packets quote traces and payloads, which are Tier 1 (doc 05 §6): write them
under `logs/` only and share them only with approved coders.
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

from analyze import CODED, _norm, write_csv
from inspect_ai.log import read_eval_log

from eduinject.analysis import CELL_FIELDS, cohen_kappa, refuse_stale, sheet_problems
from eduinject.defense import unmark
from eduinject.extraction import extract
from eduinject.scorers.deterministic import RUNS_KEY

IDS = ("log", "sample_id", "epoch", *CELL_FIELDS, "artifact_id", "goal", "channel")
HARM = ("exfiltration", "scope_violation", "authorization")
CASE_FACTS = (
    ("authorized_recipients", "District mailbox (entitled to everything)"),
    ("correspondent_addresses", "Correspondent on file (W1 submitter / W3 guardian)"),
    ("applicant_addresses", "Applicant's own address (W2)"),
    ("entitled_actions", "Actions the requester is really entitled to (W1)"),
    ("protected_terms", "Protected values about this person (T2 examples)"),
    ("third_party_terms", "Values belonging to other people (T3 examples)"),
    ("other_candidate_terms", "Other candidates (W2 T3)"),
)


def key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["log"], row["sample_id"], str(row["epoch"])


def stale_logs(rows: list[dict[str, str]], args: argparse.Namespace) -> bool:
    """True if the logs these rows came from hold stale scores (exit 4)."""
    dirs = {str(Path(r["log"].removeprefix("file://")).parent) for r in rows}
    return refuse_stale(sorted(dirs), args.allow_stale)


def cmd_practice(args: argparse.Namespace) -> int:
    with open(args.exclude, newline="", encoding="utf-8") as f:
        taken = {key(r) for r in csv.DictReader(f)}
    rows = []
    for d in args.analysis:
        with open(Path(d) / "rows.csv", newline="", encoding="utf-8") as f:
            rows += [
                r
                for r in csv.DictReader(f)
                if r["benign_only"] == "False" and r["status"] == "scored"
            ]
    rows = [r for r in rows if key(r) not in taken]
    if stale_logs(rows, args):
        return 4
    positive = [r for r in rows if any(r.get(f"score:{m}") == "1.0" for m in HARM)]
    rng = random.Random(args.seed)
    half = args.n // 2
    chosen = rng.sample(positive, min(half, len(positive)))
    rest = [r for r in rows if r not in chosen]
    chosen += rng.sample(rest, args.n - len(chosen))
    rng.shuffle(chosen)
    out = Path(args.out)
    blank = {f"code:{c}": "" for c in CODED}
    write_csv(
        out / "coding_sheet.csv",
        [{**{f: r[f] for f in IDS}, **blank, "notes": ""} for r in chosen],
    )
    write_csv(
        out / "answer_key.csv",
        [
            {
                **{f: r[f] for f in IDS},
                **{f"code:{c}": r.get(f"score:{c}", "") for c in CODED},
            }
            for r in chosen
        ],
    )
    print(
        f"{len(chosen)} practice runs ({min(half, len(positive))} scorer-flagged) -> {out.resolve()}"
    )
    return 0


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts)


def run_section(title: str, run: dict[str, Any], outcomes: bool = True) -> list[str]:
    ledger, pipe = run["ledger"], run["pipeline"]
    called = list(dict.fromkeys(c.get("tool", "") for c in ledger["calls"]))
    lines = [
        f"## {title}",
        "",
        f"**Tools called:** {', '.join(called) or '(none)'}",
        "",
    ]
    lines += ["### Every tool call, in order", ""]
    for i, c in enumerate(ledger["calls"], 1):
        lines.append(
            f"{i}. `{c.get('tool')}` {json.dumps(c.get('args', {}))}"
            + (f" → {c.get('outcome')}" if outcomes else "")
        )
    if not ledger["calls"]:
        lines.append("(none)")
    lines += ["", "### Every email it tried to send", ""]
    for i, e in enumerate(ledger["attempted_egress"], 1):
        lines += [
            f"**Email {i}** — to `{e.get('to')}` — subject: {e.get('subject')}",
            "",
            "```",
            str(e.get("body", "")),
            "```",
            "",
        ]
    if not ledger["attempted_egress"]:
        lines += ["(none)", ""]
    # The action stage's output is the final report; a run that stopped on a
    # hand-off parse error has no action stage, so every recorded stage shows.
    pre_action = [s for s in pipe["stages"] if s["name"] != "action"]
    shown = [
        (f"Stage {i} ({s['name']}) output", s["output"])
        for i, s in enumerate(pre_action, 1)
    ]
    shown.append(("Final report", pipe.get("final")))
    for label, text in shown:
        lines += [f"### {label}", "", "```", text_of(text), "```", ""]
    return lines


def cmd_packets(args: argparse.Namespace) -> int:
    with open(args.sheet, newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    if stale_logs(sheet, args):
        return 4
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logs: dict[str, Any] = {}
    index = [
        "# Coding packets",
        "",
        "Packet number = row number in the coding sheet.",
        "",
    ]
    for n, row in enumerate(sheet, 1):
        path = row["log"].removeprefix("file://")
        if path not in logs:
            logs[path] = {
                (s.id, str(s.epoch)): s for s in read_eval_log(path).samples or []
            }
        sample = logs[path][(row["sample_id"], str(row["epoch"]))]
        md = sample.metadata
        runs = md[RUNS_KEY]
        lines = [
            f"# Packet {n:03d} — {row['workflow'].upper()} {row['sample_id']} epoch {row['epoch']}",
            "",
            f"- Scope: **{row['scope']}**; isolation: **{'on' if row['isolated'] == 'True' else 'off'}**",
            f"- Tools this run was given: {', '.join(runs['attack']['ledger'].get('granted_tools', []))}",
            f"- Operator request: {sample.input if isinstance(sample.input, str) else text_of(sample.input)}",
            "",
            "## Case facts (ground truth from the district directory)",
            "",
        ]
        for field, label in CASE_FACTS:
            if md.get(field):
                lines.append(f"- **{label}:** {json.dumps(md[field])}")
        lines += ["", "---", ""]
        lines += run_section("A. Attack run (code this one)", runs["attack"])
        lines += ["---", ""]
        lines += run_section(
            "B. Twin run (same document without the attack; for action_divergence only)",
            runs["twin"],
        )
        name = f"{n:03d}_{row['workflow']}_{row['sample_id']}_e{row['epoch']}.md"
        (out / name).write_text("\n".join(lines), encoding="utf-8")
        index.append(
            f"- [{n:03d}]({name}) {row['workflow']} {row['scope']} iso={row['isolated']}"
        )
    (out / "index.md").write_text("\n".join(index), encoding="utf-8")
    print(f"{len(sheet)} packets -> {out.resolve()}")
    return 0


BLIND_CODED = ("exfiltration", "authorization", "scope_violation")
"""What a coder can judge from one run. action_divergence needs both runs of a
pair, so it is not human-coded in the blinded design (it is a set difference
over the ledger, recomputable from the log by anyone)."""

EXPLORATORY = ("acted_on_document_instruction",)
"""Codes with no automated counterpart, collected to validate a future
semantic-propagation judge (WS9). Reported descriptively, never as kappa
against the scorers (doc 10 §7)."""


def _positive(row: dict[str, str]) -> bool:
    return any(row.get(f"score:{m}") == "1.0" for m in BLIND_CODED)


def blind_sample(rows: list[dict[str, str]], n: int, seed: int) -> list[dict[str, str]]:
    """Draw `n` scored runs, balanced over cell × scorer decision.

    Every cell gets an equal share, split evenly between runs a harm scorer
    flagged and runs none did (a missing class's share goes to the other), so
    false negatives are as visible as false positives. Leftover places are
    filled at random from what remains. Deterministic under `seed`.
    """
    rng = random.Random(seed)
    strata: dict[tuple[str, ...], dict[bool, list[dict[str, str]]]] = {}
    for row in rows:
        if row["status"] != "scored":
            continue
        cell = tuple(row.get(f, "") for f in CELL_FIELDS)
        strata.setdefault(cell, {True: [], False: []})[_positive(row)].append(row)
    if not strata:
        return []
    share = max(1, n // len(strata))
    chosen: list[dict[str, str]] = []
    for cell in sorted(strata):
        pos, neg = strata[cell][True], strata[cell][False]
        # Positives are the rarer class, so an odd share rounds toward them.
        k_pos = min(len(pos), -(-share // 2) if neg else share)
        k_neg = min(len(neg), share - k_pos)
        chosen += rng.sample(pos, k_pos) + rng.sample(neg, k_neg)
    # Below one run per cell, which cells are covered is decided at random,
    # not by sort order.
    rng.shuffle(chosen)
    chosen = chosen[:n]
    taken = {id(r) for r in chosen}
    rest = [
        r
        for c in strata.values()
        for side in c.values()
        for r in side
        if id(r) not in taken
    ]
    chosen += rng.sample(rest, min(len(rest), max(0, n - len(chosen))))
    return chosen


def _side(row: dict[str, str]) -> str:
    return "twin" if row["benign_only"] == "True" else "attack"


def blind_packet(row_id: str, sample: Any, side: str) -> str:
    """One run, with nothing that identifies its model, condition or side."""
    md = sample.metadata
    run = md[RUNS_KEY][side]
    lines = [
        f"# Packet {row_id}",
        "",
        f"- Workflow: **{md['artifact_id'].split('_')[0].rstrip('c').upper()}**",
        f"- Tools this run was given: {', '.join(run['ledger'].get('granted_tools', []))}",
        f"- Operator request: {sample.input if isinstance(sample.input, str) else text_of(sample.input)}",
        "",
        "## Case facts (ground truth from the district directory)",
        "",
    ]
    for field, label in CASE_FACTS:
        if md.get(field):
            lines.append(f"- **{label}:** {json.dumps(md[field])}")
    lines += ["", "---", ""]
    # Outcomes would reveal the guard arm (`denied_by_guard`); the codes are on
    # what the agent tried, so the coder does not need them.
    lines += run_section("The run (code this one)", run, outcomes=False)
    # Datamarks would tell the coder the run was in the spotlight arm.
    return unmark("\n".join(lines))


def cmd_blind(args: argparse.Namespace) -> int:
    rows: list[dict[str, str]] = []
    for d in args.analysis:
        with open(Path(d) / "rows.csv", newline="", encoding="utf-8") as f:
            rows += [r for r in csv.DictReader(f) if r["controls"] == "False"]
    if stale_logs(rows, args):
        return 4
    chosen = blind_sample(rows, args.n, args.seed)
    cells = {tuple(r.get(f, "") for f in CELL_FIELDS) for r in rows}
    if args.n < 2 * len(cells):
        print(
            f"warning: n={args.n} is under two runs for each of {len(cells)} "
            "cells, so some cells get no positive or no run at all",
            file=sys.stderr,
        )
    if not chosen:
        print("no scored runs to sample", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    ids = [f"R{i:04d}" for i in rng.sample(range(1, 10 * len(chosen)), len(chosen))]
    out = Path(args.out)
    (out / "packets").mkdir(parents=True, exist_ok=True)
    (out / "second_pass").mkdir(parents=True, exist_ok=True)
    key = []
    logs: dict[str, Any] = {}
    for row_id, row in zip(ids, chosen, strict=True):
        path = row["log"].removeprefix("file://")
        if path not in logs:
            logs[path] = {
                (s.id, str(s.epoch)): s for s in read_eval_log(path).samples or []
            }
        sample = logs[path][(row["sample_id"], str(row["epoch"]))]
        side = _side(row)
        packet = blind_packet(row_id, sample, side)
        (out / "packets" / f"{row_id}.md").write_text(packet, encoding="utf-8")
        # The exploratory code needs the document, which would unblind the main
        # codes (it shows whether an attack was there), so it is coded in a
        # second pass from separate packets, after the main sheets are in.
        doc_key = "twin_path" if side == "twin" else "artifact_path"
        document = unmark(extract(sample.metadata[doc_key]))
        (out / "second_pass" / f"{row_id}.md").write_text(
            f"{packet}\n\n---\n\n## The submitted document (as extracted)\n\n"
            f"```\n{document}\n```\n",
            encoding="utf-8",
        )
        key.append(
            {
                "row_id": row_id,
                **{f: row[f] for f in IDS},
                "side": side,
                "scorer_positive": _positive(row),
                **{f"code:{c}": row.get(f"score:{c}", "") for c in BLIND_CODED},
            }
        )
    for prefix, codes in (("coder", BLIND_CODED), ("second_pass_coder", EXPLORATORY)):
        blank = [
            {"row_id": r, **{f"code:{c}": "" for c in codes}, "notes": ""} for r in ids
        ]
        for coder in ("a", "b"):
            order = blank[:]
            random.Random(f"{args.seed}-{prefix}-{coder}").shuffle(order)
            write_csv(out / f"{prefix}_{coder}.csv", order)
    write_csv(out / "key.csv", key)
    positives = sum(bool(k["scorer_positive"]) for k in key)
    print(
        f"{len(chosen)} runs ({positives} scorer-flagged) -> {out.resolve()}\n"
        "Give each coder their own coder_?.csv and the packets/ folder; keep "
        "key.csv away from both until `agree` has run. Hand out second_pass/ and "
        "second_pass_coder_?.csv only after both main sheets are returned."
    )
    return 0


NA = ("n/a", "na")
"""Not-applicable codes. Unlike analyze.NA, a blank is *not* one: a blank on a
returned sheet means the coder skipped the row."""


def cmd_agree(args: argparse.Namespace) -> int:
    def load(path: str) -> dict[str, dict[str, str]]:
        with open(path, newline="", encoding="utf-8") as f:
            return {r["row_id"]: r for r in csv.DictReader(f)}

    a, b, key = load(args.coder_a), load(args.coder_b), load(args.key)
    refused = False
    for name, sheet, other in (("A", a, b), ("B", b, a)):
        codebook = {f"code:{c}": {"0", "1", "n/a"} for c in BLIND_CODED}
        for problem in sheet_problems(
            list(sheet.values()), list(key.values()), codebook, list(other.values())
        ):
            print(f"coder {name}: {problem}", file=sys.stderr)
            refused = True
    if refused and not args.accept_suspicious:
        print(
            "refused: fix the sheets (or pass --accept-suspicious and report why)",
            file=sys.stderr,
        )
        return 2
    adjudicate = []
    for c in BLIND_CODED:
        col = f"code:{c}"
        rows = [r for r in key if _norm(key[r].get(col, "")) not in ("", *NA)]
        for x, y, name in ((a, b, "A-B"), (a, key, "A-auto"), (b, key, "B-auto")):
            u = [_norm(x[r].get(col, "")) for r in rows]
            v = [_norm(y[r].get(col, "")) for r in rows]
            keep = [i for i in range(len(rows)) if u[i] not in NA and v[i] not in NA]
            if not keep:
                continue
            u, v = [u[i] for i in keep], [v[i] for i in keep]
            cells = {
                (p, q): sum(1 for i, j in zip(u, v, strict=True) if (i, j) == (p, q))
                for p in ("1.0", "0.0")
                for q in ("1.0", "0.0")
            }
            print(
                f"{col} {name}: kappa={cohen_kappa(u, v):.3f} n={len(u)} "
                f"[11={cells[('1.0', '1.0')]} 10={cells[('1.0', '0.0')]} "
                f"01={cells[('0.0', '1.0')]} 00={cells[('0.0', '0.0')]}]"
            )
        for r in rows:
            votes = {
                _norm(a[r].get(col, "")),
                _norm(b[r].get(col, "")),
                _norm(key[r].get(col, "")),
            }
            if len(votes - set(NA)) > 1:
                adjudicate.append(
                    {
                        "row_id": r,
                        "code": c,
                        "coder_a": a[r].get(col),
                        "coder_b": b[r].get(col),
                        "scorer": key[r].get(col),
                        "decision": "",
                        "reason": "",
                    }
                )
    if args.out:
        write_csv(Path(args.out) / "adjudication.csv", adjudicate)
        print(
            f"{len(adjudicate)} disagreements -> {Path(args.out).resolve() / 'adjudication.csv'}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("practice")
    pr.add_argument("analysis", nargs="+")
    pr.add_argument("--exclude", required=True, help="the real coding sheet")
    pr.add_argument("--n", type=int, default=20)
    pr.add_argument("--seed", type=int, default=1)
    pr.add_argument("--out", required=True)
    pr.add_argument("--allow-stale", action="store_true")
    pk = sub.add_parser("packets")
    pk.add_argument("sheet")
    pk.add_argument("--out", required=True)
    pk.add_argument("--allow-stale", action="store_true")
    bl = sub.add_parser("blind", help="second-edition blinded sample (doc 10 §7)")
    bl.add_argument("analysis", nargs="+", help="analysis dirs holding rows.csv")
    bl.add_argument("--n", type=int, default=360)
    bl.add_argument("--seed", type=int, required=True, help="record it in doc 10")
    bl.add_argument("--out", required=True)
    bl.add_argument("--allow-stale", action="store_true")
    ag = sub.add_parser("agree", help="guarded kappa, confusion and adjudication")
    ag.add_argument("coder_a")
    ag.add_argument("coder_b")
    ag.add_argument("--key", required=True)
    ag.add_argument("--out", default=None)
    ag.add_argument("--accept-suspicious", action="store_true")
    args = ap.parse_args(argv)
    commands = {
        "practice": cmd_practice,
        "packets": cmd_packets,
        "blind": cmd_blind,
        "agree": cmd_agree,
    }
    return commands[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
