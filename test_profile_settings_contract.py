from pathlib import Path


ROOT = Path(__file__).resolve().parent
INDEX = (ROOT / "index_v2.html").read_text(encoding="utf-8")
SW = (ROOT / "sw.js").read_text(encoding="utf-8")


def test_profile_settings_visible_contract():
    required = (
        'id="profile-settings"',
        'id="p-cefr"',
        'id="p-tariff"',
        'id="p-billing-term"',
        'id="p-plan-expiry"',
        'id="p-timezone"',
        'id="p-session-duration"',
        "renderProfileSettings(D,H)",
        "boundedProfileString",
        "boundedProfileNumber",
        "profileTimezone",
        "Object.prototype.hasOwnProperty.call",
        "Number.isFinite(value)&&value>=min&&value<=max",
        "new Date(Date.UTC(year,month-1,day))",
        "canonical.getUTCFullYear()!==year",
        "(?:Z|[+-](?:[01]\\d|2[0-3]):[0-5]\\d))?$",
    )
    missing = [marker for marker in required if marker not in INDEX]
    assert not missing, f"profile settings contract is incomplete: {missing}"


def test_profile_actions_use_supported_safe_flows():
    required = (
        'id="profile-report-bug"',
        'id="profile-video-guide"',
        "PROFILE_SUPPORT_BOT_URL='https://t.me/SpeakChain_bot'",
        "safeProfileHttpsUrl",
        "telegramOnly:true",
        "guideButton.disabled=!guide",
    )
    missing = [marker for marker in required if marker not in INDEX]
    assert not missing, f"profile action safety markers are missing: {missing}"

    unsupported_writes = (
        'action:"set_timezone"',
        'action:"set_session_minutes"',
        'action:"update_profile_settings"',
        'action:"create_support_ticket"',
    )
    invented = [marker for marker in unsupported_writes if marker in INDEX]
    assert not invented, f"unsupported backend writes were introduced: {invented}"

    unsafe_aliases = (
        "['current_plan','plan']",
        "'plan_expires_at'",
        "'subscription_expires_at'",
        "'expires_at'",
        "'session_duration_minutes'",
        "'instruction_video_url'",
        "'video_guide_url'",
    )
    leaked = [marker for marker in unsafe_aliases if marker in INDEX]
    assert not leaked, f"cross-payload/generic aliases remain in profile rendering: {leaked}"

    unsafe_expiry_fallbacks = (
        "return String(value)",
        "new Intl.DateTimeFormat",
    )
    leaked = [marker for marker in unsafe_expiry_fallbacks if marker in INDEX]
    assert not leaked, f"timezone-sensitive/raw expiry fallback remains: {leaked}"


def test_profile_mutations_match_the_authenticated_bounded_backend_contract():
    required = (
        'id="profile-settings-form"',
        'id="profile-utc-offset"',
        'id="profile-notification-pref"',
        'id="profile-settings-status" role="status" aria-live="polite"',
        "PROFILE_NOTIFICATION_PREFS=new Set(['evening','on_request','off'])",
        "offset< -12||offset>14",
        "action:'profile_settings_update'",
        "settings:request.patch",
        "mutation_id:request.mutationId",
        "expected_revision:request.expectedRevision",
        "init_data:initData",
        "pwa_access_token:token",
        "payload.settings[key]===value",
        "saved.profile_settings_revision===revision",
        "PROFILE_SETTINGS_SAVE_TIMEOUT_MS=8000",
        "new AbortController()",
        "signal:controller.signal",
        "generation!==PROFILE_SETTINGS_STATE.generation",
        "if(PROFILE_SETTINGS_STATE.saving)return",
        "save.textContent='Перевірити й повторити'",
        "PROFILE_SETTINGS_STATE.retryRequest=request",
        "applyAuthoritativeProfileSettings(payload.settings)",
    )
    missing = [marker for marker in required if marker not in INDEX]
    assert not missing, f"profile mutation contract is incomplete: {missing}"

    start = INDEX.index("async function saveProfileSettings(")
    end = INDEX.index("function renderProfileSettings(", start)
    mutation = INDEX[start:end]
    assert "uid:" not in mutation and "uid=" not in mutation, "profile mutation must not send body uid"
    body_start = mutation.index("body:JSON.stringify(")
    body_end = mutation.index("signal:controller.signal", body_start)
    request_body = mutation[body_start:body_end]
    for unsupported in ("session_minutes", "profile_video_url", "level", "timezone"):
        assert unsupported not in request_body, f"unsupported profile mutation leaked: {unsupported}"


def test_profile_release_bumps_public_shell_cache():
    assert "speakchain-shell-v29" in SW


if __name__ == "__main__":
    test_profile_settings_visible_contract()
    test_profile_actions_use_supported_safe_flows()
    test_profile_mutations_match_the_authenticated_bounded_backend_contract()
    test_profile_release_bumps_public_shell_cache()
    print("profile settings contract: OK")
