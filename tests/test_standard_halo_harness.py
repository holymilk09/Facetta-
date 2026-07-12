from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.run_standard_halo_full_e2e as harness  # noqa: E402
from facetta.image_identity import spec_visual_hash
from facetta.source_component_coverage import IndependentComponentAudit


def test_audit_only_stops_before_project_and_image_generation(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"evaluation-source")
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "SOURCE", source)

    def audit(image, coverage, *, spec, evidence_sink):
        assert image == b"evaluation-source"
        evidence_sink({
            "blind_inventory_pass": {"components": []},
            "independent_mapping_pass": {"component_audits": []},
        })
        components = tuple(
            component.model_copy(update={
                "independent_audit": IndependentComponentAudit(
                    kind="independent_component_audit",
                    verdict="pass",
                    auditor="audit-only-test.v1",
                    source_view=component.source_view,
                    observed_description=component.source_description,
                    evidence_sha256="a" * 64,
                ),
            })
            for component in coverage.components
        )
        return coverage.model_copy(update={
            "components": components,
            "audited_spec_visual_hash": spec_visual_hash(spec),
        })

    monkeypatch.setattr(harness, "audit_source_component_coverage", audit)
    monkeypatch.setattr(
        harness,
        "_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("audit-only must not create a project client")
        ),
    )

    harness.run("audit-only-test", audit_only=True)

    result = json.loads(
        (tmp_path / "docs/evals/audit-only-test/result.json").read_text()
    )
    assert result["stage"] == "source_coverage_audit_complete"
    assert result["source_coverage_blockers"] == []
    assert result["source_coverage_raw_evidence"]["blind_inventory_pass"] == {
        "components": [],
    }
    assert "no image generation" in result["provider_scope"]
