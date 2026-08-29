"""Picking the week's recipe.

The level is a **ceiling, not a preference**. Each week the schedule says which
level you have unlocked; only recipes at or below it are eligible, and within
that pool the pick works near the ceiling. That keeps the climb honest — no
amount of tempting new technique can push you into a level you have not reached,
and nothing is orphaned when you move up, because everything below stays
eligible.

Within the pool, in order of weight:

1. Work near the ceiling rather than well below it.
2. Rotate across tracks -- disciplines, not cuisines -- so a run of dumplings or
   a month of French mains cannot happen. Tracks never cooked are favoured.
3. Prefer recipes that teach a skill the cook has not met yet.
4. Prefer things that are in season, and avoid the same cuisine twice running.

Recipes are never repeated until the whole library is cooked, and those tagged
`capstone` are held back until everything else is done, so the final pressure
test really is the final one.

Ties break on a hash of (slug, week), so a `--dry-run` preview on Tuesday shows
exactly what Friday's send will be.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date

from .history import History
from .library import MAX_LEVEL, MIN_LEVEL, Recipe

RECIPES_PER_LEVEL = 5

# How many recent picks a track is penalised for reappearing within.
TRACK_MEMORY = 4

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


def pace_for(library_size: int) -> int:
    """Recipes to cook per level, scaled so the climb fits the library.

    A 26-recipe library moves up every 4; a 71-recipe one every 11, which puts
    the hardest third of the course in the second half of the year.
    """
    return max(4, library_size // (MAX_LEVEL + 1))


def target_level(cooked_count: int, library_size: int | None = None, *,
                 per_level: int | None = None) -> int:
    """The highest level unlocked after `cooked_count` recipes."""
    if per_level is None:
        per_level = pace_for(library_size) if library_size else RECIPES_PER_LEVEL
    if per_level < 1:
        raise ValueError("per_level must be at least 1")
    return min(MAX_LEVEL, MIN_LEVEL + cooked_count // per_level)


def eligible_at(recipes: list[Recipe], ceiling: int) -> list[Recipe]:
    """Recipes at or below the ceiling, or the easiest available if none are."""
    within = [recipe for recipe in recipes if recipe.level <= ceiling]
    if within:
        return within
    floor = min(recipe.level for recipe in recipes)
    return [recipe for recipe in recipes if recipe.level == floor]


def _jitter(slug: str, week_key: str) -> float:
    digest = hashlib.sha256(f"{slug}:{week_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 0xFFFFFFFF


def _score(recipe: Recipe, *, ceiling: int, season: str, unseen_skills: set[str],
           last_cuisine: str | None, recent_tracks: tuple[str, ...],
           unseen_tracks: set[str], week_key: str) -> tuple[float, tuple[str, ...]]:
    reasons: list[str] = []

    # Work near the ceiling. Everything below is allowed but costs something,
    # so easier weeks happen when variety earns them, not by default.
    score = -1.5 * (ceiling - recipe.level)
    if recipe.level == ceiling:
        reasons.append(f"right at your ceiling (level {ceiling})")
    else:
        reasons.append(f"a lighter week at level {recipe.level}")

    if recipe.track in recent_tracks:
        position = recent_tracks.index(recipe.track)  # 0 = most recent
        score -= 3.0 - 0.5 * position
    elif recipe.track in unseen_tracks:
        score += 2.0
        reasons.append(f"opens up {recipe.track.replace('-', ' ')}")

    new_skills = sorted(set(recipe.skills) & unseen_skills)
    if new_skills:
        score += min(len(new_skills), 3) * 0.8
        reasons.append("teaches " + ", ".join(new_skills[:3]))

    if "any" in recipe.seasons:
        pass
    elif season in recipe.seasons:
        score += 1.5
        reasons.append(f"good for {season}")
    else:
        score -= 2.5

    if last_cuisine and recipe.cuisine == last_cuisine:
        score -= 1.0

    return score + _jitter(recipe.slug, week_key), tuple(reasons)


def choose_recipe(recipes: list[Recipe], history: History, today: date, *,
                  per_level: int | None = None,
                  track: str | None = None) -> Pick:
    """Choose the recipe to send on `today`, optionally forced to one track."""
    if not recipes:
        raise ValueError("the recipe library is empty")

    pool = [r for r in recipes if r.track == track] if track else recipes
    if not pool:
        raise ValueError(f"no recipes on the {track!r} track")

    unsent = [r for r in pool if r.slug not in history.sent_slugs]
    # Hold the capstone back while there is still ordinary work to do.
    candidates = [r for r in unsent if "capstone" not in r.tags] or unsent
    exhausted = not candidates
    if exhausted:
        # Whole library cooked: start again with whatever is least recent.
        oldest = min((history.last_sent_on(r.slug) or "") for r in pool)
        candidates = [r for r in pool if (history.last_sent_on(r.slug) or "") == oldest]

    iso = today.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"
    ceiling = target_level(history.count, len(recipes), per_level=per_level)
    season = season_for(today)
    unseen_skills = {s for r in recipes for s in r.skills} - history.skills_learned()

    by_slug = {r.slug: r for r in recipes}
    last = history.last
    last_cuisine = by_slug[last.slug].cuisine if last and last.slug in by_slug else None

    # Most recent first, so a track cooked last week is penalised hardest.
    recent_tracks = tuple(
        by_slug[entry.slug].track
        for entry in reversed(history.entries[-TRACK_MEMORY:])
        if entry.slug in by_slug
    )
    cooked_tracks = {by_slug[e.slug].track for e in history.entries if e.slug in by_slug}
    unseen_tracks = {r.track for r in recipes} - cooked_tracks

    scored = [
        (_score(r, ceiling=ceiling, season=season, unseen_skills=unseen_skills,
                last_cuisine=last_cuisine, recent_tracks=recent_tracks,
                unseen_tracks=unseen_tracks, week_key=week_key), r)
        for r in eligible_at(candidates, ceiling)
    ]
    (_, reasons), winner = max(scored, key=lambda item: (item[0][0], item[1].slug))

    if exhausted:
        reasons = reasons + ("you have cooked the whole library -- second pass",)

    return Pick(
        recipe=winner,
        target_level=ceiling,
        new_skills=tuple(sorted(set(winner.skills) - history.skills_learned())),
        week_number=history.count + 1,
        reasons=reasons,
    )
