import io
import json
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr
from datetime import date
from pathlib import Path

from recipe_club import cli
from recipe_club.history import Entry, History
from recipe_club.library import load_library, parse_recipe
from recipe_club.mailer import MailConfig, MailConfigError, build_message, send_message
from recipe_club.render import (markdown_to_html, render_html, render_markdown,
                                render_text, subject_line)
from recipe_club.selector import choose_recipe

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 9, 4)


class HistoryTests(unittest.TestCase):
    def test_missing_file_gives_empty_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = History.load(Path(tmp) / "nope.json")
            self.assertEqual(history.count, 0)
            self.assertIsNone(history.last)

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "history.json"
            history = History.empty(path)
            history.record("omelette", "Omelette", 1, ("egg control",), TODAY)
            history.save()

            reloaded = History.load(path)
            self.assertEqual(reloaded.count, 1)
            self.assertEqual(reloaded.last.slug, "omelette")
            self.assertEqual(reloaded.skills_learned(), {"egg control"})
            self.assertEqual(json.loads(path.read_text())["schema"], 1)

    def test_queries(self):
        history = History.empty()
        history.record("a", "A", 1, ("x",), TODAY)
        history.record("b", "B", 2, ("y",), date(2026, 9, 11))
        history.record("a", "A", 1, ("x",), date(2026, 9, 18))
        self.assertEqual(history.sent_slugs, {"a", "b"})
        self.assertEqual(history.times_sent("a"), 2)
        self.assertEqual(history.last_sent_on("a"), "2026-09-18")
        self.assertIsNone(history.last_sent_on("zzz"))
        self.assertEqual(history.levels_cooked(), {1: 2, 2: 1})

    def test_entry_tolerates_sparse_json(self):
        entry = Entry.from_dict({"date": "2026-01-01", "slug": "x"})
        self.assertEqual(entry.title, "x")
        self.assertEqual(entry.level, 1)

    def test_save_without_path_is_an_error(self):
        with self.assertRaises(ValueError):
            History.empty().save()


class MarkdownTests(unittest.TestCase):
    def test_headings_lists_and_paragraphs(self):
        html = markdown_to_html("## Ingredients\n- a\n- b\n\n1. first\n2. second\n\ntext")
        self.assertIn("<h3>Ingredients</h3>", html)
        self.assertIn("<ul><li>a</li><li>b</li></ul>", html)
        self.assertIn("<ol><li>first</li><li>second</li></ol>", html)
        self.assertIn("<p>text</p>", html)

    def test_inline_formatting(self):
        self.assertIn("<strong>74°C</strong>", markdown_to_html("Cook to **74°C**"))
        self.assertIn("<em>fond</em>", markdown_to_html("the *fond* is flavour"))

    def test_html_is_escaped(self):
        self.assertIn("&lt;script&gt;", markdown_to_html("<script>alert(1)</script>"))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.recipes = load_library(ROOT / "recipes")
        self.history = History.empty()
        self.history.record("prior", "Prior", 1, ("searing",), TODAY)
        self.pick = choose_recipe(self.recipes, self.history, TODAY)

    def test_subject_line(self):
        subject = subject_line(self.pick)
        self.assertIn("Week 2", subject)
        self.assertIn(self.pick.recipe.title, subject)

    def test_text_email_contains_the_method_and_progress(self):
        text = render_text(self.pick, self.history, len(self.recipes))
        self.assertIn(self.pick.recipe.body.splitlines()[0], text)
        self.assertIn(f"1/{len(self.recipes)} recipes cooked", text)
        self.assertIn("Skills in the bank", text)

    def test_markdown_email_is_valid_markdown(self):
        md = render_markdown(self.pick, self.history, len(self.recipes))
        self.assertIn("**Week 2", md)
        self.assertIn("|---|---|", md)
        self.assertIn(self.pick.recipe.body.splitlines()[0], md)
        self.assertIn("<details>", md)
        self.assertNotIn("<script", md.lower())

    def test_html_email_is_self_contained(self):
        html = render_html(self.pick, self.history, len(self.recipes))
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn("</html>", html)
        self.assertNotIn("<script", html.lower())

    def test_every_recipe_renders(self):
        for recipe in self.recipes:
            with self.subTest(recipe.slug):
                pick = choose_recipe([recipe], History.empty(), TODAY)
                self.assertTrue(render_text(pick, History.empty(), 1))
                self.assertTrue(render_html(pick, History.empty(), 1))


