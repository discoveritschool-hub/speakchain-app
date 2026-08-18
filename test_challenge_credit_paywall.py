from pathlib import Path
import unittest


PAYWALL = Path(__file__).with_name("paywall.html")


class ChallengeCreditPaywallTests(unittest.TestCase):
    def test_credit_keeps_six_month_choice_visible(self):
        source = PAYWALL.read_text(encoding="utf-8")
        self.assertNotIn("if(D.challenge_credit_available) return;", source)
        self.assertIn("Челендж враховано", source)
        self.assertNotIn("str(basic_6m_price)", source)


    def test_basic_and_premium_copy_matches_product_contract(self):
        source = PAYWALL.read_text(encoding="utf-8")
        self.assertIn("Повний репетиторський курс", source)
        self.assertIn("Живе спілкування з іншими учасниками", source)
        self.assertIn("Той самий повний курс", source)
        self.assertIn("8 ефірів щотижня + записи до п’ятниці", source)


    def test_six_month_value_is_expressed_as_effective_monthly_price(self):
        source = PAYWALL.read_text(encoding="utf-8")
        self.assertIn("Вигідніше, ніж платити щомісяця", source)
        self.assertIn("price6m / 6", source)


if __name__ == "__main__":
    unittest.main()
