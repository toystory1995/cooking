# Weekly Recipe Club

One recipe, every Friday, getting harder as you go — from a soft herb omelette to a Beef
Wellington and a self-directed pressure test. The library is 26 recipes chosen so that
each one teaches a named technique the next ones build on.

No dependencies. Python 3.9+ and the standard library, nothing to install.

## Quick start

```bash
python send_recipe.py send --dry-run   # see what this Friday would send
python send_recipe.py list             # the whole library, ✓ marks what you've cooked
python send_recipe.py stats            # progress, level, skills banked
python send_recipe.py show 23-croissants
```

To actually send, set six environment variables and drop `--dry-run`:

```bash
export SMTP_HOST=smtp.fastmail.com
export SMTP_PORT=587           # 465 switches to implicit TLS automatically
export SMTP_USERNAME=you@example.com
export SMTP_PASSWORD=an-app-specific-password
export MAIL_FROM=you@example.com
export MAIL_TO=you@example.com  # comma-separated for more than one cook

python send_recipe.py send
```

Optional: `MAIL_FROM_NAME`, `SMTP_STARTTLS`, `SMTP_SSL`.

> Use an **app-specific password**, never your account password, and keep it in a secret
> store rather than a file in this repo. iCloud, Gmail and Fastmail all issue them.

## How the weekly pick works

`recipe_club/selector.py` chooses the week's recipe by, in order of weight:

1. **No repeats** until the whole library is cooked.
2. **Difficulty progression.** You start at level 1 and move up a level every 5 recipes
   cooked, so the library takes about half a year to climb. Recipes near your current
   level score highest; a stretch upward is preferred to a step back down.
3. **New skills.** Recipes teaching techniques you have not met yet are favoured.
4. **Season and variety.** Seasonal recipes get a boost in their season, and the same
   cuisine two weeks running is penalised.

The capstone (`26-signature-dish-pressure-test`) is held back until everything else has
been cooked. Ties break on a hash of the recipe slug and the ISO week, so a `--dry-run` on
Tuesday shows exactly what Friday will send.

Levels: **1** Foundations · **2** Confident cook · **3** Technique · **4** Restaurant
plate · **5** Pressure test.

## The cooking log

`state/history.json` records what was sent and when. It is what drives the progression, so
it gets committed after each send:

```json
{"schema": 1, "entries": [
  {"date": "2026-09-04", "slug": "05-roast-chicken-and-root-vegetables",
   "title": "Roast Chicken over Root Vegetables", "level": 1,
   "skills": ["roasting", "trussing", "temperature probing", "carving"]}
]}
```

If you cook something on your own, add an entry by hand — the picker will take it into
account. To restart the whole course, empty `entries`.

## Scheduling it

### GitHub Actions (nothing of yours has to be switched on)

`.github/workflows/weekly-recipe.yml` runs at 07:00 UTC every Friday. Add the SMTP values
as repository secrets under **Settings → Secrets and variables → Actions**: `SMTP_HOST`,
`SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM`, `MAIL_TO`. The workflow
validates the library, runs the tests, sends the mail and commits the updated log.

Use **Run workflow** on the Actions tab to test it — tick *dry run* for a no-send
rehearsal, or pass a slug to force a particular recipe.

### Or cron on your own machine

```cron
0 7 * * 5 cd /path/to/cooking && /usr/bin/python3 send_recipe.py send >> /tmp/recipe.log 2>&1
```

Put the SMTP variables in the crontab or source them from a file the job reads.

## Adding your own recipes

Drop a Markdown file in `recipes/`. The filename (without `.md`) becomes the slug.

```markdown
---
title: Salt-Baked Celeriac
level: 3
minutes: 90
serves: 4
cuisine: Modern European
seasons:
  - autumn
  - winter
skills:
  - salt crust
  - vegetable roasting
equipment:
  - roasting tray
tags:
  - vegetarian
source: optional attribution
---

## Ingredients
- ...

## Method
1. ...

## What you're learning
...
```

`title`, `level` (1–5) and `minutes` are required; everything else has a default. Seasons
must be `spring`, `summer`, `autumn`, `winter` or `any`. Then check it:

```bash
python send_recipe.py validate
python send_recipe.py show salt-baked-celeriac
```

The frontmatter parser handles `key: value` and `- item` lists — that is the whole
grammar, which is why there is no YAML dependency.

## Layout

```
recipes/                 26 recipes, one Markdown file each
recipe_club/
  library.py             parsing and validating the library
  selector.py            which recipe this week, and why
  history.py             the cooking log
  render.py              plain-text and HTML emails
  mailer.py              SMTP delivery
  cli.py                 the command line
send_recipe.py           entry point
state/history.json       what you have cooked
tests/                   unittest suite, no dependencies
```

## Tests

```bash
python -m unittest discover -s tests -t . -q
```

The suite covers the parser, the selection rules (progression, no repeats, capstone last),
the log, the renderers and every CLI subcommand — and it re-parses and re-renders every
shipped recipe, so a broken recipe file fails the build rather than the Friday email.