class MailConfigTests(unittest.TestCase):
    BASE = {
        "SMTP_HOST": "smtp.example.com",
        "MAIL_FROM": "kitchen@example.com",
        "MAIL_TO": "cook@example.com, other@example.com",
    }

    def test_from_env(self):
        config = MailConfig.from_env(dict(self.BASE, SMTP_USERNAME="u", SMTP_PASSWORD="p"))
        self.assertEqual(config.port, 587)
        self.assertEqual(config.recipients, ("cook@example.com", "other@example.com"))
        self.assertTrue(config.use_tls)
        self.assertFalse(config.use_ssl)

    def test_port_465_implies_implicit_tls(self):
        config = MailConfig.from_env(dict(self.BASE, SMTP_PORT="465"))
        self.assertTrue(config.use_ssl)
        self.assertFalse(config.use_tls)

    def test_missing_variables_are_named(self):
        with self.assertRaises(MailConfigError) as caught:
            MailConfig.from_env({"SMTP_HOST": "x"})
        self.assertIn("MAIL_FROM", str(caught.exception))
        self.assertIn("MAIL_TO", str(caught.exception))

    def test_bad_port(self):
        with self.assertRaises(MailConfigError):
            MailConfig.from_env(dict(self.BASE, SMTP_PORT="soon"))

    def test_message_is_multipart_alternative(self):
        config = MailConfig.from_env(dict(self.BASE))
        message = build_message(config, "Subject", "plain body", "<p>html body</p>")
        self.assertEqual(message["Subject"], "Subject")
        self.assertIn("cook@example.com", message["To"])
        types = {part.get_content_type() for part in message.walk()}
        self.assertIn("text/plain", types)
        self.assertIn("text/html", types)


class SendMessageTests(unittest.TestCase):
    """The SMTP conversation, without touching a network."""

    CONFIG = MailConfig(host="smtp.example.com", port=587, username="u", password="p",
                        sender="kitchen@example.com", recipients=("cook@example.com",))

    def _fake_server(self):
        server = mock.MagicMock()
        server.__enter__.return_value = server
        return server

    def test_starttls_flow(self):
        server = self._fake_server()
        message = build_message(self.CONFIG, "s", "t", "<p>h</p>")
        with mock.patch("recipe_club.mailer.smtplib.SMTP", return_value=server) as smtp:
            send_message(self.CONFIG, message)
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=30)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("u", "p")
        server.send_message.assert_called_once()

    def test_implicit_tls_flow_skips_starttls(self):
        config = MailConfig(host="h", port=465, username=None, password=None,
                            sender="a@b.c", recipients=("d@e.f",), use_ssl=True, use_tls=False)
        server = self._fake_server()
        message = build_message(config, "s", "t", "<p>h</p>")
        with mock.patch("recipe_club.mailer.smtplib.SMTP_SSL", return_value=server):
            send_message(config, message)
        server.starttls.assert_not_called()
        server.login.assert_not_called()
        server.send_message.assert_called_once()


