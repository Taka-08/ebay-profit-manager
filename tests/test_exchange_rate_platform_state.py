"""Exercise Streamlit widget cleanup without a database or live FX requests."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import streamlit_app as app


RATES = {"USD": 153.554, "CAD": 112.1234, "GBP": 198.5678, "AUD": 101.2345}
PAGE = """
import streamlit as st
import streamlit_app as app
platform = app.render_platform_selector()
if platform == app.PLATFORM_EBAY:
    st.session_state.test_calculation_rates = app.render_exchange_rate()
"""


class ExchangeRatePlatformStateTest(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(app, "SHARED_EXCHANGE_RATE_PATH", Path(directory) / "rates.json"))
        self.fetch = self.stack.enter_context(patch.object(app, "fetch_exchange_rate", side_effect=lambda currency: (
            {"rate": RATES[currency], "raw_jpy": RATES[currency], "source": "test", "api_updated_at": None}, None
        )))

    def page(self, currency):
        page = AppTest.from_string(PAGE)
        page.session_state.exchange_currency = currency
        return page.run(timeout=30)

    def roundtrip(self, page):
        for platform in (app.PLATFORM_MERCARI, app.PLATFORM_IPHONE_RESALE):
            page.radio(key="profit_platform").set_value(platform).run()
            self.assertEqual([], list(page.exception))
            self.assertEqual([], list(page.number_input))
        page.radio(key="profit_platform").set_value(app.PLATFORM_EBAY).run()
        self.assertEqual([], list(page.exception))

    def assert_consistent(self, page, currency, rate):
        self.assertEqual(currency, page.selectbox(key="exchange_currency_input").value)
        self.assertEqual(rate, page.number_input(key="exchange_rate_input").value)
        self.assertEqual(rate, page.session_state.exchange_rate)
        self.assertEqual((currency, rate), page.session_state.test_calculation_rates[:2])
        self.assertEqual(currency, page.session_state.exchange_rate_message["currency_code"])
        self.assertEqual(rate, page.session_state.exchange_rate_message["after"])
        notices = list(page.info) + list(page.success)
        self.assertTrue(any(f"{rate:.4f}" in notice.value for notice in notices))

    def test_api_rate_and_currency_survive_platform_roundtrip(self):
        for currency, rate in RATES.items():
            with self.subTest(currency=currency):
                page = self.page(currency)
                self.roundtrip(page)
                self.assert_consistent(page, currency, rate)

    def test_manual_rate_survives_platform_roundtrip_without_refetch(self):
        for currency, rate in RATES.items():
            with self.subTest(currency=currency):
                page = self.page(currency)
                page.number_input(key="exchange_rate_input").set_value(rate + 1).run()
                calls = self.fetch.call_count
                self.roundtrip(page)
                self.assertEqual(calls, self.fetch.call_count)
                self.assert_consistent(page, currency, rate + 1)

    def test_currency_switch_then_update_and_roundtrip(self):
        page = self.page("USD")
        for currency, rate in RATES.items():
            page.selectbox(key="exchange_currency_input").set_value(currency).run()
            page.number_input(key="exchange_rate_input").set_value(rate + 1).run()
            page.button[0].click().run()
            self.roundtrip(page)
            self.assert_consistent(page, currency, rate)

    def test_failed_update_keeps_rate_input_and_calculation_consistent(self):
        page = self.page("GBP")
        self.fetch.side_effect = RuntimeError("test unavailable")
        page.button[0].click().run()
        self.roundtrip(page)
        self.assertEqual(RATES["GBP"], page.number_input(key="exchange_rate_input").value)
        self.assertEqual(("GBP", RATES["GBP"]), page.session_state.test_calculation_rates[:2])
        self.assertEqual("error", page.session_state.exchange_rate_message["type"])
        self.assertTrue(page.error)
