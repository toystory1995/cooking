"""Loading and parsing the recipe library.

Every recipe is a Markdown file with a small frontmatter block:

    ---
    title: Crispy-Skin Salmon
    level: 2
    minutes: 25
    serves: 2
    cuisine: Modern European
    seasons:
      - any
    skills:
      - pan-searing
      - basting
    ---

    ## Ingredients
    ...

The frontmatter parser deliberately supports only what the library needs --
scalars and block lists -- so there is no YAML dependency to install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

VALID_SEASONS = {"spring", "summer", "autumn", "winter", "any"}
MIN_LEVEL = 1
MAX_LEVEL = 5

LEVEL_NAMES = {
    1: "Foundations",
    2: "Confident cook",
    3: "Technique",
    4: "Restaurant plate",
    5: "Pressure test",
}


class RecipeError(ValueError):
    """Raised when a recipe file cannot be parsed or fails validation."""


@dataclass(frozen=True)
class Recipe:
    slug: str
    title: str
    level: int
    minutes: int
    serves: int
    cuisine: str
    body: str
    path: Path
    seasons: tuple[str, ...] = ("any",)
    skills: tuple[str, ...] = ()
    equipment: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    source: str | None = None

    @property
    def level_name(self) -> str:
        return LEVEL_NAMES.get(self.level, "Unknown")

    def in_season(self, season: str) -> bool:
        return "any" in self.seasons or season in self.seasons


def split_frontmatter(text: str, *, origin: str = "<string>") -> tuple[str, str]:
    """Return (frontmatter, body) for a Markdown document."""
    stripped = text.lstrip("﻿")
    if not stripped.startswith("---"):
        raise RecipeError(f"{origin}: file must start with a '---' frontmatter block")
    match = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", stripped, re.DOTALL)
    if not match:
        raise RecipeError(f"{origin}: frontmatter block is never closed with '---'")
    return match.group(1), stripped[match.end():].strip("\n")


def parse_frontmatter(block: str, *, origin: str = "<string>") -> dict[str, object]:
    """Parse the supported frontmatter subset: `key: value` and `- item` lists."""
    data: dict[str, object] = {}
    current_list_key: str | None = None

    for lineno, raw_line in enumerate(block.splitlines(), start=1):
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if line.lstrip().startswith("- "):
            if current_list_key is None:
                raise RecipeError(f"{origin}:{lineno}: list item before any key")
            item = line.lstrip()[2:].strip()
            if item:
                data[current_list_key].append(item)  # type: ignore[union-attr]
            continue

        if ":" not in line:
            raise RecipeError(f"{origin}:{lineno}: expected 'key: value', got {line!r}")

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise RecipeError(f"{origin}:{lineno}: empty key")

        if value:
            data[key] = value
            current_list_key = None
        else:
            data[key] = []
            current_list_key = key

    return data


def _require(data: dict[str, object], key: str, origin: str) -> object:
    if key not in data or data[key] in ("", []):
        raise RecipeError(f"{origin}: missing required field '{key}'")
    return data[key]


def _as_int(value: object, key: str, origin: str) -> int:
    try:
        return int(str(value).strip())
    except ValueError:
        raise RecipeError(f"{origin}: field '{key}' must be a whole number, got {value!r}") from None


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


def parse_recipe(text: str, *, slug: str, path: Path | None = None) -> Recipe:
    origin = str(path) if path is not None else slug
    frontmatter, body = split_frontmatter(text, origin=origin)
    data = parse_frontmatter(frontmatter, origin=origin)

    if not body.strip():
        raise RecipeError(f"{origin}: recipe has frontmatter but no method")

    level = _as_int(_require(data, "level", origin), "level", origin)
    if not MIN_LEVEL <= level <= MAX_LEVEL:
        raise RecipeError(f"{origin}: level must be between {MIN_LEVEL} and {MAX_LEVEL}, got {level}")

    seasons = _as_tuple(data.get("seasons", "any")) or ("any",)
    unknown = sorted(set(seasons) - VALID_SEASONS)
    if unknown:
        raise RecipeError(f"{origin}: unknown season(s) {', '.join(unknown)}")

    return Recipe(
        slug=slug,
        title=str(_require(data, "title", origin)),
        level=level,
        minutes=_as_int(_require(data, "minutes", origin), "minutes", origin),
        serves=_as_int(data.get("serves", 2), "serves", origin),
        cuisine=str(data.get("cuisine", "Unfiled")),
        seasons=seasons,
        skills=_as_tuple(data.get("skills", [])),
        equipment=_as_tuple(data.get("equipment", [])),
        tags=_as_tuple(data.get("tags", [])),
        source=str(data["source"]) if data.get("source") else None,
        body=body,
        path=path or Path(slug),
    )


def load_recipe(path: Path) -> Recipe:
    return parse_recipe(path.read_text(encoding="utf-8"), slug=path.stem, path=path)


def load_library(directory: Path) -> list[Recipe]:
    """Load and validate every recipe in `directory`, sorted by slug."""
    if not directory.is_dir():
        raise RecipeError(f"recipe directory not found: {directory}")

    recipes = [load_recipe(path) for path in sorted(directory.glob("*.md"))]
    if not recipes:
        raise RecipeError(f"no recipes found in {directory}")

    seen: dict[str, Path] = {}
    for recipe in recipes:
        if recipe.slug in seen:
            raise RecipeError(f"duplicate recipe slug {recipe.slug!r}")
        seen[recipe.slug] = recipe.path
    return recipes


def all_skills(recipes: Iterable[Recipe]) -> list[str]:
    return sorted({skill for recipe in recipes for skill in recipe.skills})
