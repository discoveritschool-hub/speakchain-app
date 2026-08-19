from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class MassLivePersonalLearningSurfaceTests(unittest.TestCase):
    def test_learner_gets_private_route_and_reports_the_full_funnel(self):
        source = (ROOT / "live_activity.html").read_text(encoding="utf-8")
        self.assertIn("learnerRoute", source)
        self.assertIn("function routeBanner()", source)
        self.assertIn("function renderPersonalGrammar()", source)
        self.assertIn("function renderSrsPhase()", source)
        self.assertIn("function renderPhrasePhase()", source)
        self.assertIn("function renderSpeakingPhase()", source)
        for event in (
            "preparation_completed", "grammar_completed", "srs_completed",
            "phrases_completed", "speaking_completed", "video_completed",
        ):
            self.assertIn(event, source)

    def test_host_can_show_all_routes_without_private_vocabulary(self):
        source = (ROOT / "live_host.html").read_text(encoding="utf-8")
        self.assertIn("function renderRoutes()", source)
        self.assertIn("Маршрути рівнів", source)
        self.assertIn("route_distribution", source)
        self.assertIn("personalized_accuracy", source)
        self.assertIn("особиста лексика учнів приховані", source)

    def test_admin_has_mass_live_route_and_stage_analytics(self):
        source = (ROOT / "admin_analytics.html").read_text(encoding="utf-8")
        self.assertIn("Mass Live, Personal Learning", source)
        self.assertIn("route_distribution", source)
        self.assertIn("personalized_clicks", source)
        self.assertIn("preparation_completed", source)
        self.assertIn("speaking_completed", source)
        self.assertIn("video_completed", source)

    def test_browser_blogger_can_create_and_see_invitation_immediately(self):
        source = (ROOT / "blogger.html").read_text(encoding="utf-8")
        self.assertIn("speakchain.pwa.access.v1", source)
        self.assertIn("lastMaActionError", source)
        self.assertIn("lastMaActionData?.session", source)
        self.assertIn("renderLiveSessions();", source)
        self.assertIn("duration_minutes: 60", source)
        self.assertIn("У режимі перегляду створення вимкнене", source)


if __name__ == "__main__":
    unittest.main()
