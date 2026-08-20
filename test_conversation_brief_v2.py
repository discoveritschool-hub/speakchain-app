from pathlib import Path


ROOT = Path(__file__).parent
BUDDY = (ROOT / "speaking_buddy.html").read_text(encoding="utf-8")
SW = (ROOT / "sw.js").read_text(encoding="utf-8")


def test_my_situation_is_one_bounded_accessible_field():
    assert 'id="ms-situation"' in BUDDY
    assert 'maxlength="600"' in BUDDY
    assert 'role="dialog"' in BUDDY
    assert 'aria-modal="true"' in BUDDY
    assert 'aria-labelledby="ms-title"' in BUDDY
    assert 'aria-live="polite"' in BUDDY
    assert "event.key === 'Escape'" in BUDDY
    assert "mySituationReturnFocus?.focus?.()" in BUDDY
    assert "querySelectorAll('textarea,button:not(:disabled)')" in BUDDY
    assert 'id="ms-who"' not in BUDDY
    assert 'id="ms-what"' not in BUDDY
    assert 'id="ms-focus"' not in BUDDY


def test_v2_payload_and_draft_are_default_compatible():
    assert "mySituation: conversationBriefFromInput({ situation, legacy: mySituationLegacy })" in BUDDY
    assert "speakchain.my-situation.v2" in BUDDY
    assert "localStorage.setItem(MY_SITUATION_DRAFT_KEY" in BUDDY
    assert "JSON.stringify(brief)" in BUDDY
    assert "Conversation partner:" in BUDDY
    assert "my_situation:  currentScenario.mySituation || null" in BUDDY
    assert "my_situation: currentScenario?.mySituation || null" in BUDDY


def test_service_worker_cache_is_unique_after_v34():
    assert "const CACHE = 'speakchain-shell-v35'" in SW
    assert "speakchain-shell-v34" not in SW
