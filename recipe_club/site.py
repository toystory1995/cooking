"""Building a static website out of the library.

`python send_recipe.py site` renders the whole of `recipes/` into a folder of
flat HTML files: an index you can search and filter, one page per recipe, and
the cooking log. No template engine and no build step -- the same reason the
frontmatter parser is hand-rolled -- so the site is a `cp` away from anywhere
that serves files, and GitHub Pages serves it straight from the repo.

    site/
      index.html               the library, with client-side filtering
      log.html                 what has been cooked, newest first
      recipes/<slug>.html      one page per recipe
      assets/site.css          one stylesheet

Links between pages are relative, so the output works from `file://`, from a
subdirectory on Pages, and from a domain root without being rebuilt.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .history import History
from .library import LEVEL_NAMES, MAX_LEVEL, Recipe, all_skills, tracks_in
from .render import markdown_to_html

SITE_TITLE = "Weekly Recipe Club"
TAGLINE = "One recipe every Friday, getting harder as you go."

_e = html.escape


# -- small text helpers ----------------------------------------------------


def lead_paragraph(body: str) -> str:
    """The prose a recipe opens with, before the first `## Ingredients`."""
    lines: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            break
        lines.append(line)
    text = " ".join(part for part in lines if part)
    return re.sub(r"\s+", " ", re.sub(r"[*`]", "", text)).strip()


def body_after_lead(body: str) -> str:
    """The recipe from its first `## heading` on, the lede having been lifted out."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("#"):
            return "\n".join(lines[index:])
    return body


def truncate(text: str, limit: int = 155) -> str:
    if len(text) <= limit:
        return text
    # Only back off to the previous word when the cut lands mid-word.
    cut = text[:limit] if text[limit] == " " else text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:—-") + "…"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _card_meta(recipe: Recipe) -> str:
    """`serves: 0` marks a drill rather than a dish -- don't print "serves 0"."""
    parts = [f"{recipe.minutes} min"]
    if recipe.serves:
        parts.append(f"serves {recipe.serves}")
    parts.append(recipe.cuisine)
    return " · ".join(parts)


# -- the numbers the site shows --------------------------------------------


@dataclass(frozen=True)
class SiteStats:
    total: int
    cooked: int
    tracks_total: int
    tracks_cooked: int
    skills_total: int
    skills_learned: int

    @property
    def percent(self) -> int:
        return round(100 * self.cooked / self.total) if self.total else 0


def gather_stats(recipes: Sequence[Recipe], history: History) -> SiteStats:
    by_slug = {recipe.slug: recipe for recipe in recipes}
    cooked_slugs = history.sent_slugs & set(by_slug)
    catalogue = set(all_skills(recipes))
    return SiteStats(
        total=len(recipes),
        cooked=len(cooked_slugs),
        tracks_total=len(tracks_in(recipes)),
        tracks_cooked=len({by_slug[slug].track for slug in cooked_slugs}),
        skills_total=len(catalogue),
        skills_learned=len(history.skills_learned() & catalogue),
    )


# -- page shell ------------------------------------------------------------


