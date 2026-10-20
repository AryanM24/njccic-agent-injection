"""Support for the human check (doc 09 §6): a practice sheet and readable packets.

    human_coding.py practice ANALYSIS_DIR... --exclude SHEET --out DIR [--n 20]
    human_coding.py packets SHEET --out DIR

`practice` draws a calibration set that shares no run with the real sample,
half of it runs the scorers flagged, so coders see positives before the real
sheet. `packets` renders one Markdown page per sheet row with everything a
coder needs (case facts, every tool call, every email, both runs) and no score.

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

from analyze import CODED, write_csv
from inspect_ai.log import read_eval_log

from eduinject.analysis import CELL_FIELDS
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


def run_section(title: str, run: dict[str, Any]) -> list[str]:
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
            f"{i}. `{c.get('tool')}` {json.dumps(c.get('args', {}))} → {c.get('outcome')}"
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
    for stage, label in (
        ("h1", "Stage 1 (intake) output"),
        ("h2", "Stage 2 (analysis) output"),
        ("final", "Stage 3 final report"),
    ):
        lines += [f"### {label}", "", "```", text_of(pipe.get(stage)), "```", ""]
    return lines


def cmd_packets(args: argparse.Namespace) -> int:
    with open(args.sheet, newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("practice")
    pr.add_argument("analysis", nargs="+")
    pr.add_argument("--exclude", required=True, help="the real coding sheet")
    pr.add_argument("--n", type=int, default=20)
    pr.add_argument("--seed", type=int, default=1)
    pr.add_argument("--out", required=True)
    pk = sub.add_parser("packets")
    pk.add_argument("sheet")
    pk.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return cmd_practice(args) if args.cmd == "practice" else cmd_packets(args)


if __name__ == "__main__":
    sys.exit(main())
