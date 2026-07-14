from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from facetta.blind_jewelry_review import (
    GIA_VISUAL_FIDELITY_ROLE,
    INDEPENDENT_DESIGNER_ROLE,
    build_blind_review_packet,
    validate_signed_review_ledger,
)
from facetta.blind_review_ledger_authoring import (
    BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA,
    EnrolledBlindReviewer,
    author_signed_blind_review_ledger,
    build_blind_review_authoring_template,
    load_enrolled_blind_reviewer,
)


ROOT = Path(__file__).resolve().parents[1]


def _packet(
    *,
    role: str = GIA_VISUAL_FIDELITY_ROLE,
    candidate_sha256: str = "2" * 64,
    config_sha256: str = "8" * 64,
) -> dict[str, object]:
    return build_blind_review_packet(
        corpus_run_id="ledger-authoring-fixture",
        manifest_sha256="7" * 64,
        config_sha256=config_sha256,
        workload_sha256="9" * 64,
        capture_sha256="a" * 64,
        reviewer_role=role,
        review_seed="b" * 64,
        selected_items=[{
            "kind": "render",
            "operation_class": "render_conformance",
            "intent": {
                "intended_change": "Render the exact reviewed solitaire.",
                "target_region": None,
                "frozen_facts": ["round center stone", "four prongs"],
            },
            "source": {"path": "sources/ring.png", "sha256": "1" * 64},
            "candidate": {
                "path": "review/render.png", "sha256": candidate_sha256,
            },
            "mask": None,
        }],
    )


def _enrollment(
    repository_root: Path,
    private_key: Ed25519PrivateKey,
    *,
    role: str = GIA_VISUAL_FIDELITY_ROLE,
    profile_sha256: str = "c" * 64,
) -> tuple[dict[str, object], EnrolledBlindReviewer]:
    repository_root.mkdir(parents=True, exist_ok=True)
    public_path = repository_root / f"{role}.pub"
    public_path.write_bytes(private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw,
    ))
    config_key = (
        "reviewer_public_key"
        if role == GIA_VISUAL_FIDELITY_ROLE
        else "designer_reviewer_public_key"
    )
    config = {
        config_key: {
            "key_id": f"{role}-key-v1",
            "path": public_path.name,
            "sha256": hashlib.sha256(public_path.read_bytes()).hexdigest(),
            "reviewer_profile_sha256": profile_sha256,
        },
    }
    return config, load_enrolled_blind_reviewer(
        config,
        reviewer_role=role,
        repository_root=repository_root,
    )


def _private_key_file(
    path: Path,
    key: Ed25519PrivateKey,
    *,
    pem: bool = False,
) -> Path:
    path.write_bytes(key.private_bytes(
        Encoding.PEM if pem else Encoding.Raw,
        PrivateFormat.PKCS8 if pem else PrivateFormat.Raw,
        NoEncryption(),
    ))
    path.chmod(0o600)
    return path


def _canonical_config_file(
    repository_root: Path,
    config: dict[str, object],
) -> tuple[Path, str]:
    path = repository_root / "docs/evals/frozen-founder-corpus-v1/config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _completed(template: dict[str, object]) -> dict[str, object]:
    result = deepcopy(template)
    review = result["review"]
    review["reviewer_id"] = "reviewer_opaque_17"
    review["review_timezone"] = "Asia/Shanghai"
    review["reviewed_at"] = "2026-07-15T18:30:00+08:00"
    for decision in review["decisions"]:
        for criterion in decision["criteria"]:
            criterion["rating"] = "pass"
            criterion["rationale"] = None
    return result