def _page(title: str, description: str, body: str, *, depth: int, active: str) -> str:
    up = "../" * depth
    nav = "".join(
        f'<a class="{"on" if key == active else ""}" href="{up}{href}">{_e(label)}</a>'
        for key, href, label in (
            ("index", "index.html", "Library"),
            ("log", "log.html", "Cooking log"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<link rel="stylesheet" href="{up}assets/site.css">
</head>
<body>
<nav class="topbar"><a class="brand" href="{up}index.html">{_e(SITE_TITLE)}</a>
<span class="links">{nav}</span></nav>
<main>
{body}
</main>
<footer>Built from the recipes in this repository by
<code>python send_recipe.py site</code>.</footer>
</body>
</html>
"""


def _progress_bar(stats: SiteStats) -> str:
    return (
        f'<div class="progress" role="img" aria-label="'
        f'{stats.cooked} of {stats.total} recipes cooked">'
        f'<div class="bar"><span style="width:{stats.percent}%"></span></div>'
        f'<p class="tally"><strong>{stats.cooked}</strong> of {stats.total} cooked'
        f' · <strong>{stats.tracks_cooked}</strong> of {stats.tracks_total} disciplines'
        f' · <strong>{stats.skills_learned}</strong> of {stats.skills_total} skills'
        f"</p></div>"
    )


# -- the index -------------------------------------------------------------


def _card(recipe: Recipe, cooked_on: str | None) -> str:
    haystack = " ".join([
        recipe.title, recipe.cuisine, recipe.track, recipe.slug,
        " ".join(recipe.skills), " ".join(recipe.tags), lead_paragraph(recipe.body),
    ]).lower()
    mark = (f'<span class="done" title="Cooked on {_e(cooked_on)}">✓</span>'
            if cooked_on else "")
    return f"""<li class="card" data-track="{_e(recipe.track)}" data-level="{recipe.level}"
  data-seasons="{_e(' '.join(recipe.seasons))}" data-cooked="{'yes' if cooked_on else 'no'}"
  data-search="{_e(haystack)}">
<a href="recipes/{_e(recipe.slug)}.html">
  <span class="card-top"><span class="lvl lvl{recipe.level}">Level {recipe.level}</span>
    <span class="track">{_e(recipe.track)}</span>{mark}</span>
  <h2>{_e(recipe.title)}</h2>
  <p class="blurb">{_e(truncate(lead_paragraph(recipe.body)))}</p>
  <p class="meta">{_e(_card_meta(recipe))}</p>
</a></li>"""


def _select(name: str, label: str, options: Iterable[tuple[str, str]]) -> str:
    items = "".join(f'<option value="{_e(value)}">{_e(text)}</option>'
                    for value, text in options)
    return (f'<label class="field"><span>{_e(label)}</span>'
            f'<select id="{name}" name="{name}">{items}</select></label>')


def render_index(recipes: Sequence[Recipe], history: History) -> str:
    stats = gather_stats(recipes, history)
    ordered = sorted(recipes, key=lambda recipe: (recipe.level, recipe.slug))
    cards = "\n".join(_card(recipe, history.last_sent_on(recipe.slug)) for recipe in ordered)

    cuisines = sorted({recipe.cuisine for recipe in recipes})
    filters = "".join([
        '<label class="field grow"><span>Search</span>'
        '<input id="q" type="search" placeholder="salmon, emulsion, pastry…"'
        ' autocomplete="off"></label>',
        _select("track", "Discipline",
                [("", "Any")] + [(track, track) for track in tracks_in(recipes)]),
        _select("level", "Level",
                [("", "Any")] + [(str(lvl), f"{lvl} — {LEVEL_NAMES[lvl]}")
                                 for lvl in range(1, MAX_LEVEL + 1)]),
        _select("season", "Season",
                [("", "Any")] + [(s, s) for s in ("spring", "summer", "autumn", "winter")]),
        _select("cooked", "Status",
                [("", "Everything"), ("no", "Not yet cooked"), ("yes", "Cooked")]),
    ])

    body = f"""<header class="hero">
  <p class="eyebrow">{_plural(stats.total, 'recipe')} · {stats.tracks_total} disciplines · five levels</p>
  <h1>{_e(TAGLINE)}</h1>
  <p class="lede">From a soft herb omelette to xiao long bao, a mole poblano and a
  self-directed pressure test — each recipe teaching a named technique the next ones
  build on.</p>
  {_progress_bar(stats)}
</header>

<form class="filters" id="filters" onsubmit="return false">{filters}
  <button type="button" id="reset" class="reset">Clear</button>
</form>
<p class="count" id="count">{_plural(len(ordered), 'recipe')}</p>
<ul class="grid" id="grid">
{cards}
</ul>
<p class="empty" id="empty" hidden>Nothing matches those filters.</p>
<script src="assets/filter.js"></script>"""
    return _page(SITE_TITLE, TAGLINE, body, depth=0, active="index")


# -- one recipe ------------------------------------------------------------


def _chips(label: str, values: Sequence[str]) -> str:
    if not values:
        return ""
    chips = "".join(f'<span class="chip">{_e(value)}</span>' for value in values)
    return f'<div class="chips"><span class="chips-label">{_e(label)}</span>{chips}</div>'


def render_recipe_page(recipe: Recipe, history: History,
                       neighbours: tuple[Recipe | None, Recipe | None]) -> str:
    cooked_on = history.last_sent_on(recipe.slug)
    banner = (f'<p class="cooked-banner">✓ Cooked on {_e(cooked_on)}</p>'
              if cooked_on else "")

    facts = "".join(
        f"<div><dt>{_e(label)}</dt><dd>{value}</dd></div>" for label, value in (
            ("Level", f'<span class="lvl lvl{recipe.level}">{recipe.level}</span> '
                      f"{_e(recipe.level_name)}"),
            ("Time", f"{recipe.minutes} minutes"),
            ("Serves", str(recipe.serves) if recipe.serves else "a drill, not a dish"),
            ("Cuisine", _e(recipe.cuisine)),
            ("Discipline", f'<a href="../index.html?track={_e(recipe.track)}">'
                           f"{_e(recipe.track)}</a>"),
            ("Season", _e(", ".join(recipe.seasons))),
        )
    )

    previous, following = neighbours
    def _link(recipe_or_none: Recipe | None, prefix: str) -> str:
        if recipe_or_none is None:
            return "<span></span>"
        return (f'<a href="{_e(recipe_or_none.slug)}.html">{prefix} '
                f"{_e(recipe_or_none.title)}</a>")

    source = (f'<p class="source">Inspired by {_e(recipe.source)}</p>'
              if recipe.source else "")

    body = f"""<article class="recipe">
  <p class="crumb"><a href="../index.html">← the library</a></p>
  {banner}
  <p class="eyebrow">{_e(recipe.track)} · level {recipe.level}, {_e(recipe.level_name)}</p>
  <h1>{_e(recipe.title)}</h1>
  <p class="lede">{_e(lead_paragraph(recipe.body))}</p>
  <dl class="facts">{facts}</dl>
  {_chips('Skills', recipe.skills)}
  {_chips('Kit', recipe.equipment)}
  {_chips('Tags', recipe.tags)}
  <div class="prose">{markdown_to_html(body_after_lead(recipe.body))}</div>
  {source}
</article>
<nav class="pager">{_link(previous, '←')}{_link(following, '→')}</nav>"""
    return _page(f"{recipe.title} · {SITE_TITLE}",
                 truncate(lead_paragraph(recipe.body), 200),
                 body, depth=1, active="index")


# -- the log ---------------------------------------------------------------


def render_log_page(recipes: Sequence[Recipe], history: History) -> str:
    stats = gather_stats(recipes, history)
    by_slug = {recipe.slug: recipe for recipe in recipes}

    rows = []
    for number, entry in enumerate(reversed(history.entries), start=1):
        week = history.count - number + 1
        recipe = by_slug.get(entry.slug)
        title = (f'<a href="recipes/{_e(entry.slug)}.html">{_e(entry.title)}</a>'
                 if recipe else _e(entry.title))
        skills = "".join(f'<span class="chip">{_e(skill)}</span>' for skill in entry.skills)
        track = f'<span class="track">{_e(recipe.track)}</span>' if recipe else ""
        rows.append(f"""<li>
  <p class="when"><time datetime="{_e(entry.date)}">{_e(entry.date)}</time>
    <span class="week">week {week}</span></p>
  <h2>{title}</h2>
  <p class="meta"><span class="lvl lvl{entry.level}">Level {entry.level}</span>{track}</p>
  <div class="chips">{skills}</div>
</li>""")

    timeline = ("<ol class=\"timeline\">" + "\n".join(rows) + "</ol>") if rows else (
        '<p class="empty">Nothing cooked yet. Friday will fix that.</p>')

    learned = sorted(history.skills_learned())
    bank = (f'<section class="bank"><h2>Skills in the bank</h2><div class="chips">'
            + "".join(f'<span class="chip">{_e(skill)}</span>' for skill in learned)
            + "</div></section>") if learned else ""

    body = f"""<header class="hero">
  <p class="eyebrow">The cooking log</p>
  <h1>{_plural(stats.cooked, 'recipe')} down, {stats.total - stats.cooked} to go</h1>
  {_progress_bar(stats)}
</header>
{timeline}
{bank}"""
    return _page(f"Cooking log · {SITE_TITLE}",
                 f"{stats.cooked} of {stats.total} recipes cooked so far.",
                 body, depth=0, active="log")


# -- assets ----------------------------------------------------------------

STYLESHEET = """/* Generated by recipe_club/site.py -- edit there, not here. */
:root {
  --bg: #f6f3ee; --card: #fffdf9; --ink: #2b2420; --muted: #7a6a58;
  --rule: #e7ded1; --accent: #c8842a; --accent-soft: #fbf6ee;
  --shadow: 0 1px 3px rgba(0,0,0,.08);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17140f; --card: #211c16; --ink: #ece4d8; --muted: #a2907a;
    --rule: #342c22; --accent: #e0a458; --accent-soft: #2a2117;
    --shadow: 0 1px 3px rgba(0,0,0,.4);
  }
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
body {
  margin: 0; background: var(--bg); color: var(--ink); line-height: 1.6;
  font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
  -webkit-text-size-adjust: 100%;
}
a { color: inherit; }
main { max-width: 1040px; margin: 0 auto; padding: 0 20px 64px; }

.topbar {
  display: flex; flex-wrap: wrap; gap: 12px 20px; align-items: baseline;
  max-width: 1040px; margin: 0 auto; padding: 20px;
}
.brand {
  font-size: 13px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent); text-decoration: none; font-weight: bold;
}
.topbar .links { margin-left: auto; display: flex; gap: 18px; font-size: 14px; }
.topbar .links a { color: var(--muted); text-decoration: none; }
.topbar .links a:hover, .topbar .links a.on { color: var(--ink); }

.hero { padding: 24px 0 8px; max-width: 46rem; }
.recipe > .eyebrow { margin-top: 24px; }
.eyebrow {
  margin: 0; font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
  color: var(--accent);
}
h1 { font-size: clamp(28px, 5vw, 40px); line-height: 1.2; margin: 10px 0 16px; }
.lede { margin: 0 0 20px; color: var(--muted); font-size: 17px; }

.progress { margin: 20px 0 8px; }
.bar {
  height: 8px; background: var(--rule); border-radius: 99px; overflow: hidden;
}
.bar span { display: block; height: 100%; background: var(--accent); }
.tally { margin: 8px 0 0; font-size: 14px; color: var(--muted); }
.tally strong { color: var(--ink); }

.filters {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end;
  margin: 28px 0 16px; padding: 16px; background: var(--card);
  border: 1px solid var(--rule); border-radius: 10px; box-shadow: var(--shadow);
}
.field { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.field > span { color: var(--muted); }
.field.grow { flex: 1 1 220px; }
input, select, .reset {
  font: inherit; font-size: 15px; padding: 8px 10px; color: var(--ink);
  background: var(--bg); border: 1px solid var(--rule); border-radius: 6px;
}
input:focus, select:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
.reset { cursor: pointer; color: var(--muted); }
.reset:hover { color: var(--ink); border-color: var(--muted); }
.count { margin: 0 0 16px; font-size: 14px; color: var(--muted); }

.grid {
  list-style: none; margin: 0; padding: 0; display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
}
.card { display: flex; }
.card a {
  display: flex; flex-direction: column; gap: 8px; flex: 1;
  padding: 18px; background: var(--card); border: 1px solid var(--rule);
  border-radius: 10px; box-shadow: var(--shadow); text-decoration: none;
  transition: transform .12s ease, border-color .12s ease;
}
.card a:hover { transform: translateY(-2px); border-color: var(--accent); }
.card h2 { margin: 0; font-size: 20px; line-height: 1.25; }
.card .blurb { margin: 0; font-size: 14px; color: var(--muted); flex: 1; }
.card .meta { margin: 0; font-size: 13px; color: var(--muted); }
.card-top { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.done { margin-left: auto; color: var(--accent); font-weight: bold; }

.lvl {
  font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px;
  letter-spacing: .06em; text-transform: uppercase; padding: 3px 7px;
  border-radius: 99px; background: var(--accent-soft); color: var(--accent);
  border: 1px solid currentColor; white-space: nowrap;
}
.lvl1 { color: #4e7a3f; } .lvl2 { color: #3f6f7a; } .lvl3 { color: #7a5c3f; }
.lvl4 { color: #8a4a2f; } .lvl5 { color: #7a3f52; }
@media (prefers-color-scheme: dark) {
  .lvl1 { color: #9ec98c; } .lvl2 { color: #8dc0cc; } .lvl3 { color: #d3ab7e; }
  .lvl4 { color: #e29a7c; } .lvl5 { color: #d98fa4; }
}
.track {
  font-family: ui-sans-serif, system-ui, sans-serif; font-size: 12px;
  color: var(--muted);
}
.empty { color: var(--muted); font-size: 15px; }

.recipe { max-width: 46rem; }
.crumb { margin: 16px 0 0; font-size: 14px; }
.crumb a { color: var(--muted); text-decoration: none; }
.crumb a:hover { color: var(--accent); }
.cooked-banner {
  margin: 16px 0 20px; padding: 8px 14px; display: inline-block; font-size: 14px;
  background: var(--accent-soft); color: var(--accent); border-radius: 99px;
}
.facts {
  display: grid; gap: 16px 28px; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  margin: 0 0 24px; padding: 20px; background: var(--card);
  border: 1px solid var(--rule); border-radius: 10px; font-size: 16px;
}
.facts dt {
  font-family: ui-sans-serif, system-ui, sans-serif; font-size: 11px;
  letter-spacing: .1em; text-transform: uppercase; color: var(--muted);
  margin-bottom: 4px;
}
.facts dd { margin: 0; }
.facts dd a { color: var(--accent); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 0 0 12px; }
.chips-label { font-size: 13px; color: var(--muted); margin-right: 4px; }
.chip {
  font-family: ui-sans-serif, system-ui, sans-serif; font-size: 12px;
  padding: 3px 9px; border-radius: 99px; background: var(--card);
  border: 1px solid var(--rule); color: var(--muted);
}
.prose { margin-top: 28px; font-size: 17px; }
.prose h3 {
  margin: 36px 0 12px; font-size: 13px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--accent);
  padding-bottom: 6px; border-bottom: 1px solid var(--rule);
}
.prose ul, .prose ol { padding-left: 22px; }
.prose li { margin: 6px 0; }
.prose code {
  font-size: .9em; background: var(--accent-soft); padding: 1px 5px; border-radius: 4px;
}
.source { margin-top: 32px; font-style: italic; color: var(--muted); font-size: 14px; }
.pager {
  display: flex; justify-content: space-between; gap: 16px; max-width: 46rem;
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--rule);
  font-size: 14px;
}
.pager a { color: var(--muted); text-decoration: none; }
.pager a:hover { color: var(--accent); }

.timeline { list-style: none; margin: 32px 0 0; padding: 0; }
.timeline li {
  padding: 18px 0 18px 20px; border-left: 2px solid var(--rule); position: relative;
}
.timeline li::before {
  content: ""; position: absolute; left: -6px; top: 26px; width: 10px; height: 10px;
  border-radius: 50%; background: var(--accent);
}
.timeline h2 { margin: 4px 0 8px; font-size: 21px; }
.timeline h2 a { text-decoration: none; }
.timeline h2 a:hover { color: var(--accent); }
.timeline .when { margin: 0; font-size: 13px; color: var(--muted); }
.timeline .week { margin-left: 10px; }
.timeline .meta { margin: 0 0 10px; display: flex; gap: 10px; align-items: center; }
.bank { margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--rule); }
.bank h2 { font-size: 15px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }

footer {
  max-width: 1040px; margin: 0 auto; padding: 24px 20px 40px;
  border-top: 1px solid var(--rule); color: var(--muted); font-size: 13px;
}
footer code { font-size: 12px; }
"""

FILTER_JS = """/* Generated by recipe_club/site.py -- edit there, not here. */
(function () {
  var grid = document.getElementById('grid');
  if (!grid) return;
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.card'));
  var count = document.getElementById('count');
  var empty = document.getElementById('empty');
  var fields = ['q', 'track', 'level', 'season', 'cooked'].map(function (id) {
    return document.getElementById(id);
  });
  var q = fields[0];

  function matches(card, query, track, level, season, cooked) {
    if (track && card.dataset.track !== track) return false;
    if (level && card.dataset.level !== level) return false;
    if (season && card.dataset.seasons.split(' ').indexOf(season) === -1
        && card.dataset.seasons.indexOf('any') === -1) return false;
    if (cooked && card.dataset.cooked !== cooked) return false;
    if (query && card.dataset.search.indexOf(query) === -1) return false;
    return true;
  }

  function apply() {
    var query = q.value.trim().toLowerCase();
    var values = fields.slice(1).map(function (field) { return field.value; });
    var shown = 0;
    cards.forEach(function (card) {
      var ok = matches(card, query, values[0], values[1], values[2], values[3]);
      card.hidden = !ok;
      if (ok) shown += 1;
    });
    count.textContent = shown === cards.length
      ? cards.length + ' recipes'
      : shown + ' of ' + cards.length + ' recipes';
    empty.hidden = shown !== 0;
    remember();
  }

  /* Keep the filters in the URL so a view can be linked to and reloaded.
     Opened from disk the origin is opaque and replaceState throws, which is
     fine -- the filtering above has already happened. */
  function remember() {
    var params = new URLSearchParams();
    fields.forEach(function (field) {
      if (field.value.trim()) params.set(field.id, field.value.trim());
    });
    var query = params.toString();
    try {
      history.replaceState(null, '', query ? '?' + query : location.pathname);
    } catch (e) { /* file:// */ }
  }

  function restore() {
    var params = new URLSearchParams(location.search);
    fields.forEach(function (field) {
      var value = params.get(field.id);
      if (value !== null) field.value = value;
    });
  }

  fields.forEach(function (field) {
    field.addEventListener('input', apply);
    field.addEventListener('change', apply);
  });
  document.getElementById('reset').addEventListener('click', function () {
    fields.forEach(function (field) { field.value = ''; });
    apply();
    q.focus();
  });

  restore();
  apply();
})();
"""


# -- building --------------------------------------------------------------


def build_site(recipes: Sequence[Recipe], history: History, out: Path) -> list[Path]:
    """Render the whole site into `out`, returning every file written."""
    ordered = sorted(recipes, key=lambda recipe: recipe.slug)
    pages = out / "recipes"
    assets = out / "assets"
    for directory in (out, pages, assets):
        directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def write(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        written.append(path)

    write(out / "index.html", render_index(ordered, history))
    write(out / "log.html", render_log_page(ordered, history))
    write(assets / "site.css", STYLESHEET)
    write(assets / "filter.js", FILTER_JS)
    # Pages would otherwise hand the output to Jekyll, which we do not want.
    write(out / ".nojekyll", "")

    for index, recipe in enumerate(ordered):
        neighbours = (ordered[index - 1] if index else None,
                      ordered[index + 1] if index + 1 < len(ordered) else None)
        write(pages / f"{recipe.slug}.html", render_recipe_page(recipe, history, neighbours))

    _prune(pages, {f"{recipe.slug}.html" for recipe in ordered})
    return written


def _prune(pages: Path, keep: set[str]) -> list[Path]:
    """Drop recipe pages whose Markdown file has gone. Only ever touches .html."""
    removed = []
    for stale in sorted(pages.glob("*.html")):
        if stale.name not in keep:
            stale.unlink()
            removed.append(stale)
    return removed
