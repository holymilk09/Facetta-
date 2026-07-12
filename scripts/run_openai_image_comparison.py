"""Run one explicit GPT Image comparison through Facetta's jewelry QA.

This is an internal evaluation route, not a user-facing model picker and not a
change to the Grok-primary product policy.  The default case isolates the
face-up head in founder reference image-112, masks only its center stone and
touching prongs, and asks GPT Image 2 to change the oval center cut to an
emerald cut.  Facetta supplies the native alpha mask, composites the generated
patch back inside that mask, and runs the same localized-edit QA used by the
trusted workflow.

Preflight is free and is the default. A live request requires the explicit
``--confirm-paid-provider-call`` flag.  Results are evaluation evidence only;
no Project, Design, DesignVersion, or ImageAsset is created.

Usage::

    PYTHONPATH=src uv run python scripts/run_openai_image_comparison.py RUN_NAME
    PYTHONPATH=src uv run python scripts/run_openai_image_comparison.py RUN_NAME \
        --confirm-paid-provider-call
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from facetta.config import load_env_file  # noqa: E402
from facetta.image_agent import (  # noqa: E402
    ImageAgentError,
    ImageOperation,
    JewelryImageAgent,
    OpenAIImageProvider,
    RingQualityEvaluator,
    build_image_plan,
    openai_route_for_plan,
)
from facetta.image_agent.prompts import compile_initial_prompt  # noqa: E402
from facetta.image_region import crop_normalized_region  # noqa: E402
from facetta.image_identity import spec_visual_hash  # noqa: E402
from facetta.ring_evals import (  # noqa: E402
    CANONICAL_RING_EDITS,
    apply_canonical_ring_edit,
)
from facetta.spec import Spec  # noqa: E402
from facetta.source_component_coverage import (  # noqa: E402
    source_component_factory_blockers,
)
from facetta.source_component_resolution import (  # noqa: E402
    valid_source_component_spec_paths,
)

DEFAULT_SOURCE = Path(
    "/Users/mattfb/.codex/attachments/"
    "c2fd41d0-b236-43ef-ada9-e9479718c771/image-112.jpg"
)
DEFAULT_SPEC = (
    ROOT / "docs" / "evals"
    / "designer-standard-halo-full-e2e-live-v11-2026-07-11"
    / "audited-estimated-spec.json"
)
SOURCE_REGION = {"x": 0.08, "y": 0.12, "width": 0.55, "height": 0.38}
EDIT_ID = "center-cut-shape"
TEST_ACTOR = "usr_openai_comparison_test_actor_unapproved"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _edit_case():
    return next(edit for edit in CANONICAL_RING_EDITS if edit.id == EDIT_ID)


def _center_mask(source: bytes) -> bytes:
    """Select center stone plus touching prongs, excluding the halo run."""

    image = Image.open(BytesIO(source))
    width, height = image.size
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (
            round(width * 0.23),
            round(height * 0.22),
            round(width * 0.53),
            round(height * 0.65),
        ),
        radius=max(8, round(min(width, height) * 0.035)),
        fill=255,
    )
    output = BytesIO()
    mask.save(output, format="PNG")
    return output.getvalue()


def _prepare(source_path: Path, spec_path: Path) -> dict[str, Any]:
    source_full = source_path.read_bytes()
    source = crop_normalized_region(source_full, **SOURCE_REGION)
    source_spec = Spec.model_validate(json.loads(spec_path.read_text()))
    source_spec_blockers = source_component_factory_blockers(
        source_spec.source_component_coverage,
        valid_spec_paths=valid_source_component_spec_paths(source_spec),
        current_spec_visual_hash=spec_visual_hash(source_spec),
    )
    edit = _edit_case()
    target_spec, issues = apply_canonical_ring_edit(source_spec, edit)
    if target_spec is None or issues:
        raise RuntimeError(
            "comparison target spec is invalid: " + json.dumps(issues)
        )
    mask = _center_mask(source)
    plan = build_image_plan(
        ImageOperation.LOCAL_EDIT,
        edit.instruction,
        spec=target_spec,
        source_spec=source_spec,
        source_image=source,
        mask_bytes=mask,
        region_description=(
            "only the center-stone body and its immediately touching six "
            "prong seats in the selected face-up ring-head view; exclude the "
            "complete halo run and every pixel outside the saved mask"
        ),
        frozen=edit.frozen_facts,
        style_constraints=(
            "retain the exact source drawing medium, lighting, view, scale, "
            "and background",
        ),
        expected_output=(
            "the same face-up ring-head drawing with only the oval center "
            "stone changed to an emerald cut and the six touching prong seats "
            "adjusted as needed; halo and all outside-mask pixels unchanged"
        ),
        variant=0,
        allow_fallback=False,
    )
    return {
        "source": source,
        "mask": mask,
        "source_spec": source_spec,
        "target_spec": target_spec,
        "plan": plan,
        "prompt": compile_initial_prompt(plan),
        "edit": edit,
        "source_spec_blockers": source_spec_blockers,
    }


def run(
    run_name: str,
    *,
    source_path: Path = DEFAULT_SOURCE,
    spec_path: Path = DEFAULT_SPEC,
    confirm_paid_provider_call: bool = False,
    quality: str = "low",
    max_attempts: int = 1,
) -> dict[str, Any]:
    if not 1 <= max_attempts <= 2:
        raise ValueError("OpenAI comparison max_attempts must be one or two")
    outdir = ROOT / "docs" / "evals" / run_name
    outdir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare(source_path, spec_path)
    (outdir / "source-crop.jpg").write_bytes(prepared["source"])
    (outdir / "approved-edit-mask.png").write_bytes(prepared["mask"])
    _write_json(
        outdir / "source-spec.json",
        prepared["source_spec"].model_dump(mode="json"),
    )
    _write_json(
        outdir / "target-spec.json",
        prepared["target_spec"].model_dump(mode="json"),
    )
    preflight: dict[str, Any] = {
        "run_name": run_name,
        "mode": "live" if confirm_paid_provider_call else "preflight",
        "provider_calls": 0,
        "project_records_created": 0,
        "source": str(source_path),
        "source_region": SOURCE_REGION,
        "spec": str(spec_path),
        "edit_id": EDIT_ID,
        "test_actor": TEST_ACTOR,
        "founder_approval": False,
        "designer_approval": False,
        "gia_cofounder_approval": False,
        "product_asset_persisted": False,
        "warning_auto_accepted": False,
        "attempt_limit": max_attempts,
        "quality": quality,
        "plan": prepared["plan"].model_dump(mode="json"),
        "compiled_prompt": prepared["prompt"],
        "isolation_policy": (
            "Native alpha mask plus Facetta patch compositing. Pixels outside "
            "the internal white-edit mask come from the immutable source raster."
        ),
        "disclosure": (
            "Internal provider comparison only. All dimensions/spec facts are "
            "test-designer estimates and no output is manufacturing approval."
        ),
        "source_spec_blockers": [
            blocker.model_dump(mode="json")
            for blocker in prepared["source_spec_blockers"]
        ],
    }
    if prepared["source_spec_blockers"]:
        preflight["status"] = "source_spec_audit_required"
        _write_json(outdir / "results.json", preflight)
        return preflight
    if not confirm_paid_provider_call:
        preflight["status"] = "paid_call_confirmation_required"
        _write_json(outdir / "results.json", preflight)
        return preflight

    load_env_file(ROOT / ".env")
    plan = prepared["plan"]
    route = openai_route_for_plan(plan)
    provider = OpenAIImageProvider(quality=quality)
    agent = JewelryImageAgent(
        provider,
        RingQualityEvaluator(),
        attempt_routes=(route,) * max_attempts,
    )
    try:
        generated = agent.run(
            plan,
            source_image=prepared["source"],
            mask_bytes=prepared["mask"],
        )
    except ImageAgentError as exc:
        preflight.update({
            "status": "comparison_failed",
            "provider_calls": len(exc.attempts),
            "error": exc.as_dict(),
            "attempts": [
                attempt.model_dump(mode="json") for attempt in exc.attempts
            ],
        })
        _write_json(outdir / "results.json", preflight)
        return preflight

    (outdir / "qa-candidate.png").write_bytes(generated.image_bytes)
    preflight.update({
        "status": (
            "qa_pass_not_human_approved"
            if generated.accepted else "designer_review_required"
        ),
        "provider_calls": len(generated.run.attempts),
        "run": generated.run.model_dump(mode="json"),
        "quality_report": generated.quality.model_dump(mode="json"),
        "candidate_file": "qa-candidate.png",
        "product_asset_persisted": False,
    })
    _write_json(outdir / "results.json", preflight)
    return preflight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_name")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument(
        "--confirm-paid-provider-call",
        action="store_true",
        help="authorize the direct OpenAI request and independent vision QA",
    )
    parser.add_argument(
        "--quality", choices=("low", "medium", "high"), default="low"
    )
    parser.add_argument("--max-attempts", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    result = run(
        args.run_name,
        source_path=args.source,
        spec_path=args.spec,
        confirm_paid_provider_call=args.confirm_paid_provider_call,
        quality=args.quality,
        max_attempts=args.max_attempts,
    )
    print(json.dumps({
        "status": result["status"],
        "output": str(ROOT / "docs" / "evals" / args.run_name),
        "provider_calls": result["provider_calls"],
    }, indent=2))


if __name__ == "__main__":
    main()
