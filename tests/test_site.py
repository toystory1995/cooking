import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

from recipe_club import cli
from recipe_club.history import History
from recipe_club.library import load_library, parse_recipe
from recipe_club.site import (body_after_lead, build_site, gather_stats, lead_paragraph,
                              render_index, render_log_page, render_recipe_page, truncate)

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 4)

FIELDS = {
    "title": "Test Dish",
    "level": 2,
    "minutes": 30,
    "serves": 4,
    "cuisine": "Italian",
    "track": "pasta",
}

BODY = """The opening line that sells the dish, spread
over two lines of Markdown.

## Ingredients
- One thing

## Method
1. Do it.
"""

LISTS = """seasons:
  - summer
skills:
  - searing
equipment:
  - a pan
tags:
  - weeknight
source: Escoffier
"""


def sample(slug: str = "test-dish", **overrides):
    """A one-off recipe, so the tests do not lean on the shipped library."""
    fields = "".join(f"{key}: {value}\n" for key, value in {**FIELDS, **overrides}.items())
    return parse_recipe(f"---\n{fields}{LISTS}---\n\n{BODY}", slug=slug)


class TextHelperTests(unittest.TestCase):
    def test_lead_paragraph_is_the_prose_before_the_first_heading(self):
        recipe = sample()
        self.assertEqual(
            lead_paragraph(recipe.body),
            "The opening line that sells the dish, spread over two lines of Markdown.")

    def test_lead_paragraph_strips_markdown_emphasis(self):
        self.assertEqual(lead_paragraph("A **bold** claim.\n\n## Ingredients"),
                         "A bold claim.")

    def test_lead_paragraph_is_empty_when_a_heading_comes_first(self):
        self.assertEqual(lead_paragraph("## Ingredients\n- salt"), "")

    def test_body_after_lead_drops_the_intro_but_keeps_everything_else(self):
        rest = body_after_lead(sample().body)
        self.assertTrue(rest.startswith("## Ingredients"))
        self.assertIn("## Method", rest)
        self.assertNotIn("sells the dish", rest)

    def test_body_after_lead_leaves_a_headingless_body_alone(self):
        self.assertEqual(body_after_lead("just prose"), "just prose")

    def test_truncate_breaks_on_a_word_and_adds_an_ellipsis(self):
        self.assertEqual(truncate("one two three", 7), "one two…")
        self.assertEqual(truncate("short", 20), "short")


class StatsTests(unittest.TestCase):
    def test_counts_only_recipes_still_in_the_library(self):
        recipes = [sample(), sample(slug="other")]
        history = History.empty()
        history.record("test-dish", "Test Dish", 2, ("searing",), TODAY)
        history.record("deleted-recipe", "Gone", 1, ("whisking",), TODAY)

        stats = gather_stats(recipes, history)
        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.cooked, 1)
        self.assertEqual(stats.tracks_cooked, 1)
        self.assertEqual(stats.skills_learned, 1)  # 'whisking' is not in the library
        self.assertEqual(stats.percent, 50)

    def test_percent_is_zero_for_an_empty_library(self):
        self.assertEqual(gather_stats([], History.empty()).percent, 0)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.recipes = load_library(ROOT / "recipes")
        self.history = History.empty()
        self.history.record("13-kimchi", "Baechu Kimchi", 1, ("brining",), TODAY)
        self.html = render_index(self.recipes, self.history)

    def test_every_recipe_gets_a_card_and_a_link(self):
        for recipe in self.recipes:
            self.assertIn(f'href="recipes/{recipe.slug}.html"', self.html)
        self.assertEqual(self.html.count('class="card"'), len(self.recipes))

    def test_cards_carry_the_data_the_filters_read(self):
        self.assertIn('data-track="dumplings"', self.html)
        self.assertIn('data-level="5"', self.html)
        self.assertIn('data-cooked="yes"', self.html)
        self.assertIn('data-cooked="no"', self.html)

    def test_search_index_includes_skills_and_cuisine(self):
        card = [line for line in self.html.splitlines()
                if 'data-search=' in line and "kimchi" in line][0]
        self.assertIn("lacto-fermentation", card)
        self.assertIn("korean", card)

    def test_cooked_recipes_are_marked(self):
        self.assertIn("Cooked on 2026-09-04", self.html)

    def test_drills_do_not_claim_to_serve_nobody(self):
        self.assertNotIn("serves 0", self.html)


