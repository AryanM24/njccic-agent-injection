"""Build the paper: TikZ figures and appendix tables from aggregate results, then main.pdf.

    python paper/build.py            # use paper/figdata.json as is
    python paper/build.py --refresh  # re-extract figdata.json from logs/ first

figdata.json holds aggregate rates only (Tier 2, doc 05 §6). The by-technique
breakdowns are Tier 1 and are never read here.
"""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGS = HERE.parent / "logs"
DATA = HERE / "figdata.json"
GEN = HERE / "generated"
MODELS = {"openrouter/openai/gpt-6-luna": "Luna", "openrouter/deepseek/deepseek-v4-flash-0731": "DeepSeek"}
STAGES = ("intake", "analysis", "action")
WFS = ("w1", "w2", "w3")
SCOPES = ("read_only", "standard", "read_write")
COLOR = {"Luna": "luna", "DeepSeek": "deepseek"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def extract() -> dict:
    """Pull every number the figures and tables need from the analysis outputs under logs/."""
    attack, base, hashes = {}, {}, {}
    for name in ("analysis-attack-luna", "analysis-attack-deepseek", "analysis-baseline"):
        for r in _rows(LOGS / name / "rates.csv"):
            key = f"{MODELS[r['model']]}|{r['workflow']}|{r['scope']}|{r['isolated']}|{r['metric']}"
            val = [float(r["rate"]), float(r["ci_lo"]), float(r["ci_hi"]), float(r["epoch_range"] or 0)]
            (base if r["benign_only"] == "True" else attack)[key] = val
        for r in _rows(LOGS / name / "rows.csv"):
            cell = f"{MODELS[r['model']]}|{r['workflow']}|{r['scope']}|{r['isolated']}"
            kind = "baseline" if r["benign_only"] == "True" else "attack"
            hashes.setdefault(cell, {})[kind] = r["config_hash"]

    # Floor = largest baseline epoch range per model x workflow x metric (doc 09 §4, findings App. A).
    floors: dict[str, float] = {}
    for key, v in base.items():
        m, wf, _, _, metric = key.split("|")
        k = f"{m}|{wf}|{metric}"
        floors[k] = max(floors.get(k, 0.0), v[3])

    paired = []
    for line in (LOGS / "paired_outcomes.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 9 or cells[0] in ("Model", "---"):
            continue
        lo, hi = re.findall(r"[+-]\d\.\d+", cells[8])[1:3]
        paired.append({
            "model": cells[0], "wf": cells[1], "scope": cells[2], "iso": cells[3], "metric": cells[4],
            "attack": float(cells[6]), "twin": float(cells[7]),
            "diff": float(cells[8].split()[0]), "lo": float(lo), "hi": float(hi),
        })
    return {"attack": attack, "baseline": base, "floors": floors, "paired": paired, "hashes": hashes}


def spread(items: list[tuple[float, str]], gap: float) -> list[tuple[float, str]]:
    """Nudge label positions apart so no two sit closer than `gap`, keeping their order."""
    out: list[list] = []
    for y, t in sorted(items):
        if out and y - out[-1][0] < gap:
            y = out[-1][0] + gap
        out.append([y, t])
    return [(y, t) for y, t in out]


def fig_propagation(d: dict) -> str:
    """Marker rate at each stage, isolation off vs on, read_write scope, one panel per workflow."""
    names = {"w1": "W1: IT help desk", "w2": "W2: Applicant screening", "w3": "W3: Parent correspondence"}
    out = [r"\begin{tikzpicture}",
           r"\begin{groupplot}[group style={group size=3 by 1, horizontal sep=0.75cm, yticklabels at=edge left},",
           r"  width=4.75cm, height=5.2cm, ymin=-0.02, ymax=1.02, xmin=-0.15, xmax=2.15,",
           r"  xtick={0,1,2}, xticklabels={Intake,Analysis,Action}, ytick={0,0.25,0.5,0.75,1},",
           r"  yticklabels={0\%,25\%,50\%,75\%,100\%}, clip=false, figaxis]"]
    for wf in WFS:
        out.append(rf"\nextgroupplot[title={{{names[wf]}}}]")
        labels = []
        for m in ("DeepSeek", "Luna"):
            for iso in ("False", "True"):
                vals = [d["attack"][f"{m}|{wf}|read_write|{iso}|propagation.{s}"][0] for s in STAGES]
                style = f"{COLOR[m]}, " + ("isoon" if iso == "True" else "isooff")
                coords = " ".join(f"({j},{v:.3f})" for j, v in enumerate(vals))
                out.append(rf"\addplot[{style}] coordinates {{{coords}}};")
                labels.append((vals[2], f"{m} {'on' if iso == 'True' else 'off'}|{COLOR[m]}|{vals[2] * 100:.0f}"))
        if wf == WFS[-1]:  # direct labels on the last panel only; earlier panels share its line styles
            for ly, t in spread(labels, 0.075):
                lab, col, _ = t.split("|")
                out.append(rf"\node[dlabel, text={col}!70!black] at (axis cs:2.12,{ly:.3f}) {{{lab}}};")
    out += [r"\end{groupplot}", r"\end{tikzpicture}"]
    return "\n".join(out)


def forest_rows(d: dict) -> list[dict]:
    """Harm cells where the attack could move the rate. Saturated cells (either side exactly 0 or 1) are
    excluded from comparative claims by doc 04 §14 / doc 09 §5, so they are left out of the figure."""
    keep = [p for p in d["paired"] if p["metric"] in ("exfiltration", "unauthorized")
            and all(0 < p[s] < 1 for s in ("attack", "twin"))]
    order = {"DeepSeek": 0, "Luna": 1}
    keep.sort(key=lambda p: (order[p["model"]], p["wf"], p["metric"], SCOPES.index(p["scope"]), p["iso"]))
    for p in keep:
        metric = "authorization" if p["metric"] == "unauthorized" else p["metric"]
        p["floor"] = d["floors"][f"{p['model']}|{p['wf']}|{metric}"]
        p["effect"] = abs(p["diff"]) > p["floor"] and (p["lo"] > 0 or p["hi"] < 0)
    return keep


def fig_forest(d: dict) -> str:
    """Paired attack minus twin harm differences with 95% intervals against each cell's noise floor."""
    rows = forest_rows(d)
    n = len(rows)
    metric_name = {"exfiltration": "leak", "unauthorized": "unauthorized action"}
    scope = {"standard": "standard", "read_write": "read-write"}
    out = [r"\begin{tikzpicture}[x=22cm, y=-0.56cm]"]
    lo_x, hi_x, harm_w = -0.105, 0.16, "2.5cm"
    for g in (-0.10, -0.05, 0.0, 0.05, 0.10, 0.15):
        style = "axisline" if g == 0 else "gridline"
        out.append(rf"\draw[{style}] ({g},-0.6) -- ({g},{n - 0.4});")
        out.append(rf"\node[tick, below] at ({g},{n - 0.4}) {{{f'{g * 100:+.0f}'.replace('-', '−')}}};")
    out.append(rf"\node[tick] at (0.03,{n + 0.9}) {{Attack minus twin, percentage points}};")
    out.append(rf"\node[colhead, anchor=east, xshift=-{harm_w}] at ({lo_x},-1.1) {{Model, workflow, scope, isolation}};")
    out.append(rf"\node[colhead, anchor=east] at ({lo_x},-1.1) {{Harm}};")
    prev = None
    for i, p in enumerate(rows):
        grp = (p["model"], p["wf"])
        if prev and grp != prev:
            out.append(rf"\draw[sepline] ([xshift=-7.2cm]{lo_x},{i - 0.5}) -- ({hi_x},{i - 0.5});")
        prev = grp
        f = p["floor"]
        out.append(rf"\fill[floorband] ({max(-f, lo_x)},{i - 0.3}) rectangle ({min(f, hi_x)},{i + 0.3});")
        label = f"{p['model']}, {p['wf'].upper()}, {scope[p['scope']]}, isolation {p['iso']}"
        out.append(rf"\node[rowlab, anchor=east, xshift=-{harm_w}] at ({lo_x},{i}) {{{label}}};")
        out.append(rf"\node[rowlab, anchor=east, text=muted] at ({lo_x},{i}) {{{metric_name[p['metric']]}}};")
        c = COLOR[p["model"]]
        out.append(rf"\draw[{c}, line width=1.1pt] ({p['lo']},{i}) -- ({p['hi']},{i});")
        r = "2.6pt" if p["effect"] else "2.1pt"
        out.append(rf"\fill[{c}, draw=white, line width=0.8pt] ({p['diff']},{i}) circle ({r});")
        if p["effect"]:
            out.append(rf"\node[callout, anchor=west] at ({p['hi'] + 0.004},{i}) {{{p['diff'] * 100:+.1f} pts, above floor}};")
    out.append(r"\end{tikzpicture}")
    return "\n".join(out)


def fig_isolation(d: dict) -> str:
    """W1 clean-ticket task completion and unauthorized actions, isolation off vs on."""
    # Separate measures, so each panel gets its own y range (not a dual axis).
    panels = [("control_check.legit_task_completed", "Legitimate request completed", 1.0),
              ("authorization", "Unauthorized reset or unlock", 0.3)]
    out = [r"\begin{tikzpicture}",
           r"\begin{groupplot}[group style={group size=2 by 1, horizontal sep=3.9cm},",
           r"  width=5.0cm, height=5.0cm, ymin=-0.02, ymax=1.02, xmin=-0.2, xmax=1.2,",
           r"  xtick={0,1}, xticklabels={Isolation off,Isolation on}, ytick={0,0.25,0.5,0.75,1},",
           r"  yticklabels={0\%,25\%,50\%,75\%,100\%}, clip=false, figaxis]"]
    for metric, name, top in panels:
        ticks = [top * k / 4 for k in range(5)] if top == 1.0 else [0, 0.1, 0.2, 0.3]
        out.append(rf"\nextgroupplot[title={{{name}}}, ymin={-0.02 * top}, ymax={1.02 * top}, "
                   rf"ytick={{{','.join(f'{t:g}' for t in ticks)}}}, "
                   rf"yticklabels={{{','.join(f'{t * 100:.0f}\\%' for t in ticks)}}}]")
        labels = []
        for m in ("Luna", "DeepSeek"):
            for sc in ("read_write", "standard"):
                a = d["baseline"][f"{m}|w1|{sc}|False|{metric}"][0]
                b = d["baseline"][f"{m}|w1|{sc}|True|{metric}"][0]
                style = f"{COLOR[m]}, " + ("isoon" if sc == "read_write" else "isooff")
                out.append(rf"\addplot[{style}] coordinates {{(0,{a:.3f}) (1,{b:.3f})}};")
                labels.append((b, f"{m}, {sc.replace('_', '-')}|{COLOR[m]}|{b * 100:.0f}"))
        for ly, t in spread(labels, 0.075 * top):
            lab, col, pct = t.split("|")
            out.append(rf"\node[dlabel, text={col}!70!black] at (axis cs:1.1,{ly:.3f}) {{{lab} {{\color{{muted}}{pct}\%}}}};")
    out += [r"\end{groupplot}", r"\end{tikzpicture}"]
    return "\n".join(out)


def table_propagation(d: dict) -> str:
    """Appendix table: marker rate per stage, every attack cell, with 95% intervals for the action stage."""
    out = []
    for m in ("Luna", "DeepSeek"):
        for wf in WFS:
            for sc in SCOPES:
                cells = []
                for iso in ("False", "True"):
                    k = f"{m}|{wf}|{sc}|{iso}|propagation."
                    i, a = d["attack"][k + "intake"][0], d["attack"][k + "analysis"][0]
                    act = d["attack"][k + "action"]
                    cells += [f"{i:.2f}", f"{a:.2f}", f"{act[0]:.2f} [{act[1]:.2f}, {act[2]:.2f}]"]
                out.append(f"{m} & {wf.upper()} & {sc.replace('_', '-')} & " + " & ".join(cells) + r" \\")
            out.append(r"\addlinespace[2pt]")
    head = (r"\begin{tabular}{@{}lll ccc ccc@{}}" "\n" r"\toprule" "\n"
            r"& & & \multicolumn{3}{c}{Isolation off} & \multicolumn{3}{c}{Isolation on} \\" "\n"
            r"\cmidrule(lr){4-6}\cmidrule(l){7-9}" "\n"
            r"Model & WF & Scope & Intake & Analysis & Action [95\% CI] & Intake & Analysis & Action [95\% CI] \\" "\n"
            r"\midrule")
    return "\n".join([head, *out[:-1], r"\bottomrule", r"\end{tabular}"])


def table_hashes(d: dict) -> str:
    """Appendix table: config hash of every cell, baseline and attack, Luna and DeepSeek side by side."""
    out = [r"\begin{tabular}{@{}lll ll ll@{}}", r"\toprule",
           r"& & & \multicolumn{2}{c}{Luna} & \multicolumn{2}{c}{DeepSeek} \\",
           r"\cmidrule(lr){4-5}\cmidrule(l){6-7}",
           r"WF & Scope & Isolation & Baseline & Attack & Baseline & Attack \\", r"\midrule"]
    for wf in WFS:
        for sc in SCOPES:
            for iso in ("False", "True"):
                cells = [rf"\texttt{{{d['hashes'][f'{m}|{wf}|{sc}|{iso}'][k]}}}"
                         for m in ("Luna", "DeepSeek") for k in ("baseline", "attack")]
                out.append(f"{wf.upper()} & {sc.replace('_', '-')} & {'on' if iso == 'True' else 'off'} & "
                           + " & ".join(cells) + r" \\")
        out.append(r"\addlinespace[2pt]")
    return "\n".join([*out[:-1], r"\bottomrule", r"\end{tabular}"])


def main() -> None:
    if "--refresh" in sys.argv or not DATA.exists():
        DATA.write_text(json.dumps(extract(), indent=1, sort_keys=True))
    d = json.loads(DATA.read_text())
    GEN.mkdir(exist_ok=True)
    for name, text in {"fig_propagation": fig_propagation(d), "fig_forest": fig_forest(d),
                       "fig_isolation": fig_isolation(d), "tab_propagation": table_propagation(d),
                       "tab_hashes": table_hashes(d)}.items():
        (GEN / f"{name}.tex").write_text(text + "\n")
    subprocess.run(["tectonic", "--keep-logs", "main.tex"], cwd=HERE, check=True)
    print("wrote", HERE / "main.pdf")


if __name__ == "__main__":
    main()