def test_template_derives_exact_packet_artifact_criterion_and_reviewer_bindings(
    tmp_path: Path,
) -> None:
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(tmp_path / "repo", key)
    packet = _packet()

    template = build_blind_review_authoring_template(packet, reviewer=reviewer)

    assert template["schema_version"] == BLIND_REVIEW_AUTHORING_TEMPLATE_SCHEMA
    binding = template["bindings"]
    packet_item = packet["items"][0]
    item = binding["items"][0]
    assert binding["reviewer_role"] == GIA_VISUAL_FIDELITY_ROLE
    assert binding["reviewer_key_id"] == reviewer.key_id
    assert binding["reviewer_profile_sha256"] == "c" * 64
    assert item["item_id"] == packet_item["item_id"]
    assert item["selected_source_sha256"] == "1" * 64
    assert item["selected_candidate_sha256"] == "2" * 64
    assert item["criterion_ids"] == [
        row["criterion_id"] for row in packet_item["criteria"]
    ]
    assert "accepted" not in json.dumps(template).lower()


@pytest.mark.parametrize(
    "role", [GIA_VISUAL_FIDELITY_ROLE, INDEPENDENT_DESIGNER_ROLE],
)
@pytest.mark.parametrize("pem", [False, True])
def test_completed_form_signs_and_immediately_self_verifies_for_both_roles(
    tmp_path: Path,
    role: str,
    pem: bool,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key, role=role)
    private_path = _private_key_file(tmp_path / "reviewer.key", key, pem=pem)
    packet = _packet(role=role)
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )

    ledger, validation = author_signed_blind_review_ledger(
        packet,
        completed,
        reviewer=reviewer,
        private_key_path=private_path,
        repository_root=repository_root,
        evidence_root=evidence_root,
    )

    assert validation["status"] == "pass"
    assert validation["signature_status"] == "verified"
    assert validation["accepted_count"] == 1
    assert ledger["reviewer_role"] == role
    assert set(ledger["decisions"][0]) == {
        "item_id",
        "selected_source_sha256",
        "selected_candidate_sha256",
        "selected_mask_sha256",
        "criteria",
    }


def test_signing_rejects_missing_extra_criteria_and_asserted_acceptance(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key)
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    packet = _packet()
    baseline = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )

    missing = deepcopy(baseline)
    missing["review"]["decisions"][0]["criteria"].pop()
    with pytest.raises(ValueError, match="criterion count differs"):
        author_signed_blind_review_ledger(
            packet, missing, reviewer=reviewer, private_key_path=private_path,
            repository_root=repository_root, evidence_root=evidence_root,
        )

    extra = deepcopy(baseline)
    extra["review"]["decisions"][0]["criteria"].append({
        "criterion_id": "extra", "rating": "pass", "rationale": None,
    })
    with pytest.raises(ValueError, match="criterion count differs"):
        author_signed_blind_review_ledger(
            packet, extra, reviewer=reviewer, private_key_path=private_path,
            repository_root=repository_root, evidence_root=evidence_root,
        )

    asserted = deepcopy(baseline)
    asserted["review"]["decisions"][0]["accepted"] = True
    with pytest.raises(ValueError, match="cannot assert accepted booleans"):
        author_signed_blind_review_ledger(
            packet, asserted, reviewer=reviewer, private_key_path=private_path,
            repository_root=repository_root, evidence_root=evidence_root,
        )


