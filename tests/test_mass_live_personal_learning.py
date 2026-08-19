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

    def test_private_console_controls_a_separate_clean_youtube_screen(self):
        host = (ROOT / "live_host.html").read_text(encoding="utf-8")
        present = (ROOT / "live_present.html").read_text(encoding="utf-8")
        blogger = (ROOT / "blogger.html").read_text(encoding="utf-8")
        for state in ("__plan__", "__routes__", "__questions__"):
            self.assertIn(state, host)
            self.assertIn(state, present)
        self.assertIn("live_present.html", host)
        self.assertIn("host_visible!==false", present)
        self.assertNotIn('id="next"', present)
        self.assertNotIn('id="prev"', present)
        self.assertIn("present_url", blogger)
        self.assertIn("Відкрити пульт блогера", blogger)
        self.assertIn("Відкрити чистий екран YouTube", blogger)

    def test_live_surfaces_are_mobile_safe_and_reconnect_automatically(self):
        learner = (ROOT / "live_activity.html").read_text(encoding="utf-8")
        host = (ROOT / "live_host.html").read_text(encoding="utf-8")
        present = (ROOT / "live_present.html").read_text(encoding="utf-8")
        for source in (learner, host, present):
            self.assertIn('name="referrer" content="no-referrer"', source)
            self.assertIn("visibilitychange", source)
            self.assertIn("Math.min(15000", source)
            self.assertIn("navigator.onLine", source)
        self.assertIn("repeat(2,minmax(0,1fr))", host)
        self.assertIn("main{grid-template-columns:1fr", present)
        self.assertIn("env(safe-area-inset-bottom)", learner)
        self.assertIn("min-height:52px", learner)

    def test_blogger_can_start_and_end_the_session_from_the_private_console(self):
        host = (ROOT / "live_host.html").read_text(encoding="utf-8")
        self.assertIn('id="start"', host)
        self.assertIn('id="end"', host)
        self.assertIn("/host/status", host)
        self.assertIn("Почати ефір", host)
        self.assertIn("Завершити ефір?", host)

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
