"""Studio presentation routes preserve trusted transaction authority."""

import pytest
from pydantic import ValidationError

from facetta.api import studio
from facetta.auth import AuthenticatedPrincipal


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(subject=None, local_unbound=True)


def test_beauty_alias_delegates_the_exact_accounted_request(monkeypatch):
    request = studio.StudioBeautyRenderRequest(
        created_by="usr_designer",
        expected_asset_id="ast_active",
        source_asset_id="ast_line_art",
        expected_design_version=4,
        instruction="Preserve the confirmed design.",
        presentation_only=True,
        studio_job_id="job_present",
    )
    db = object()
    calls = []

    def delegate(root_id, delegated_request, delegated_db):
        calls.append((root_id, delegated_request, delegated_db))
        return {"status": "review_required"}

    monkeypatch.setattr(studio, "render_project_revision", delegate)

    result = studio.create_studio_beauty_render(
        "project_exact", request, db, _principal(),
    )

    assert result == {"status": "review_required"}
    assert calls == [("project_exact", request, db)]


def test_product_photo_alias_delegates_the_exact_accounted_request(monkeypatch):
    request = studio.StudioProductPhotoRequest(
        created_by="usr_designer",
        expected_asset_id="ast_active",
        expected_design_version=4,
        preset="catalog_white",
        framing="square",
        presentation_only=True,
        studio_job_id="job_present",
    )
    db = object()
    calls = []

    def delegate(root_id, delegated_request, delegated_db):
        calls.append((root_id, delegated_request, delegated_db))
        return {"status": "review_required"}

    monkeypatch.setattr(studio, "create_product_photo", delegate)

    result = studio.create_studio_product_photo(
        "project_exact", request, db, _principal(),
    )

    assert result == {"status": "review_required"}
    assert calls == [("project_exact", request, db)]


@pytest.mark.parametrize(
    ("request_type", "payload"),
    [
        (
            studio.StudioBeautyRenderRequest,
            {
                "created_by": "usr_designer",
                "expected_design_version": 4,
                "presentation_only": False,
                "studio_job_id": "job_present",
            },
        ),
        (
            studio.StudioProductPhotoRequest,
            {
                "created_by": "usr_designer",
                "expected_asset_id": "ast_active",
                "expected_design_version": 4,
                "presentation_only": True,
            },
        ),
    ],
)
def test_studio_presentation_aliases_reject_legacy_mutation_shapes(
    request_type,
    payload,
):
    with pytest.raises(ValidationError):
        request_type.model_validate(payload)
