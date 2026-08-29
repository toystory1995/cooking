"""Picking the week's recipe.

The rules, in order of weight:

1. Never repeat a recipe until the whole library has been cooked.
2. Work up through the difficulty levels -- one level per `RECIPES_PER_LEVEL`
   cooked -- but stay flexible when the library is thin at the target level.
3. Prefer recipes that teach a skill the cook has not met yet.
4. Prefer things that are in season, and avoid the same cuisine twice running.

Recipes tagged `capstone` are held back until everything else has been cooked, so the
final pressure test really is the final one.

Ties break on a hash of (slug, week), so a `--dry-run` preview on Tuesday shows
exactly what Friday's send will be.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from .library import MAX_LEVEL, MIN_LEVEL, Recipe
from .history import History

RECIPES_PER_LEVEL = 5

# Meteorological seasons, northern hemisphere.
_SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}


@dataclass(frozen=True)
class Pick:
    recipe: Recipe
    target_level: int
    new_skills: tuple[str, ...]
    week_number: int
    reasons: tuple[str, ...]


def season_for(today: date) -> str:
    return _SEASON_BY_MONTH[today.month]


def target_level(cooked_count: int, *, per_level: int = RECIPES_PER_LEVEL) -> int:
    """Difficulty to aim for after `cooked_count` recipes."""
    if per_level < 1:
        raise ValueError("per_level must be at least 1")
    return min(MAX_LEVEL, MIN_LEVEL + cooked_count // per_level)


def _jitter(slug: str, week_key: str) -> float:
    digest = hashlib.sha256(f"{slug}:{week_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _score(recipe: Recipe, *, level: int, season: str, unseen_skills: set[str],
           last_cuisine: str | None, week_key: str) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []

    distance = abs(recipe.level - level)
    score = -3.0 * distance
    # Stretching up is more interesting than dropping back down.
    if recipe.level < level:
        score -= 1.0 * distance
    if distance == 0:
        reasons.append(f"right at your current level ({level})")
    elif recipe.level > level:
        reasons.append(f"a stretch above level {level}")

    new_skills = sorted(set(recipe.skills) & unseen_skills)
    if new_skills:
        score += min(len(new_skills), 3) * 1.2
        reasons.append("teaches " + ", ".join(new_skills))

    if "any" in recipe.seasons:
        pass
    elif season in recipe.seasons:
        score += 1.5
        reasons.append(f"good for {season}")
    else:
        score -= 2.0

    if last_cuisine and recipe.cuisine == last_cuisine:
        score -= 1.0

    return score + _jitter(recipe.slug, week_key), tuple(reasons)


def choose_recipe(recipes: list[Recipe], history: History, today: date, *,
                  per_level: int = RECIPES_PER_LEVEL) -> Pick:
    """Choose the recipe to send on `today`."""
    if not recipes:
        raise ValueError("the recipe library is empty")

    unsent = [r for r in recipes if r.slug not in history.sent_slugs]
    # Hold the capstone back while there is still ordinary work to do.
    candidates = [r for r in unsent if "capstone" not in r.tags] or unsent
    exhausted = not candidates
    if exhausted:
        # Whole library cooked: start again with whatever is least recent.
        oldest = min((history.last_sent_on(r.slug) or "") for r in recipes)
        candidates = [r for r in recipes if (history.last_sent_on(r.slug) or "") == oldest]

    iso = today.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"
    level = target_level(history.count, per_level=per_level)
    season = season_for(today)
    unseen = {skill for r in recipes for skill in r.skills} - history.skills_learned()
    last = history.last
    last_cuisine = None
    if last is not None:
        by_slug = {r.slug: r for r in recipes}
        last_recipe = by_slug.get(last.slug)
        last_cuisine = last_recipe.cuisine if last_recipe else None

    scored = [
        (_score(r, level=level, season=season, unseen_skills=unseen,
                last_cuisine=last_cuisine, week_key=week_key), r)
        for r in candidates
    ]
    (_, reasons), winner = max(scored, key=lambda item: (item[0][0], item[1].slug))

    if exhausted:
        reasons = reasons + ("you have cooked the whole library -- second pass",)

    return Pick(
        recipe=winner,
        target_level=level,
        new_skills=tuple(sorted(set(winner.skills) - history.skills_learned())),
        week_number=history.count + 1,
        reasons=reasons,
    )
