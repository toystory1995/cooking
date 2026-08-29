# Weekly Recipe Club

One recipe, every Friday, getting harder as you go — from a soft herb omelette to xiao long
bao, a mole poblano and a self-directed pressure test. The library is 71 recipes across 20
disciplines, chosen so each one teaches a named technique the next ones build on. At one a
week that is about sixteen months.

No dependencies. Python 3.9+ and the standard library, nothing to install.

## Quick start

```bash
python send_recipe.py send --dry-run          # see what this Friday would send
python send_recipe.py plan 12                 # the next twelve Fridays
python send_recipe.py list                    # the library, ✓ marks what you've cooked
python send_recipe.py list --track dumplings  # one discipline
python send_recipe.py stats                   # progress, level, tracks, skills
python send_recipe.py show 63-croissants
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

## What's in the library

Twenty **tracks** — disciplines, not cuisines — so the course covers range rather than
depth in one corner:

| | |
|---|---|
| foundations, knife-skills, eggs-dairy | the basics and the drills |
| stocks-soups, sauces | stock, consommé, dashi, ramen, five kinds of emulsion, mole |
| meat, butchery, fish, offal, fire | jointing, filleting, live fire, sweetbreads, parfait |
| pasta, dumplings, rice-grains, bread | jiaozi to xiao long bao, sushi, biryani, sourdough |
| pastry, desserts | croissants, choux, macarons, tempering, entremet |
| fermentation, vegetables, modern, challenge | kimchi, dosa, agar, plating and mystery-box drills |

Cuisines span Chinese, Japanese, Indian, Korean, Thai, Nepali, Mexican, Peruvian,
Moroccan, Levantine, Nordic and the European canon. No single track is more than 15% of
the library — there is a test enforcing that.

Levels: **1** Foundations · **2** Confident cook · **3** Technique · **4** Restaurant
plate · **5** Pressure test.

## How the weekly pick works

`recipe_club/selector.py` treats the level as a **ceiling, not a preference**. Each week
the schedule says which level you have unlocked; only recipes at or below it are eligible.
Nothing can push you into a level you have not reached, and nothing is orphaned when you
move up, because everything below stays in play.

The pace scales with the library: `library ÷ 6`, so 71 recipes means eleven weeks per
level and the hardest third of the course falls in the second half of the year. Within the
eligible pool the pick is decided by:

1. **No repeats** until the whole library is cooked.
2. **Working near the ceiling** rather than well below it.
3. **Track rotation.** A discipline cooked in the last four weeks is penalised, hardest
   for last week; a track you have never touched gets a boost. In a full 71-week run no
   track ever appears twice in a row and none exceeds eight weeks in the first year.
4. **New skills**, then **season**, then avoiding the same cuisine twice running.

The capstone (`71-signature-dish-pressure-test`) is held back until everything else has
been cooked. Ties break on a hash of the recipe slug and the ISO week, so a `--dry-run` on
Tuesday shows exactly what Friday will send.

Want something specific this week? `--track` picks from one discipline:

```bash
python send_recipe.py send --dry-run --track dumplings
python send_recipe.py send --slug 65-xiao-long-bao     # or force one outright
```

## The cooking log

`state/history.json` records what was sent and when. It is what drives the progression, so
it gets committed after each send:

```json
{"schema": 1, "entries": [
  {"date": "2026-09-04", "slug": "10-roast-chicken-and-root-vegetables",
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
track: vegetables
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
must be `spring`, `summer`, `autumn`, `winter` or `any`, and `track` must be one of the
twenty in `recipe_club/library.py` (it defaults to `foundations`). Then check it:

```bash
python send_recipe.py validate
python send_recipe.py show salt-baked-celeriac
```

The frontmatter parser handles `key: value` and `- item` lists — that is the whole
grammar, which is why there is no YAML dependency.

## Layout

```
recipes/                 71 recipes, one Markdown file each
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

The 97 cases cover the parser, the selection rules (the level ceiling, track rotation, no
repeats, capstone last), the log, the renderers, the SMTP flow and every CLI subcommand.
They also re-parse and re-render every shipped recipe and assert the library stays
balanced — no track over 15%, at least fifteen non-European cuisines — so both a broken
recipe file and a lopsided library fail the build rather than the Friday email.