def test_signing_rejects_packet_artifact_role_profile_key_and_timezone_drift(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key)
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    packet = _packet()
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )

    artifact_drift = deepcopy(completed)
    artifact_drift["bindings"]["items"][0]["selected_candidate_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="bindings differ"):
        author_signed_blind_review_ledger(
            packet, artifact_drift, reviewer=reviewer,
            private_key_path=private_path, repository_root=repository_root,
            evidence_root=evidence_root,
        )

    with pytest.raises(ValueError, match="bindings differ"):
        author_signed_blind_review_ledger(
            _packet(candidate_sha256="e" * 64), completed, reviewer=reviewer,
            private_key_path=private_path, repository_root=repository_root,
            evidence_root=evidence_root,
        )

    wrong_role = deepcopy(completed)
    wrong_role["bindings"]["reviewer_role"] = INDEPENDENT_DESIGNER_ROLE
    with pytest.raises(ValueError, match="bindings differ"):
        author_signed_blind_review_ledger(
            packet, wrong_role, reviewer=reviewer, private_key_path=private_path,
            repository_root=repository_root, evidence_root=evidence_root,
        )

    _config, changed_profile = _enrollment(
        repository_root, key, profile_sha256="f" * 64,
    )
    with pytest.raises(ValueError, match="bindings differ"):
        author_signed_blind_review_ledger(
            packet, completed, reviewer=changed_profile,
            private_key_path=private_path, repository_root=repository_root,
            evidence_root=evidence_root,
        )

    wrong_private = _private_key_file(
        tmp_path / "wrong-reviewer.key", Ed25519PrivateKey.generate(),
    )
    with pytest.raises(ValueError, match="differs from configured enrollment"):
        author_signed_blind_review_ledger(
            packet, completed, reviewer=reviewer,
            private_key_path=wrong_private, repository_root=repository_root,
            evidence_root=evidence_root,
        )

    wrong_timezone = deepcopy(completed)
    wrong_timezone["review"]["review_timezone"] = "America/New_York"
    with pytest.raises(ValueError, match="offset differs from review_timezone"):
        author_signed_blind_review_ledger(
            packet, wrong_timezone, reviewer=reviewer,
            private_key_path=private_path, repository_root=repository_root,
            evidence_root=evidence_root,
        )


def test_private_signing_key_must_stay_outside_repository_and_evidence_root(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key)
    packet = _packet()
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    inside = _private_key_file(evidence_root / "forbidden.key", key)

    with pytest.raises(ValueError, match="outside the repository and evidence root"):
        author_signed_blind_review_ledger(
            packet, completed, reviewer=reviewer, private_key_path=inside,
            repository_root=repository_root, evidence_root=evidence_root,
        )


@pytest.mark.parametrize("pem", [False, True])
@pytest.mark.parametrize("mode", [0o640, 0o604])
def test_raw_and_pem_private_keys_reject_group_or_world_access(
    tmp_path: Path,
    pem: bool,
    mode: int,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key)
    packet = _packet()
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    exposed = _private_key_file(tmp_path / "exposed.key", key, pem=pem)
    exposed.chmod(mode)

    with pytest.raises(ValueError, match="group- or world-accessible"):
        author_signed_blind_review_ledger(
            packet, completed, reviewer=reviewer, private_key_path=exposed,
            repository_root=repository_root, evidence_root=evidence_root,
        )


def _load_cli() -> ModuleType:
    path = ROOT / "scripts" / "author_blind_review_ledger.py"
    spec = importlib.util.spec_from_file_location("author_blind_review_ledger_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_retains_fresh_template_and_refuses_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    config, _reviewer = _enrollment(repository_root, key)
    _config_path, config_sha256 = _canonical_config_file(repository_root, config)
    packet_path = evidence_root / "packet.json"
    packet_path.write_text(
        json.dumps(_packet(config_sha256=config_sha256)), encoding="utf-8",
    )
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", repository_root)
    output = evidence_root / "template.json"
    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "template",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--reviewer-role", GIA_VISUAL_FIDELITY_ROLE,
        "--out", str(output),
    ])

    assert cli.main() == 0
    retained = output.read_bytes()
    with pytest.raises(ValueError, match="retained artifact already exists"):
        cli.main()
    assert output.read_bytes() == retained


def test_cli_rejects_noncanonical_config_authority_and_packet_binding_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    config, _reviewer = _enrollment(repository_root, key)
    _canonical_config_file(repository_root, config)
    packet_path = evidence_root / "packet.json"
    packet_path.write_text(json.dumps(_packet()), encoding="utf-8")
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", repository_root)
    output = evidence_root / "template.json"
    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "template",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--reviewer-role", GIA_VISUAL_FIDELITY_ROLE,
        "--out", str(output),
    ])

    with pytest.raises(ValueError, match="not bound to the canonical frozen"):
        cli.main()
    assert not output.exists()

    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "template",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--config", str(repository_root / "other.json"),
        "--reviewer-role", GIA_VISUAL_FIDELITY_ROLE,
        "--out", str(output),
    ])
    with pytest.raises(SystemExit):
        cli.main()


