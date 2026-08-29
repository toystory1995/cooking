"""Command line entry point: `python send_recipe.py --help`."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from .history import History
from .library import MAX_LEVEL, RecipeError, all_skills, load_library
from .mailer import MailConfig, MailConfigError, build_message, send_message
from .render import render_html, render_text, subject_line
from .selector import Pick, RECIPES_PER_LEVEL, choose_recipe, season_for, target_level

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECIPES = ROOT / "recipes"
DEFAULT_HISTORY = ROOT / "state" / "history.json"


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date as YYYY-MM-DD, got {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    # Shared options live on a parent parser so they work either side of the
    # subcommand -- `send_recipe.py --history x send` and `send_recipe.py send
    # --history x` both read naturally.
    # SUPPRESS keeps the subparser copies from overwriting a value that was
    # given before the subcommand; the real defaults are applied in main().
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--recipes", type=Path, default=argparse.SUPPRESS, metavar="DIR",
                        help="directory of recipe Markdown files (default: ./recipes)")
    common.add_argument("--history", type=Path, default=argparse.SUPPRESS, metavar="FILE",
                        help="cooking log to read and update (default: ./state/history.json)")

    parser = argparse.ArgumentParser(
        prog="send_recipe.py",
        parents=[common],
        description="Send yourself one recipe a week and work your way up to MasterChef.",
    )
    sub = parser.add_subparsers(dest="command")

    send = sub.add_parser("send", parents=[common],
                          help="pick this week's recipe and email it (the default)")
    send.add_argument("--dry-run", action="store_true",
                      help="print the recipe instead of sending it, and leave the log untouched")
    send.add_argument("--no-record", action="store_true", help="send, but do not write to the log")
    send.add_argument("--date", type=_parse_date, default=None, metavar="YYYY-MM-DD",
                      help="pretend today is this date (useful for previewing)")
    send.add_argument("--slug", default=None, help="force a specific recipe instead of choosing one")
    send.add_argument("--html-out", type=Path, default=None, metavar="FILE",
                      help="also write the HTML email to this file")

    show = sub.add_parser("show", parents=[common], help="print one recipe")
    show.add_argument("slug")

    sub.add_parser("list", parents=[common], help="list the library")
    sub.add_parser("stats", parents=[common], help="show progress through the library")
    sub.add_parser("validate", parents=[common], help="parse every recipe and report problems")

    return parser


# Options that take a value, so we can tell a command name from an option's argument.
_VALUE_OPTIONS = {"--recipes", "--history", "--date", "--slug", "--html-out"}


def inject_default_command(argv: list[str]) -> list[str]:
    """`send_recipe.py --dry-run` should mean `send_recipe.py send --dry-run`."""
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token in _VALUE_OPTIONS:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if token in COMMANDS:
            return argv
        break
    return ["send", *argv]


def _pick_for(args, recipes, history) -> Pick:
    today = getattr(args, "date", None) or date.today()
    if args.slug:
        by_slug = {recipe.slug: recipe for recipe in recipes}
        if args.slug not in by_slug:
            raise SystemExit(f"no recipe with slug {args.slug!r}. Try: send_recipe.py list")
        recipe = by_slug[args.slug]
        return Pick(
            recipe=recipe,
            target_level=target_level(history.count),
            new_skills=tuple(sorted(set(recipe.skills) - history.skills_learned())),
            week_number=history.count + 1,
            reasons=("you asked for this one",),
        )
    return choose_recipe(recipes, history, today)


def cmd_send(args, recipes, history) -> int:
    today = args.date or date.today()
    pick = _pick_for(args, recipes, history)
    subject = subject_line(pick)
    text = render_text(pick, history, len(recipes))
    html_body = render_html(pick, history, len(recipes))

    if args.html_out:
        args.html_out.parent.mkdir(parents=True, exist_ok=True)
        args.html_out.write_text(html_body, encoding="utf-8")
        print(f"HTML written to {args.html_out}", file=sys.stderr)

    if args.dry_run:
        print(text)
        print(f"\n[dry run] would send to MAIL_TO with subject: {subject}", file=sys.stderr)
        return 0

    try:
        config = MailConfig.from_env()
    except MailConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        print("hint: run with --dry-run to preview without sending.", file=sys.stderr)
        return 2

    send_message(config, build_message(config, subject, text, html_body))
    print(f"sent '{pick.recipe.title}' to {', '.join(config.recipients)}")

    if not args.no_record:
        history.record(pick.recipe.slug, pick.recipe.title, pick.recipe.level, pick.recipe.skills, today)
        history.save(args.history)
        print(f"logged to {args.history}")
    return 0


def cmd_show(args, recipes, history) -> int:
    by_slug = {recipe.slug: recipe for recipe in recipes}
    recipe = by_slug.get(args.slug)
    if recipe is None:
        print(f"no recipe with slug {args.slug!r}. Try: send_recipe.py list", file=sys.stderr)
        return 1
    print(f"{recipe.title}  [level {recipe.level} · {recipe.minutes} min · serves {recipe.serves}]")
    if recipe.skills:
        print("skills: " + ", ".join(recipe.skills))
    print()
    print(recipe.body)
    return 0


def cmd_list(args, recipes, history) -> int:
    done = history.sent_slugs
    print(f"{'':2} {'level':>5}  {'min':>4}  {'slug':<34} title")
    for recipe in sorted(recipes, key=lambda r: (r.level, r.slug)):
        mark = "✓" if recipe.slug in done else " "
        print(f"{mark:2} {recipe.level:>5}  {recipe.minutes:>4}  {recipe.slug:<34} {recipe.title}")
    print(f"\n{len(done)}/{len(recipes)} cooked")
    return 0


def cmd_stats(args, recipes, history) -> int:
    total = len(recipes)
    done = history.count
    level = target_level(done)
    filled = round(20 * min(done / total, 1.0)) if total else 0
    print(f"Cooked      {done}/{total}  [{'█' * filled}{'·' * (20 - filled)}]")
    print(f"Level       {level}/{MAX_LEVEL} (next level after "
          f"{RECIPES_PER_LEVEL - done % RECIPES_PER_LEVEL} more)")
    print(f"Season      {season_for(getattr(args, 'date', None) or date.today())}")

    counts = history.levels_cooked()
    if counts:
        breakdown = "  ".join(f"L{lvl}×{counts[lvl]}" for lvl in sorted(counts))
        print(f"Breakdown   {breakdown}")

    known = history.skills_learned()
    catalogue = all_skills(recipes)
    print(f"Skills      {len(known & set(catalogue))}/{len(catalogue)}")
    if known:
        print("  learned:  " + ", ".join(sorted(known)))
    todo = [skill for skill in catalogue if skill not in known]
    if todo:
        shown = ", ".join(todo[:12])
        if len(todo) > 12:
            shown += f", … and {len(todo) - 12} more"
        print("  to come:  " + shown)
    if history.last:
        print(f"Last sent   {history.last.date} — {history.last.title}")
    return 0


def cmd_validate(args, recipes, history) -> int:
    by_level: dict[int, int] = {}
    for recipe in recipes:
        by_level[recipe.level] = by_level.get(recipe.level, 0) + 1
    print(f"{len(recipes)} recipes parsed cleanly from {args.recipes}")
    for lvl in range(1, MAX_LEVEL + 1):
        print(f"  level {lvl}: {by_level.get(lvl, 0)}")
    print(f"{len(all_skills(recipes))} distinct skills")
    empty = [lvl for lvl in range(1, MAX_LEVEL + 1) if not by_level.get(lvl)]
    if empty:
        print("warning: no recipes at level(s) " + ", ".join(map(str, empty)), file=sys.stderr)
    return 0


COMMANDS = {
    "send": cmd_send,
    "show": cmd_show,
    "list": cmd_list,
    "stats": cmd_stats,
    "validate": cmd_validate,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(inject_default_command(list(sys.argv[1:] if argv is None else argv)))
    args.recipes = getattr(args, "recipes", None) or DEFAULT_RECIPES
    args.history = getattr(args, "history", None) or DEFAULT_HISTORY

    try:
        recipes = load_library(args.recipes)
    except RecipeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    history = History.load(args.history)
    return COMMANDS[args.command](args, recipes, history)
