"""Grok-powered spec editing: the same structural guarantees as the Claude
edit agent, running entirely on the xAI key.

The edit agent's promise — change ONE element and nothing else — was never the
model's to keep: `agent.scope_guard` enforces it by construction, and the
validator gates the result. Those pieces are pure code, so this module swaps
only the language engine: an xAI chat call proposes the edited spec, the
existing scope guard and validator do the guaranteeing. It also carries the
"understood as" interpreter for checklist NO-notes: the agent echoes its
reading of the designer's note back for confirmation BEFORE anything executes
— understanding is confirmed, never assumed.

Runs on XAI_KEY alone; anthropic is never imported here.
"""

from __future__ import annotations

import json
import os

from pydantic import ValidationError

from facetta.agent import (
    Annotation, EditResult, ScopedEditResult, _frame_annotation, _target_label,
    _target_ref, edit_system_prompt, resolve_target, scope_guard,
)
from facetta.assistant import DEFAULT_ASSISTANT_NAME
from facetta.spec import Spec

GROK_CHAT_MODEL_ENV = "FACETTA_XAI_CHAT"
DEFAULT_GROK_CHAT_MODEL = "grok-4.3"


class GrokEditUnavailable(Exception):
    """No key, provider failure, or unusable output after the repair retry."""


def _chat_json(system: str, user: str) -> dict:
    """One xAI chat call, JSON object out — the assistant._assistant_chat
    shape, isolated here so tests monkeypatch exactly one seam."""
    from facetta.concept import _provider_key

    key = _provider_key("XAI_KEY")
    if not key:
        raise GrokEditUnavailable(
            "no XAI_KEY configured — the edit agent needs a chat key")

    import httpx

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions", timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get(GROK_CHAT_MODEL_ENV,
                                        DEFAULT_GROK_CHAT_MODEL),
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
            })
        response.raise_for_status()
        data = json.loads(response.json()["choices"][0]["message"]["content"])
        if not isinstance(data, dict):
            raise ValueError(f"provider returned non-object JSON: {data!r}")
        return data
    except GrokEditUnavailable:
        raise
    except Exception as exc:
        raise GrokEditUnavailable(f"grok edit call failed: {exc}") from exc


_RESULT_SHAPE = (
    '\n\nReturn JSON exactly in this shape:\n'
    '{"spec": {…the COMPLETE edited spec object…},\n'
    ' "changed_fields": ["path: old → new", …],\n'
    ' "isolate_ref": null,\n'
    ' "message": "one sentence describing the change"}\n'
    "The spec must be the WHOLE object with your edit applied — every field "
    "of the current spec present, unchanged except what the instruction asks. "
    "Output ONLY the JSON.")


def grok_plan_edit(instruction: str, current: Spec) -> EditResult:
    """Propose an edited spec via Grok. xAI JSON mode has no schema
    enforcement (unlike the Anthropic parse path), so a malformed proposal
    gets ONE repair retry with the validation error appended. The result is
    NOT trusted — callers scope-guard and re-validate before saving."""
    user = ("CURRENT SPEC:\n" + current.model_dump_json(indent=2)
            + "\n\nEDIT INSTRUCTION:\n" + instruction)
    system = edit_system_prompt() + _RESULT_SHAPE
    data = _chat_json(system, user)
    try:
        return EditResult.model_validate(data)
    except ValidationError as first_error:
        repair = (user + "\n\nYour previous answer failed validation with:\n"
                  + str(first_error)
                  + "\nReturn the corrected JSON in the exact shape asked.")
        data = _chat_json(system, repair)
        try:
            return EditResult.model_validate(data)
        except ValidationError as exc:
            raise GrokEditUnavailable(
                f"edit proposal failed validation twice: {exc}") from exc


def grok_plan_scoped_edit(annotation: Annotation,
                          current: Spec) -> ScopedEditResult:
    """The scoped edit on Grok: resolve the ONE target subtree, let the model
    propose a whole spec, then scope_guard grafts only that subtree — touching
    anything else is impossible, exactly as in agent.plan_scoped_edit. The
    caller still re-validates the guarded spec before saving a version."""
    target = resolve_target(current, annotation)
    proposed = grok_plan_edit(
        _frame_annotation(target, annotation.instruction), current)
    guarded, changed, ignored = scope_guard(current, target, proposed.spec)
    return ScopedEditResult(
        spec=guarded, target=_target_label(target),
        isolate_ref=_target_ref(target),
        changed_fields=changed, ignored_fields=ignored,
        message=proposed.message)


_INTERPRET_SYSTEM = """\
You are {name}, the design assistant inside Facetta, a jewelry
design-to-manufacturing platform. A designer answered NO on an approval
checklist item and wrote a change note. Your job is to make sure the change is
understood 100% BEFORE anything executes: restate it precisely, and say how it
should be carried out. Never guess — if the note is ambiguous, ask.

Return JSON exactly:
{{"understood_as": "Understood as: <precise restatement, with numbers when the
  note implies them; end with 'nothing else changes.'>",
 "action": "spec_edit" | "image_edit" | "both" | "needs_clarification",
 "instruction": "<the note rewritten as one imperative, agent-ready sentence>",
 "region_description": "<the piece region for a localized image edit>",
 "target_section": "stone|side_stones|setting|metal|band|ring_size|drop|pendant|chain|bracelet|brooch" | null,
 "confidence": 0.0-1.0,
 "clarification": "<the ONE question to ask, when action is needs_clarification>"}}

action: spec_edit when the change is a recorded value (a dimension, count,
material); image_edit when it is purely visual (finish, styling) with no
recorded value; both when it changes a value that is also visible. Use
needs_clarification whenever the note could mean two different changes.
Output ONLY the JSON."""


def interpret_change_note(note: str, *, item_label: str, item_fact: str,
                          spec_json: dict | None = None,
                          name: str = DEFAULT_ASSISTANT_NAME) -> dict:
    """The understood-as echo for a checklist NO. Returns the normalized
    interpretation dict; confidence below 0.6 is coerced to
    needs_clarification — a half-understood change is never offered as
    executable. Raises GrokEditUnavailable on provider failure (an explicit
    interpret request fails loudly)."""
    name = (name or DEFAULT_ASSISTANT_NAME).strip() or DEFAULT_ASSISTANT_NAME
    user = (f"Checklist item: {item_label}\n"
            f"Fact shown to the designer: {item_fact}\n"
            f"Designer's change note: {note}")
    if spec_json:
        user += "\n\nCURRENT SPEC:\n" + json.dumps(spec_json, indent=1)
    data = _chat_json(_INTERPRET_SYSTEM.format(name=name), user)

    out = {
        "understood_as": str(data.get("understood_as") or "").strip(),
        "action": str(data.get("action") or "needs_clarification"),
        "instruction": str(data.get("instruction") or note),
        "region_description": str(data.get("region_description") or ""),
        "target_section": data.get("target_section"),
        "confidence": float(data.get("confidence") or 0.0),
        "clarification": str(data.get("clarification") or ""),
        "assistant_name": name,
    }
    valid_actions = {"spec_edit", "image_edit", "both", "needs_clarification"}
    if out["action"] not in valid_actions:
        out["action"] = "needs_clarification"
    if out["confidence"] < 0.6 and out["action"] != "needs_clarification":
        out["action"] = "needs_clarification"
        out["clarification"] = (out["clarification"]
                                or "the note could be read more than one way — "
                                   "say exactly what should change")
    if not out["understood_as"]:
        out["action"] = "needs_clarification"
        out["clarification"] = (out["clarification"]
                                or "could not restate the change — please "
                                   "rephrase the note")
    return out
