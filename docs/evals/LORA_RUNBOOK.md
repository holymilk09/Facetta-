# LoRA training & three-engine comparison — runbook

The LoRA pipeline is built and tested. Training needs one live step that this
sandbox's network policy blocks, so it runs either after the policy is opened
or from any machine with fal access. Inference (the `flux_lora` engine) is
unaffected — it rides `fal.run`.

## What trains on what

- **`data/train/bootstrap/`** — generated Grok/FLUX renders, curated by
  `is_style_worthy`. Training on these MEASURES what a LoRA does; it style-locks
  FLUX to a look but cannot beat Grok (you are distilling Grok). Use it to
  quantify the effect, not as the moat.
- **`data/train/approved/`** — the designer's REAL approvals, produced by
  `scripts/export_training_set.py` (pinned or accepted assets). This is the
  moat: genuine house style, no circular distillation. Train on this once
  ~30+ images have accrued.

## The one network requirement

fal's trainer must fetch the images from a URL, so the archive is uploaded to
fal storage first. That needs these hosts allowed (this sandbox blocks them):

    rest.alpha.fal.ai      (storage upload)
    queue.fal.run          (async training queue, if used)

Open them in the environment's network policy (Claude Code web → environment
settings), OR run the training step from an unrestricted machine.

## Train

    uv run python -c "from pathlib import Path; \
      from facetta.tuning import train_style_lora; \
      print(train_style_lora(sorted(Path('data/train/bootstrap').glob('*.jpg'))))"

This uploads the set, trains a FLUX style LoRA, and writes `data/loras.json`
(the `flux_lora` engine reads it; its URL is part of the cache key, so a
retrain is never served stale). Swap in `data/train/approved` for the real run.

## Compare the three engines

    uv run python scripts/run_engine_eval.py lora grok_direct,flux,flux_lora

Same specs, same edits, scored identically — Grok vs FLUX vs FLUX+house-LoRA.
Writes `docs/evals/lora/report.md` + `board.html`.

## Accrue the real training set (ongoing)

    uv run python scripts/export_training_set.py            # product shots only
    uv run python scripts/export_training_set.py --include-worn

Prints a manifest: how many approved images were kept, and every one dropped
WITH its reason (never a silent cap). Run it as approvals accumulate; train
when it reports 30+.
