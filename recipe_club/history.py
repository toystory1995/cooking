"""The cooking log: which recipes have been sent, and what they taught."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Entry:
    date: str
    slug: str
    title: str
    level: int
    skills: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "slug": self.slug,
            "title": self.title,
            "level": self.level,
            "skills": list(self.skills),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Entry":
        return cls(
            date=str(raw["date"]),
            slug=str(raw["slug"]),
            title=str(raw.get("title", raw["slug"])),
            level=int(raw.get("level", 1)),
            skills=tuple(str(s) for s in raw.get("skills", [])),
        )


@dataclass
class History:
    entries: list[Entry]
    path: Path | None = None

    @classmethod
    def empty(cls, path: Path | None = None) -> "History":
        return cls(entries=[], path=path)

    @classmethod
    def load(cls, path: Path) -> "History":
        """Load history, tolerating a missing file (a first run has no log yet)."""
        if not path.exists():
            return cls.empty(path)
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        entries = [Entry.from_dict(item) for item in raw.get("entries", [])]
        entries.sort(key=lambda entry: (entry.date, entry.slug))
        return cls(entries=entries, path=path)

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("no path given to save history to")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in self.entries],
        }
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return target

    # -- queries ---------------------------------------------------------

    @property
    def sent_slugs(self) -> set[str]:
        return {entry.slug for entry in self.entries}

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def last(self) -> Entry | None:
        return self.entries[-1] if self.entries else None

    def skills_learned(self) -> set[str]:
        return {skill for entry in self.entries for skill in entry.skills}

    def levels_cooked(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for entry in self.entries:
            counts[entry.level] = counts.get(entry.level, 0) + 1
        return counts

    def times_sent(self, slug: str) -> int:
        return sum(1 for entry in self.entries if entry.slug == slug)

    def last_sent_on(self, slug: str) -> str | None:
        dates = [entry.date for entry in self.entries if entry.slug == slug]
        return max(dates) if dates else None

    def record(self, recipe_slug: str, title: str, level: int, skills: tuple[str, ...], on: date) -> Entry:
        entry = Entry(date=on.isoformat(), slug=recipe_slug, title=title, level=level, skills=tuple(skills))
        self.entries.append(entry)
        return entry
