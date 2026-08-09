from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent


def test_account_linking_is_double_gated_and_shell_cached():
    module = (ROOT / "account_linking.js").read_text(encoding="utf-8")
    index = (ROOT / "index_v2.html").read_text(encoding="utf-8")
    worker = (ROOT / "sw.js").read_text(encoding="utf-8")
    assert "window.SC_ACCOUNT_LINKING_BUILD_ENABLED === true" in module
    assert "config?.account_linking_enabled !== true" in module
    assert '<div id="account-linking-slot" hidden></div>' in index
    assert "./account_linking.js" in worker
    assert "speakchain-shell-v29" in worker


def test_account_linking_uses_bearer_contract_without_raw_uid():
    pwa = (ROOT / "pwa.js").read_text(encoding="utf-8")
    module = (ROOT / "account_linking.js").read_text(encoding="utf-8")
    assert "'Authorization': 'Bearer ' + accessToken" in pwa
    assert "ACCOUNT_LINK_PATHS.has(path)" in pwa
    assert "'/api/v1/account-link/intents'" in module
    assert "'/api/v1/account-link/complete'" in module
    assert "target_provider: state.target, consent: true" in module
    assert not re.search(r"\buid\s*:", module)
    assert "pwa_access_token" not in module


def test_account_linking_never_persists_or_logs_intent_tokens():
    module = (ROOT / "account_linking.js").read_text(encoding="utf-8")
    assert "localStorage" not in module
    assert "sessionStorage" not in module
    assert "console." not in module
    assert "textContent" in module
    assert "clearIntent();" in module


def test_account_linking_covers_terminal_safety_outcomes():
    module = (ROOT / "account_linking.js").read_text(encoding="utf-8")
    for code in (
        "intent_expired", "cross_user_rejected", "target_identity_mismatch",
        "identity_conflict", "already_linked", "profile_too_large",
        "persistence_unavailable",
    ):
        assert code in module
    assert "state.completed = true" in module
    assert "result?.ok" in module
