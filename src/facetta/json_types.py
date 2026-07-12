"""Recursive JSON types for typed API and persistence boundaries."""

from __future__ import annotations

from typing import TypeAlias

from typing_extensions import TypeAliasType

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue = TypeAliasType(
    "JsonValue",
    JsonScalar | list["JsonValue"] | dict[str, "JsonValue"],
)
JsonObject: TypeAlias = dict[str, JsonValue]
