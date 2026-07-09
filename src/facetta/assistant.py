"""The in-app design assistant: a designer describes a piece from scratch, the
assistant asks the right questions, then hands a clean brief to the pipeline.

This is the front door to origination. The designer can rename it (it defaults
to "Atelier"), types what they want in plain language, and the assistant — held
inside the controlled vocabulary and the design-style library — asks one useful
question at a time until it knows enough to build: the archetype, the centre
stone, the metal, the setting, and how the designer wants to see it (a client
render, a factory spec sheet, or both). When it has enough, it stops asking and
returns a compiled brief plus the chosen output mode; the caller runs that brief
through the same generate → read → validate → draw pipeline as everything else.

The assistant never writes dimensions or invents trade terms — it only gathers
intent. The validator and the deterministic renderers still own every number.
"""

from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from facetta.render import RenderUnavailable
from facetta.styles import get_styles
from facetta.vocabulary import get_vocabulary

DEFAULT_ASSISTANT_NAME = "Atelier"

_SYSTEM = """\
You are {name}, the design assistant inside Facetta, a jewelry design-to-
manufacturing platform. A designer wants to create a NEW piece from scratch and
has described it in their own words. Your job is to gather enough intent to build
it — NOT to draw it, and NOT to state any millimetre dimensions (the platform's
validator sets real measurements later).

Work one question at a time. Keep asking until you know all of:
  - the archetype (one of the library types below),
  - the centre stone species and cut (controlled vocabulary only),
  - the metal (material and, for gold, colour),
  - the setting / how the stone is held,
  - for a halo or cluster, the accent stone,
  - and how the designer wants to SEE it: a client render, a factory
    manufacturing technical drawing, or both.
You may suggest an era from the library to steer the look, but never require it.

Only ever use these controlled-vocabulary ids — never invent species, cuts,
metals, or trade terms:
{vocab}

{styles}

Return ONLY a JSON object matching exactly one of these two shapes.

While you still need information:
{{"action": "ask", "message": "<friendly reply>", "question": "<one question>",
  "options": ["<suggested answer>", "..."]}}

When you have everything (including the output choice):
{{"action": "design",
  "message": "<one sentence confirming what you'll build>",
  "brief": "<a single vivid product-photo sentence naming the archetype, era if
    chosen, centre stone species and cut, metal, and setting — no millimetres>",
  "output": "render" | "sheet" | "both"}}

Output ONLY the JSON, nothing else."""


class AssistantReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assistant_name: str = DEFAULT_ASSISTANT_NAME
    action: Literal["ask", "design"]
    message: str = ""
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    brief: str | None = None
    output: Literal["render", "sheet", "both"] | None = None


class Turn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["assistant", "user"]
    content: str


def _system_prompt(name: str) -> str:
    vocab = get_vocabulary()
    styles = get_styles()
    vocab_lines = (
        f"species: {', '.join(vocab.species_ids())}\n"
        f"cuts: {', '.join(vocab.cut_ids())}\n"
        f"metals: {', '.join(m['id'] for m in vocab.metals())}\n"
        f"settings: {', '.join(t['id'] for t in vocab.setting_techniques())}"
    )
    return _SYSTEM.format(name=name, vocab=vocab_lines, styles=styles.digest())


def _assistant_chat(system: str, messages: list[dict], model: str) -> str:
    """One grounded chat turn returning the raw JSON string. xAI by default;
    isolated here so tests can monkeypatch the network."""
    from facetta.concept import _provider_key

    key = _provider_key("XAI_KEY")
    if not key:
        raise RenderUnavailable(
            "no XAI_KEY configured — the design assistant needs a chat key")

    import httpx

    try:
        response = httpx.post(
            "https://api.x.ai/v1/chat/completions", timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.environ.get("FACETTA_XAI_CHAT", "grok-4.3"),
                "messages": [{"role": "system", "content": system}, *messages],
                "response_format": {"type": "json_object"},
            })
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RenderUnavailable(f"assistant chat failed: {exc}") from exc


def assist(history: list[Turn], message: str, *,
           name: str = DEFAULT_ASSISTANT_NAME,
           model: str = "grok") -> AssistantReply:
    """Advance the from-scratch conversation by one turn. `history` is the prior
    exchange (oldest first); `message` is the designer's latest input. Returns
    either a clarifying question or a finished brief + output choice."""
    name = (name or DEFAULT_ASSISTANT_NAME).strip() or DEFAULT_ASSISTANT_NAME
    msgs = [{"role": t.role, "content": t.content} for t in history]
    msgs.append({"role": "user", "content": message})
    raw = _assistant_chat(_system_prompt(name), msgs, model)
    reply = AssistantReply.model_validate(json.loads(raw))
    reply.assistant_name = name  # the app owns the name, not the model
    return reply
