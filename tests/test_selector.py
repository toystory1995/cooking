import unittest
from datetime import date, timedelta
from pathlib import Path

from recipe_club.history import History
from recipe_club.library import load_library, parse_recipe
from recipe_club.selector import choose_recipe, season_for, target_level

ROOT = Path(__file__).resolve().parent.parent


def make(slug, level=1, skills=(), seasons=("any",), cuisine="Test", tags=()):
    lines = [
        "---", f"title: {slug.title()}", f"level: {level}", "minutes: 30",
        f"cuisine: {cuisine}", "seasons:",
    ]
    lines += [f"  - {s}" for s in seasons]
    if skills:
        lines += ["skills:"] + [f"  - {s}" for s in skills]
    if tags:
        lines += ["tags:"] + [f"  - {t}" for t in tags]
    lines += ["---", "", "## Method", "1. Cook it."]
    return parse_recipe("\n".join(lines) + "\n", slug=slug)


class TargetLevelTests(unittest.TestCase):
    def test_starts_at_one_and_climbs(self):
        self.assertEqual(target_level(0), 1)
        self.assertEqual(target_level(4), 1)
        self.assertEqual(target_level(5), 2)
        self.assertEqual(target_level(12), 3)

    def test_caps_at_max(self):
        self.assertEqual(target_level(500), 5)

    def test_custom_pace(self):
        self.assertEqual(target_level(2, per_level=2), 2)

    def test_rejects_zero_pace(self):
        with self.assertRaises(ValueError):
            target_level(1, per_level=0)


class SeasonTests(unittest.TestCase):
    def test_months_map_to_seasons(self):
        self.assertEqual(season_for(date(2026, 1, 15)), "winter")
        self.assertEqual(season_for(date(2026, 4, 15)), "spring")
        self.assertEqual(season_for(date(2026, 7, 15)), "summer")
        self.assertEqual(season_for(date(2026, 10, 15)), "autumn")


class ChooseRecipeTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 4)

    def test_empty_library_is_an_error(self):
        with self.assertRaises(ValueError):
            choose_recipe([], History.empty(), self.today)

    def test_prefers_the_current_level(self):
        recipes = [make("easy", level=1), make("hard", level=5)]
        pick = choose_recipe(recipes, History.empty(), self.today)
        self.assertEqual(pick.recipe.slug, "easy")

    def test_level_climbs_with_experience(self):
        recipes = [make("easy", level=1), make("mid", level=3)]
        history = History.empty()
        for index in range(10):
            history.record(f"other-{index}", "x", 1, (), self.today)
        pick = choose_recipe(recipes, history, self.today)
        self.assertEqual(pick.recipe.slug, "mid")

    def test_does_not_repeat_until_library_is_exhausted(self):
        recipes = [make(f"r{i}", level=1) for i in range(6)]
        history = History.empty()
        day = self.today
        seen = []
        for _ in range(6):
            pick = choose_recipe(recipes, history, day)
            seen.append(pick.recipe.slug)
            history.record(pick.recipe.slug, pick.recipe.title, pick.recipe.level,
                           pick.recipe.skills, day)
            day += timedelta(days=7)
        self.assertEqual(len(set(seen)), 6)

    def test_second_pass_starts_over(self):
        recipes = [make("a"), make("b")]
        history = History.empty()
        history.record("a", "A", 1, (), self.today)
        history.record("b", "B", 1, (), self.today + timedelta(days=7))
        pick = choose_recipe(recipes, history, self.today + timedelta(days=14))
        self.assertEqual(pick.recipe.slug, "a")  # least recently cooked
        self.assertIn("second pass", " ".join(pick.reasons))

    def test_prefers_unseen_skills(self):
        recipes = [
            make("known", level=1, skills=("searing",)),
            make("fresh", level=1, skills=("braising", "glazing", "carving")),
        ]
        history = History.empty()
        history.record("elsewhere", "x", 1, ("searing",), self.today)
        pick = choose_recipe(recipes, history, self.today)
        self.assertEqual(pick.recipe.slug, "fresh")

    def test_out_of_season_is_penalised(self):
        recipes = [make("winter-dish", seasons=("winter",)), make("autumn-dish", seasons=("autumn",))]
        pick = choose_recipe(recipes, History.empty(), date(2026, 10, 2))
        self.assertEqual(pick.recipe.slug, "autumn-dish")

    def test_capstone_is_held_back_until_last(self):
        recipes = [make("ordinary", level=5), make("final", level=5, tags=("capstone",))]
        pick = choose_recipe(recipes, History.empty(), self.today)
        self.assertEqual(pick.recipe.slug, "ordinary")

        history = History.empty()
        history.record("ordinary", "Ordinary", 5, (), self.today)
        pick = choose_recipe(recipes, history, self.today + timedelta(days=7))
        self.assertEqual(pick.recipe.slug, "final")

    def test_same_week_is_deterministic(self):
        recipes = [make(f"r{i}", level=1) for i in range(8)]
        first = choose_recipe(recipes, History.empty(), self.today)
        second = choose_recipe(recipes, History.empty(), self.today)
        self.assertEqual(first.recipe.slug, second.recipe.slug)

    def test_week_number_tracks_history(self):
        recipes = [make("a"), make("b")]
        history = History.empty()
        history.record("a", "A", 1, (), self.today)
        self.assertEqual(choose_recipe(recipes, history, self.today).week_number, 2)


class FullLibraryProgressionTests(unittest.TestCase):
    def test_a_year_of_fridays_covers_the_library_without_repeats(self):
        recipes = load_library(ROOT / "recipes")
        history = History.empty()
        day = date(2026, 9, 4)
        for _ in range(len(recipes)):
            pick = choose_recipe(recipes, history, day)
            history.record(pick.recipe.slug, pick.recipe.title, pick.recipe.level,
                           pick.recipe.skills, day)
            day += timedelta(days=7)
        self.assertEqual(len(history.sent_slugs), len(recipes))

    def test_difficulty_trends_upward(self):
        recipes = load_library(ROOT / "recipes")
        history = History.empty()
        day = date(2026, 9, 4)
        levels = []
        for _ in range(15):
            pick = choose_recipe(recipes, history, day)
            levels.append(pick.recipe.level)
            history.record(pick.recipe.slug, pick.recipe.title, pick.recipe.level,
                           pick.recipe.skills, day)
            day += timedelta(days=7)
        self.assertLessEqual(max(levels[:5]), 2)
        self.assertGreaterEqual(sum(levels[10:]) / 5, sum(levels[:5]) / 5 + 1)

    def test_capstone_is_the_last_recipe_sent(self):
        recipes = load_library(ROOT / "recipes")
        history = History.empty()
        day = date(2026, 9, 4)
        for _ in range(len(recipes)):
            pick = choose_recipe(recipes, history, day)
            history.record(pick.recipe.slug, pick.recipe.title, pick.recipe.level,
                           pick.recipe.skills, day)
            day += timedelta(days=7)
        last = history.entries[-1]
        capstone = next(r for r in recipes if "capstone" in r.tags)
        self.assertEqual(last.slug, capstone.slug)


if __name__ == "__main__":
    unittest.main()
