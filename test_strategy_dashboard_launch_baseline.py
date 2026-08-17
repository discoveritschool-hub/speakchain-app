from pathlib import Path


HTML = Path(__file__).with_name("strategy_dashboard.html").read_text(encoding="utf-8")


def test_launch_baseline_has_no_demo_business_numbers():
    assert "implementation-roadmap-v7" in HTML
    assert 'mrr:"$0"' in HTML
    assert 'paid:"0"' in HTML
    assert 'payout:"$0"' in HTML
    assert "$12,400" not in HTML
    assert "● демо-дані" not in HTML


def test_current_offer_contract_is_visible():
    for value in ("$109", "$99", "$475", "$397", "$69", "$388"):
        assert value in HTML
    assert "Живе спілкування з учасниками" in HTML
    assert "День 6" in HTML and "День 7" in HTML