class CliTests(unittest.TestCase):
    def run_cli(self, *args, history=None):
        argv = ["--recipes", str(ROOT / "recipes")]
        argv += ["--history", str(history or Path(self.tmp) / "history.json")]
        argv += list(args)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_list(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("Soft Herb Omelette", out)
        self.assertIn("cooked", out)

    def test_show(self):
        code, out, _ = self.run_cli("show", "01-soft-herb-omelette")
        self.assertEqual(code, 0)
        self.assertIn("Soft Herb Omelette", out)

    def test_show_unknown_slug(self):
        code, _, err = self.run_cli("show", "nope")
        self.assertEqual(code, 1)
        self.assertIn("no recipe", err)

    def test_list_can_filter_by_track(self):
        code, out, _ = self.run_cli("list", "--track", "dumplings")
        self.assertEqual(code, 0)
        self.assertIn("on the dumplings track", out)
        self.assertNotIn("Croissants", out)

    def test_unknown_track_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.run_cli("list", "--track", "baking")

    def test_send_can_be_forced_to_a_track(self):
        code, out, _ = self.run_cli("send", "--dry-run", "--track", "pastry")
        self.assertEqual(code, 0)
        self.assertIn("Week 1", out)

    def test_plan_projects_without_recording(self):
        path = Path(self.tmp) / "history.json"
        code, out, _ = self.run_cli("plan", "6", "--date", "2026-09-01", history=path)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("2026-"), 6)
        self.assertIn("2026-09-04", out)  # projected onto Fridays
        self.assertFalse(path.exists())

    def test_plan_defaults_to_twelve_weeks(self):
        code, out, _ = self.run_cli("plan")
        self.assertEqual(code, 0)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.strip().startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9"))]), 12)

    def test_stats_shows_track_coverage(self):
        code, out, _ = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Tracks", out)
        self.assertIn("untried", out)

    def test_stats_and_validate(self):
        code, out, _ = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Level", out)
        code, out, _ = self.run_cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("parsed cleanly", out)

    def test_dry_run_prints_and_does_not_write_history(self):
        path = Path(self.tmp) / "history.json"
        code, out, err = self.run_cli("send", "--dry-run", "--date", "2026-09-04")
        self.assertEqual(code, 0)
        self.assertIn("Week 1", out)
        self.assertIn("[dry run]", err)
        self.assertFalse(path.exists())

    def test_dry_run_can_write_html(self):
        target = Path(self.tmp) / "out" / "preview.html"
        code, _, _ = self.run_cli("send", "--dry-run", "--html-out", str(target))
        self.assertEqual(code, 0)
        self.assertIn("<!doctype html>", target.read_text())

    def test_forced_slug(self):
        code, out, _ = self.run_cli("send", "--dry-run", "--slug", "69-croissants")
        self.assertEqual(code, 0)
        self.assertIn("Croissants", out)

    def test_missing_mail_config_fails_cleanly(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code, _, err = self.run_cli("send", "--date", "2026-09-04")
        self.assertEqual(code, 2)
        self.assertIn("missing environment variable", err)
        self.assertIn("--no-email", err)

    def test_no_email_delivers_without_smtp(self):
        path = Path(self.tmp) / "history.json"
        body = Path(self.tmp) / "out" / "body.md"
        subject = Path(self.tmp) / "out" / "subject.txt"
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("recipe_club.cli.send_message") as sender:
            code, out, _ = self.run_cli("send", "--no-email", "--date", "2026-09-04",
                                        "--markdown-out", str(body),
                                        "--subject-out", str(subject), history=path)
        self.assertEqual(code, 0)
        sender.assert_not_called()
        self.assertIn("no email sent", out)
        # the recipe is still delivered as files, and still logged
        self.assertIn("Week 1", subject.read_text())
        self.assertIn("**Week 1", body.read_text())
        self.assertEqual(History.load(path).count, 1)

    def test_no_email_still_respects_no_record(self):
        path = Path(self.tmp) / "history.json"
        with mock.patch.dict("os.environ", {}, clear=True):
            code, _, _ = self.run_cli("send", "--no-email", "--no-record", history=path)
        self.assertEqual(code, 0)
        self.assertFalse(path.exists())

    def test_bad_recipe_directory(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--recipes", str(Path(self.tmp) / "none"), "list"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err.getvalue())

    def test_real_send_records_history(self):
        path = Path(self.tmp) / "history.json"
        env = {"SMTP_HOST": "h", "MAIL_FROM": "a@b.c", "MAIL_TO": "d@e.f"}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch("recipe_club.cli.send_message") as sender:
            code, out, _ = self.run_cli("send", "--date", "2026-09-04", history=path)
        self.assertEqual(code, 0)
        sender.assert_called_once()
        self.assertIn("sent", out)
        logged = History.load(path)
        self.assertEqual(logged.count, 1)
        self.assertEqual(logged.last.date, "2026-09-04")

    def test_no_record_leaves_the_log_alone(self):
        path = Path(self.tmp) / "history.json"
        env = {"SMTP_HOST": "h", "MAIL_FROM": "a@b.c", "MAIL_TO": "d@e.f"}
        with mock.patch.dict("os.environ", env, clear=True), \
                mock.patch("recipe_club.cli.send_message"):
            code, _, _ = self.run_cli("send", "--no-record", history=path)
        self.assertEqual(code, 0)
        self.assertFalse(path.exists())

    def test_send_is_the_default_command(self):
        code, out, _ = self.run_cli("--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Week 1", out)

    def test_inject_default_command(self):
        self.assertEqual(cli.inject_default_command(["--dry-run"]), ["send", "--dry-run"])
        self.assertEqual(cli.inject_default_command(["list"]), ["list"])
        self.assertEqual(cli.inject_default_command(["--recipes", "x", "stats"]),
                         ["--recipes", "x", "stats"])
        # a value that happens to look like a command is not mistaken for one
        self.assertEqual(cli.inject_default_command(["--slug", "list"]),
                         ["send", "--slug", "list"])


if __name__ == "__main__":
    unittest.main()