def test_invalid_completed_form_never_creates_partial_cli_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    config, reviewer = _enrollment(repository_root, key)
    _config_path, config_sha256 = _canonical_config_file(repository_root, config)
    packet = _packet(config_sha256=config_sha256)
    packet_path = evidence_root / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    invalid = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    invalid["review"]["decisions"][0]["criteria"].pop()
    template_path = evidence_root / "completed.json"
    template_path.write_text(json.dumps(invalid), encoding="utf-8")
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", repository_root)
    output = evidence_root / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "sign",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--template", str(template_path),
        "--private-key", str(private_path),
        "--out", str(output),
    ])

    with pytest.raises(ValueError, match="criterion count differs"):
        cli.main()
    assert not output.exists()


def test_cli_sign_rejects_canonical_config_changed_after_template_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    config, reviewer = _enrollment(repository_root, key)
    config_path, config_sha256 = _canonical_config_file(repository_root, config)
    packet = _packet(config_sha256=config_sha256)
    packet_path = evidence_root / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    template_path = evidence_root / "completed.json"
    template_path.write_text(json.dumps(completed), encoding="utf-8")
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    config_path.write_text(
        json.dumps(config | {"unexpected_config_drift": True}), encoding="utf-8",
    )
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", repository_root)
    output = evidence_root / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "sign",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--template", str(template_path),
        "--private-key", str(private_path),
        "--out", str(output),
    ])

    with pytest.raises(ValueError, match="not bound to the canonical frozen"):
        cli.main()
    assert not output.exists()


def test_cli_signs_and_retains_a_canonically_verified_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    config, reviewer = _enrollment(repository_root, key)
    _config_path, config_sha256 = _canonical_config_file(repository_root, config)
    packet = _packet(config_sha256=config_sha256)
    packet_path = evidence_root / "packet.json"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    template_path = evidence_root / "completed.json"
    template_path.write_text(json.dumps(completed), encoding="utf-8")
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    cli = _load_cli()
    monkeypatch.setattr(cli, "ROOT", repository_root)
    output = evidence_root / "ledger.json"
    monkeypatch.setattr(sys, "argv", [
        "author_blind_review_ledger.py", "sign",
        "--evidence-root", str(evidence_root),
        "--packet", str(packet_path),
        "--template", str(template_path),
        "--private-key", str(private_path),
        "--out", str(output),
    ])

    assert cli.main() == 0
    ledger = json.loads(output.read_text(encoding="utf-8"))
    validation = validate_signed_review_ledger(
        packet,
        ledger,
        reviewer_public_key=reviewer.public_key,
        reviewer_key_id=reviewer.key_id,
        expected_reviewer_profile_sha256=reviewer.reviewer_profile_sha256,
    )
    assert validation["status"] == "pass"
    assert validation["signature_status"] == "verified"


def test_valid_signed_ledger_remains_compatible_with_canonical_validator(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repo"
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    key = Ed25519PrivateKey.generate()
    _config, reviewer = _enrollment(repository_root, key)
    private_path = _private_key_file(tmp_path / "reviewer.key", key)
    packet = _packet()
    completed = _completed(
        build_blind_review_authoring_template(packet, reviewer=reviewer)
    )
    ledger, _validation = author_signed_blind_review_ledger(
        packet, completed, reviewer=reviewer, private_key_path=private_path,
        repository_root=repository_root, evidence_root=evidence_root,
    )

    replay = validate_signed_review_ledger(
        packet,
        ledger,
        reviewer_public_key=reviewer.public_key,
        reviewer_key_id=reviewer.key_id,
        expected_reviewer_profile_sha256=reviewer.reviewer_profile_sha256,
    )
    assert replay["status"] == "pass"
    assert replay["signature_status"] == "verified"
