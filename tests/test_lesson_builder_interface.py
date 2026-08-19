from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LessonBuilderInterfaceTests(unittest.TestCase):
    def test_builder_exposes_the_review_gated_workflow(self):
        html = (ROOT / "lesson_builder.html").read_text(encoding="utf-8")
        for action in (
            "admin_lesson_generate", "admin_lesson_load", "admin_lesson_validate",
            "admin_lesson_save", "admin_lesson_publish",
        ):
            self.assertIn(action, html)
        for check in ("grammar_accuracy", "distractors", "level_routes", "image_rights"):
            self.assertIn(f'data-review="{check}"', html)
        self.assertIn("speakchain.pwa.access.v1", html)
        self.assertIn("Telegram?.WebApp", html)

    def test_admin_panel_links_to_the_builder(self):
        html = (ROOT / "admin_analytics.html").read_text(encoding="utf-8")
        self.assertIn("lesson_builder.html", html)


if __name__ == "__main__":
    unittest.main()
