"""Run the engine evaluation live: same specs, same edits, every engine,
scored identically. Research tooling — writes docs/evals/<run-name>/ with the
raw images, a markdown report, and a side-by-side HTML board.

Usage:
    uv run python scripts/run_engine_eval.py <run-name> [gen-engines] [edit-engines]

Defaults: gen-engines=grok_direct,flux  edit-engines=grok_direct,flux_kontext
(comma-separated; add flux_lora once a LoRA is trained and registered).
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from facetta.evals import (  # noqa: E402
    score_edit_fidelity, score_spec_conformance, summarize_engine_scores,
)
from facetta.render import RenderUnavailable, edit_image, render_from_spec  # noqa: E402
from facetta.spec import Spec  # noqa: E402
from facetta.specagent import compile_localized_edit_instruction  # noqa: E402

GOLDEN_SPECS = [
    "ruby_sunburst_ring",
    "marquise_drop_earring",
    "aurora_pendant",
    "leaf_spray_brooch",
    "concept_emerald_halo",
]

# the canonical edit trio: stone swap, proportion change, material change —
# each engine gets the IDENTICAL compiled instruction on the IDENTICAL source
CANONICAL_EDITS = [
    ("the centre stone", "replace the ruby with a blue sapphire",
     "the centre ruby becomes a blue sapphire"),
    ("the band", "make the band visibly wider and more substantial",
     "the band is visibly wider"),
    ("the metal surfaces", "change all the metal to yellow gold",
     "the metal becomes yellow gold"),
]


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    gen_engines = (sys.argv[2] if len(sys.argv) > 2
                   else "grok_direct,flux").split(",")
    edit_engines = (sys.argv[3] if len(sys.argv) > 3
                    else "grok_direct,flux_kontext").split(",")

    root = Path(__file__).parent.parent
    outdir = root / "docs" / "evals" / run
    outdir.mkdir(parents=True, exist_ok=True)
    examples = root / "docs" / "examples"

    rows: list[dict] = []
    cells: dict[tuple[str, str], dict] = {}   # (item, engine) -> {img, score}

    # --- generation: every golden spec through every generation engine ---
    for name in GOLDEN_SPECS:
        spec = Spec.model_validate(json.loads((examples / f"{name}.json").read_text()))
        for engine in gen_engines:
            label = f"render:{name}"
            try:
                image, cached = render_from_spec(spec, model=engine)
                result = score_spec_conformance(spec, image)
            except RenderUnavailable as exc:
                print(f"[FAIL] {label} via {engine}: {exc}")
                rows.append({"engine": engine, "kind": "render", "item": name,
                             "score": 0.0, "error": str(exc)})
                continue
            path = outdir / f"{name}--{engine}.png"
            path.write_bytes(image)
            rows.append({"engine": engine, "kind": "render", "item": name,
                         "score": result["score"],
                         "components": result["components"]})
            cells[(label, engine)] = {"img": path.name, "score": result["score"]}
            print(f"[ok] {label:44s} {engine:14s} score={result['score']:5.1f} "
                  f"(cached={cached}) {result['components']}")

    # --- edits: one shared source per engine comparison ---
    src_spec = Spec.model_validate(
        json.loads((examples / "ruby_sunburst_ring.json").read_text()))
    source, _ = render_from_spec(src_spec, model="grok_direct")
    (outdir / "edit-source.png").write_bytes(source)

    for region, change, intended in CANONICAL_EDITS:
        instruction = compile_localized_edit_instruction(region, change)
        item = f"edit:{change[:32]}"
        for engine in edit_engines:
            try:
                edited, cached = edit_image(source, instruction, engine)
                result = score_edit_fidelity(source, edited, intended)
            except RenderUnavailable as exc:
                print(f"[FAIL] {item} via {engine}: {exc}")
                rows.append({"engine": engine, "kind": "edit", "item": item,
                             "score": 0.0, "error": str(exc)})
                continue
            path = outdir / f"{_safe(change)}--{engine}.png"
            path.write_bytes(edited)
            rows.append({"engine": engine, "kind": "edit", "item": item,
                         "score": result["score"],
                         "applied": result["change_applied"],
                         "severity": result["severity"],
                         "unintended": result["unintended_changes"]})
            cells[(item, engine)] = {"img": path.name, "score": result["score"]}
            print(f"[ok] {item:44s} {engine:14s} score={result['score']:5.1f} "
                  f"applied={result['change_applied']} drift={result['severity']}")

    summary = summarize_engine_scores(rows)
    (outdir / "results.json").write_text(json.dumps(
        {"run": run, "summary": summary, "rows": rows}, indent=1))
    _write_report(outdir, run, summary, rows)
    _write_board(outdir, run, summary, cells,
                 gen_engines=gen_engines, edit_engines=edit_engines)
    print("\n=== SUMMARY ===")
    for engine, s in summary.items():
        print(f"  {engine:14s} render_avg={s['render_avg']} "
              f"edit_avg={s['edit_avg']} runs={s['runs']}")
    print(f"\nreport: {outdir / 'report.md'}\nboard:  {outdir / 'board.html'}")


def _safe(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower())[:40]


def _write_report(outdir: Path, run: str, summary: dict, rows: list[dict]) -> None:
    lines = [f"# Engine evaluation — {run}", "",
             "Same specs, same instructions, scored identically. "
             "Spec conformance = vision read of the output compared against "
             "the validated record (species, metal, counts, carat, size). "
             "Edit fidelity = intended change applied × rest held static.", "",
             "## Summary", "", "| engine | render avg | edit avg | runs |",
             "|---|---|---|---|"]
    for engine, s in summary.items():
        lines.append(f"| {engine} | {s['render_avg']} | {s['edit_avg']} | {s['runs']} |")
    lines += ["", "## Every run", "",
              "| item | engine | kind | score | detail |", "|---|---|---|---|---|"]
    for r in rows:
        detail = r.get("error") or r.get("components") or \
            f"applied={r.get('applied')} drift={r.get('severity')}"
        lines.append(f"| {r['item']} | {r['engine']} | {r['kind']} | "
                     f"{r['score']} | {detail} |")
    (outdir / "report.md").write_text("\n".join(lines) + "\n")


def _write_board(outdir: Path, run: str, summary: dict,
                 cells: dict, *, gen_engines: list[str],
                 edit_engines: list[str]) -> None:
    engines = list(dict.fromkeys(gen_engines + edit_engines))
    items = list(dict.fromkeys(item for item, _ in cells))
    head = "".join(f"<th>{e}</th>" for e in engines)
    body = []
    for item in items:
        tds = []
        for e in engines:
            cell = cells.get((item, e))
            if cell is None:
                tds.append("<td>—</td>")
                continue
            b64 = base64.b64encode((outdir / cell["img"]).read_bytes()).decode()
            tds.append(f"<td><div class='s'>{cell['score']}</div>"
                       f"<img src='data:image/png;base64,{b64}'/></td>")
        body.append(f"<tr><th class='r'>{item}</th>{''.join(tds)}</tr>")
    srows = "".join(f"<tr><td>{e}</td><td>{s['render_avg']}</td>"
                    f"<td>{s['edit_avg']}</td></tr>" for e, s in summary.items())
    (outdir / "board.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Engine eval — {run}</title>
<style>
 body{{font-family:system-ui;margin:24px;background:#fafafa;color:#222}}
 table{{border-collapse:collapse}} td,th{{border:1px solid #ddd;padding:8px;
 vertical-align:top;background:#fff}} img{{width:260px;display:block}}
 .s{{font-weight:700;margin-bottom:4px}} .r{{text-align:left;max-width:160px}}
 h1{{font-size:20px}}
</style>
<h1>Engine evaluation — {run}</h1>
<table><tr><th>engine</th><th>render avg</th><th>edit avg</th></tr>{srows}</table>
<br>
<table><tr><th></th>{head}</tr>{''.join(body)}</table>
""")


if __name__ == "__main__":
    main()
