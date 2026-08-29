"""Turning a pick into something worth reading on a Friday morning."""

from __future__ import annotations

import html
import re

from .history import History
from .library import LEVEL_NAMES, MAX_LEVEL, Recipe
from .selector import Pick


def subject_line(pick: Pick) -> str:
    return (f"Week {pick.week_number} · Level {pick.recipe.level} "
            f"{LEVEL_NAMES[pick.recipe.level]} · {pick.recipe.title}")


def _facts(recipe: Recipe) -> list[tuple[str, str]]:
    facts = [
        ("Level", f"{recipe.level}/{MAX_LEVEL} — {recipe.level_name}"),
        ("Time", f"{recipe.minutes} minutes"),
        ("Serves", str(recipe.serves)),
        ("Cuisine", recipe.cuisine),
    ]
    if recipe.skills:
        facts.append(("Skills", ", ".join(recipe.skills)))
    if recipe.equipment:
        facts.append(("Kit", ", ".join(recipe.equipment)))
    return facts


def _progress_line(history: History, total_recipes: int) -> str:
    done = history.count
    filled = round(20 * min(done / total_recipes, 1.0)) if total_recipes else 0
    bar = "█" * filled + "·" * (20 - filled)
    return f"{bar}  {done}/{total_recipes} recipes cooked"


def render_text(pick: Pick, history: History, total_recipes: int) -> str:
    recipe = pick.recipe
    lines = [
        subject_line(pick),
        "=" * len(subject_line(pick)),
        "",
    ]
    for label, value in _facts(recipe):
        lines.append(f"{label + ':':<10}{value}")
    lines.append("")
    if pick.reasons:
        lines.append("Why this one: " + "; ".join(pick.reasons) + ".")
        lines.append("")
    lines.append(recipe.body)
    lines.append("")
    lines.append("-" * 60)
    lines.append(_progress_line(history, total_recipes))
    if pick.new_skills:
        lines.append("New skills this week: " + ", ".join(pick.new_skills))
    known = sorted(history.skills_learned())
    if known:
        lines.append(f"Skills in the bank ({len(known)}): " + ", ".join(known))
    if recipe.source:
        lines.append(f"Inspired by: {recipe.source}")
    lines.append("")
    lines.append("Cook it, photograph it, write one line about what went wrong. That is the whole trick.")
    return "\n".join(lines)


_INLINE = (
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![\w*])\*([^*]+?)\*(?![\w*])"), r"<em>\1</em>"),
    (re.compile(r"`([^`]+?)`"), r"<code>\1</code>"),
)


def _inline(text: str) -> str:
    out = html.escape(text)
    for pattern, replacement in _INLINE:
        out = pattern.sub(replacement, out)
    return out


def markdown_to_html(text: str) -> str:
    """A deliberately small Markdown subset: headings, lists, paragraphs."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append("<p>" + "<br>".join(_inline(line) for line in paragraph) + "</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if list_items:
            items = "".join(f"<li>{item}</li>" for item in list_items)
            blocks.append(f"<{list_tag}>{items}</{list_tag}>")
            list_items.clear()
        list_tag = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            flush_list()
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            flush_list()
            depth = min(len(heading.group(1)) + 1, 6)
            blocks.append(f"<h{depth}>{_inline(heading.group(2))}</h{depth}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if bullet or ordered:
            wanted = "ul" if bullet else "ol"
            if list_tag != wanted:
                flush_paragraph()
                flush_list()
                list_tag = wanted
            list_items.append(_inline((bullet or ordered).group(1)))
            continue

        flush_list()
        paragraph.append(stripped)

    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def render_html(pick: Pick, history: History, total_recipes: int) -> str:
    recipe = pick.recipe
    facts = "".join(
        f"<tr><th align='left' style='padding:2px 12px 2px 0;color:#7a6a58;"
        f"font-weight:500;white-space:nowrap'>{html.escape(label)}</th>"
        f"<td style='padding:2px 0'>{html.escape(value)}</td></tr>"
        for label, value in _facts(recipe)
    )
    why = ""
    if pick.reasons:
        why = (f"<p style='margin:18px 0 0;padding:12px 16px;background:#fbf6ee;"
               f"border-left:3px solid #c8842a;border-radius:4px;font-size:14px'>"
               f"<strong>Why this one:</strong> {html.escape('; '.join(pick.reasons))}.</p>")

    known = sorted(history.skills_learned())
    footer_bits = [html.escape(_progress_line(history, total_recipes))]
    if pick.new_skills:
        footer_bits.append("New skills this week: " + html.escape(", ".join(pick.new_skills)))
    if known:
        footer_bits.append(f"Skills in the bank ({len(known)}): " + html.escape(", ".join(known)))
    if recipe.source:
        footer_bits.append("Inspired by: " + html.escape(recipe.source))

    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f6f3ee;
  font-family:Georgia,'Iowan Old Style',serif;color:#2b2420;line-height:1.6">
<div style="max-width:640px;margin:0 auto;background:#fffdf9;padding:32px;
  border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.08)">
  <p style="margin:0;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#c8842a">
    Week {pick.week_number} &middot; Level {recipe.level} &middot; {html.escape(recipe.level_name)}</p>
  <h1 style="margin:8px 0 20px;font-size:28px;line-height:1.25">{html.escape(recipe.title)}</h1>
  <table style="font-size:14px;border-collapse:collapse">{facts}</table>
  {why}
  <div style="margin-top:24px;font-size:16px">{markdown_to_html(recipe.body)}</div>
  <hr style="margin:32px 0 16px;border:0;border-top:1px solid #e7ded1">
  <p style="font-size:13px;color:#7a6a58;margin:0">
    {"<br>".join(footer_bits)}</p>
  <p style="font-size:13px;color:#7a6a58;margin:12px 0 0">
    Cook it, photograph it, write one line about what went wrong. That is the whole trick.</p>
</div></body></html>
"""
