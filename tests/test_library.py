import unittest
from pathlib import Path

from recipe_club.library import (MAX_LEVEL, VALID_TRACKS, RecipeError, all_skills,
                                 load_library, parse_frontmatter, parse_recipe,
                                 split_frontmatter, tracks_in)

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = """---
title: Test Dish
level: 2
minutes: 30
serves: 4
cuisine: Italian
track: pasta
seasons:
  - summer
  - autumn
skills:
  - searing
  - deglazing
---

## Ingredients
- One thing
"""


class ParseFrontmatterTests(unittest.TestCase):
    def test_scalars_and_lists(self):
        data = parse_frontmatter("title: A\nskills:\n  - x\n  - y\nlevel: 3")
        self.assertEqual(data, {"title": "A", "skills": ["x", "y"], "level": "3"})

    def test_blank_lines_and_comments_ignored(self):
        data = parse_frontmatter("# note\n\ntitle: A\n")
        self.assertEqual(data, {"title": "A"})

    def test_value_may_contain_colon(self):
        data = parse_frontmatter("source: Escoffier: Le Guide Culinaire")
        self.assertEqual(data["source"], "Escoffier: Le Guide Culinaire")

    def test_list_item_before_key_is_an_error(self):
        with self.assertRaises(RecipeError):
            parse_frontmatter("- orphan")

    def test_line_without_colon_is_an_error(self):
        with self.assertRaises(RecipeError):
            parse_frontmatter("title A")


class SplitFrontmatterTests(unittest.TestCase):
    def test_splits_body_from_header(self):
        front, body = split_frontmatter(SAMPLE)
        self.assertIn("title: Test Dish", front)
        self.assertTrue(body.startswith("## Ingredients"))

    def test_missing_frontmatter(self):
        with self.assertRaises(RecipeError):
            split_frontmatter("# Just a heading\n")

    def test_unclosed_frontmatter(self):
        with self.assertRaises(RecipeError):
            split_frontmatter("---\ntitle: A\n")


class ParseRecipeTests(unittest.TestCase):
    def test_fields(self):
        recipe = parse_recipe(SAMPLE, slug="test-dish")
        self.assertEqual(recipe.title, "Test Dish")
        self.assertEqual(recipe.level, 2)
        self.assertEqual(recipe.minutes, 30)
        self.assertEqual(recipe.serves, 4)
        self.assertEqual(recipe.skills, ("searing", "deglazing"))
        self.assertEqual(recipe.seasons, ("summer", "autumn"))

    def test_track(self):
        self.assertEqual(parse_recipe(SAMPLE, slug="test-dish").track, "pasta")

    def test_unknown_track(self):
        with self.assertRaises(RecipeError):
            parse_recipe("---\ntitle: A\nlevel: 1\nminutes: 5\ntrack: baking\n---\n\nb\n",
                         slug="a")

    def test_defaults(self):
        recipe = parse_recipe(
            "---\ntitle: A\nlevel: 1\nminutes: 5\n---\n\nbody\n", slug="a")
        self.assertEqual(recipe.seasons, ("any",))
        self.assertEqual(recipe.track, "foundations")
        self.assertEqual(recipe.serves, 2)
        self.assertEqual(recipe.skills, ())

    def test_in_season(self):
        recipe = parse_recipe(SAMPLE, slug="test-dish")
        self.assertTrue(recipe.in_season("summer"))
        self.assertFalse(recipe.in_season("winter"))
        anytime = parse_recipe("---\ntitle: A\nlevel: 1\nminutes: 5\n---\n\nbody\n", slug="a")
        self.assertTrue(anytime.in_season("winter"))

    def test_missing_required_field(self):
        with self.assertRaises(RecipeError):
            parse_recipe("---\ntitle: A\nminutes: 5\n---\n\nbody\n", slug="a")

    def test_level_out_of_range(self):
        with self.assertRaises(RecipeError):
            parse_recipe("---\ntitle: A\nlevel: 9\nminutes: 5\n---\n\nbody\n", slug="a")

    def test_non_numeric_minutes(self):
        with self.assertRaises(RecipeError):
            parse_recipe("---\ntitle: A\nlevel: 1\nminutes: soon\n---\n\nbody\n", slug="a")

    def test_unknown_season(self):
        with self.assertRaises(RecipeError):
            parse_recipe(
                "---\ntitle: A\nlevel: 1\nminutes: 5\nseasons:\n  - monsoon\n---\n\nbody\n",
                slug="a")

    def test_empty_body(self):
        with self.assertRaises(RecipeError):
            parse_recipe("---\ntitle: A\nlevel: 1\nminutes: 5\n---\n\n\n", slug="a")


class RealLibraryTests(unittest.TestCase):
    """The shipped library must always parse and stay balanced."""

    @classmethod
    def setUpClass(cls):
        cls.recipes = load_library(ROOT / "recipes")

    def test_every_recipe_parses(self):
        self.assertGreaterEqual(len(self.recipes), 60)

    def test_every_level_is_represented(self):
        levels = {recipe.level for recipe in self.recipes}
        self.assertEqual(levels, set(range(1, MAX_LEVEL + 1)))

    def test_every_recipe_teaches_a_skill(self):
        for recipe in self.recipes:
            with self.subTest(recipe.slug):
                self.assertTrue(recipe.skills, f"{recipe.slug} lists no skills")

    def test_bodies_have_a_method(self):
        for recipe in self.recipes:
            with self.subTest(recipe.slug):
                self.assertIn("What you're learning", recipe.body)

    def test_skills_are_catalogued(self):
        self.assertGreater(len(all_skills(self.recipes)), 30)

    def test_tracks_are_valid_and_broadly_covered(self):
        covered = tracks_in(self.recipes)
        self.assertGreaterEqual(len(covered), 15)
        self.assertTrue(set(covered) <= set(VALID_TRACKS))

    def test_no_track_dominates_the_library(self):
        counts = {}
        for recipe in self.recipes:
            counts[recipe.track] = counts.get(recipe.track, 0) + 1
        biggest, count = max(counts.items(), key=lambda item: item[1])
        self.assertLessEqual(count / len(self.recipes), 0.15,
                             f"{biggest} is {count}/{len(self.recipes)} of the library")

    def test_cuisines_are_not_all_european(self):
        european = {"French", "Italian", "British", "Modern European", "Spanish",
                    "Polish", "Nordic", "Mediterranean", "Modern", "Foundations", "Yours"}
        other = [r for r in self.recipes if r.cuisine not in european]
        self.assertGreaterEqual(len(other), 15)

    def test_exactly_one_capstone(self):
        capstones = [r for r in self.recipes if "capstone" in r.tags]
        self.assertEqual(len(capstones), 1)

    def test_missing_directory(self):
        with self.assertRaises(RecipeError):
            load_library(ROOT / "no-such-directory")


if __name__ == "__main__":
    unittest.main()
