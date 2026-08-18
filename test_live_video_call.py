from pathlib import Path
import unittest


class LiveVideoCallContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(__file__).with_name("index_v2.html").read_text(encoding="utf-8")

    def test_live_room_has_local_remote_video_and_controls(self):
        for marker in (
            'id="live-remote-video"',
            'id="live-local-video"',
            'id="live-camera-toggle"',
            'id="live-mic-toggle"',
            'id="live-camera-switch"',
        ):
            self.assertIn(marker, self.source)

    def test_video_is_optional_and_joins_existing_webrtc_connection(self):
        self.assertIn('id="live-camera-choice" type="checkbox" checked', self.source)
        self.assertIn("LIVE_PC.addTrack(track,LIVE_LOCAL_STREAM)", self.source)
        self.assertIn("sender.replaceTrack(next)", self.source)
        self.assertIn("video:wantsVideo?{facingMode:'user'", self.source)

    def test_leaving_stops_camera_and_remote_tracks(self):
        self.assertIn("LIVE_LOCAL_STREAM?.getTracks().forEach(t=>t.stop())", self.source)
        self.assertIn("LIVE_REMOTE_STREAM?.getTracks().forEach(t=>t.stop())", self.source)

    def test_room_has_synchronised_zero_ai_facilitator(self):
        for marker in (
            'id="live-room-host"',
            'Chainy веде кімнату',
            "socialApi('live_game_action'",
            "function completeLiveGameStage()",
            "function liveGameReaction(emoji)",
            "renderLiveRoomGame(d.game||null)",
            "viewer_uid='+encodeURIComponent(UID)",
            'id="live-game-answer-text"',
            "function captureLiveGameAnswer()",
            "answer_text:answerText",
            "r.event?.type==='answer_needs_retry'",
        ):
            self.assertIn(marker, self.source)


if __name__ == "__main__":
    unittest.main()
