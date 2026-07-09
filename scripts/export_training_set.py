"""Export the designer's approved images into a LoRA training set.

An asset counts as approved when it is pinned or carries an `accepted`
feedback verdict. Run this as approvals accrue; when the manifest reports
~30+ kept, feed the output directory straight to train_style_lora — that
set is the house-style moat (real approvals, no circular distillation).

Usage:
    uv run python scripts/export_training_set.py [out-dir] [--include-worn]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from facetta.db import get_engine  # noqa: E402
from facetta.tuning import export_approved_training_set  # noqa: E402


def main() -> None:
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out_dir = Path(args[0]) if args else Path("data/train/approved")
    product_only = "--include-worn" not in flags

    db = sessionmaker(bind=get_engine(), autoflush=False)()
    try:
        manifest = export_approved_training_set(
            db, out_dir, product_only=product_only)
    finally:
        db.close()

    print(f"kept {manifest['kept']} approved images -> {manifest['out_dir']}")
    if manifest["dropped"]:
        print(f"dropped {len(manifest['dropped'])} (reported, never silent):")
        for d in manifest["dropped"]:
            print(f"  - {d['id']}: {d['reason']}")
    if manifest["kept"] < 30:
        print(f"\n{manifest['kept']}/~30 - keep accruing approvals before "
              "training; a thin set makes a weak LoRA.")
    else:
        print(f"\nready to train on {manifest['out_dir']} "
              "(see docs/evals/LORA_RUNBOOK.md)")


if __name__ == "__main__":
    main()