class RecipePageTests(unittest.TestCase):
    def test_page_has_the_recipe_and_its_facts(self):
        recipe = sample()
        page = render_recipe_page(recipe, History.empty(), (None, None))
        self.assertIn("<title>Test Dish · Weekly Recipe Club</title>", page)
        self.assertIn("30 minutes", page)
        self.assertIn("Italian", page)
        self.assertIn("Escoffier", page)
        self.assertIn("<li>One thing</li>", page)
        self.assertIn('href="../index.html?track=pasta"', page)

    def test_the_lede_is_not_repeated_in_the_body(self):
        page = render_recipe_page(sample(), History.empty(), (None, None))
        prose = page[page.index('<div class="prose">'):]
        self.assertIn("sells the dish", page)
        self.assertNotIn("sells the dish", prose)

    def test_a_drill_says_so_instead_of_serving_zero(self):
        page = render_recipe_page(sample(serves=0), History.empty(), (None, None))
        self.assertIn("a drill, not a dish", page)

    def test_neighbours_become_previous_and_next_links(self):
        previous, following = sample(slug="a-dish"), sample(slug="z-dish")
        page = render_recipe_page(sample(), History.empty(), (previous, following))
        self.assertIn('href="a-dish.html"', page)
        self.assertIn('href="z-dish.html"', page)

    def test_a_cooked_recipe_shows_when(self):
        history = History.empty()
        history.record("test-dish", "Test Dish", 2, (), TODAY)
        page = render_recipe_page(sample(), history, (None, None))
        self.assertIn("Cooked on 2026-09-04", page)

    def test_titles_are_escaped(self):
        recipe = sample(title="Soup & <script>alert(1)</script>")
        page = render_recipe_page(recipe, History.empty(), (None, None))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&amp;", page)


class LogPageTests(unittest.TestCase):
    def test_entries_run_newest_first_and_link_to_the_recipe(self):
        recipes = load_library(ROOT / "recipes")
        history = History.empty()
        history.record("13-kimchi", "Baechu Kimchi", 1, ("brining",), date(2026, 9, 4))
        history.record("25-focaccia", "Focaccia", 2, ("hydration",), date(2026, 9, 11))

        page = render_log_page(recipes, history)
        self.assertLess(page.index("Focaccia"), page.index("Baechu Kimchi"))
        self.assertIn('href="recipes/13-kimchi.html"', page)
        self.assertIn("week 2", page)
        self.assertIn("2 recipes down, 76 to go", page)

    def test_an_empty_log_says_so(self):
        page = render_log_page(load_library(ROOT / "recipes"), History.empty())
        self.assertIn("Nothing cooked yet", page)

    def test_a_recipe_that_has_since_been_deleted_is_listed_without_a_link(self):
        history = History.empty()
        history.record("gone", "Vanished Dish", 1, (), TODAY)
        page = render_log_page([sample()], history)
        self.assertIn("Vanished Dish", page)
        self.assertNotIn('href="recipes/gone.html"', page)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "site"

    def tearDown(self):
        self._tmp.cleanup()

    def test_builds_a_page_per_recipe_plus_the_shell(self):
        recipes = load_library(ROOT / "recipes")
        written = build_site(recipes, History.empty(), self.out)

        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue((self.out / "log.html").exists())
        self.assertTrue((self.out / "assets" / "site.css").exists())
        self.assertTrue((self.out / "assets" / "filter.js").exists())
        self.assertTrue((self.out / ".nojekyll").exists())
        self.assertEqual(len(list((self.out / "recipes").glob("*.html"))), len(recipes))
        self.assertEqual(len(written), len(recipes) + 5)

    def test_every_shipped_recipe_renders(self):
        recipes = load_library(ROOT / "recipes")
        build_site(recipes, History.empty(), self.out)
        for recipe in recipes:
            page = (self.out / "recipes" / f"{recipe.slug}.html").read_text(encoding="utf-8")
            self.assertIn("<h1>", page)
            self.assertIn("stylesheet", page)
            self.assertTrue(page.rstrip().endswith("</html>"))

    def test_rebuilding_drops_pages_whose_recipe_has_gone(self):
        build_site([sample(), sample(slug="doomed")], History.empty(), self.out)
        self.assertTrue((self.out / "recipes" / "doomed.html").exists())

        build_site([sample()], History.empty(), self.out)
        self.assertFalse((self.out / "recipes" / "doomed.html").exists())
        self.assertTrue((self.out / "recipes" / "test-dish.html").exists())

    def test_pruning_leaves_anything_that_is_not_a_recipe_page_alone(self):
        build_site([sample()], History.empty(), self.out)
        stray = self.out / "recipes" / "notes.txt"
        stray.write_text("keep me", encoding="utf-8")

        build_site([sample()], History.empty(), self.out)
        self.assertTrue(stray.exists())


class SiteCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        argv = ["--recipes", str(ROOT / "recipes"),
                "--history", str(ROOT / "state" / "history.json"), *args]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_site_command_writes_the_site(self):
        out_dir = self.tmp / "public"
        code, out, _ = self.run_cli("site", "--out", str(out_dir))
        self.assertEqual(code, 0)
        self.assertIn("pages written", out)
        self.assertTrue((out_dir / "index.html").exists())

    def test_site_reflects_the_real_cooking_log(self):
        out_dir = self.tmp / "public"
        self.run_cli("site", "--out", str(out_dir))
        log = (out_dir / "log.html").read_text(encoding="utf-8")
        self.assertIn("Baechu Kimchi", log)

    def test_site_is_recognised_as_a_command_not_a_bare_send(self):
        self.assertEqual(cli.inject_default_command(["site", "--out", "public"]),
                         ["site", "--out", "public"])


if __name__ == "__main__":
    unittest.main()
