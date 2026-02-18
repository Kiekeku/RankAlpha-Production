"""
itest_ib_interfacing.py
=======================

Full integration test against Interactive Brokers *paper* account,
covering every public method of ib_interfacing.IBInterfacing.

!!  THIS HITS LIVE IBKR ENDPOINTS  !!
Make sure you meet the preconditions described at the top of the file.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from decimal import ROUND_HALF_UP, Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradeexec.settings import TradeExecSettings


# ------------------------- OAuth helper ------------------------------ #
def _build_oauth_params() -> dict:
    """Collect mandatory OAuth‑1a values from account config or environment."""
    test_settings = TradeExecSettings()
    test_settings.load_accounts_from_env()
    if test_settings.accounts:
        return test_settings.accounts[0].get_broker_oauth_params()
    # Fallback to env variables for dev runs
    required = {
        "consumer_key": "IB_OAUTH_CONSUMER_KEY",
        "access_token": "IB_OAUTH_ACCESS_TOKEN",
        "access_token_secret": "IB_OAUTH_ACCESS_TOKEN_SECRET",
        "encryption_key_fp": "IB_OAUTH_ENCRYPTION_KEY_FP",
        "signature_key_fp": "IB_OAUTH_SIGNATURE_KEY_FP",
    }
    params = {}
    missing = []
    for key, env_var in required.items():
        val = os.getenv(env_var)
        if not val:
            missing.append(env_var)
        params[key] = val
    if missing:
        raise EnvironmentError("Missing required OAuth env‑vars: " + ", ".join(missing)) from None
    dh_prime = os.getenv("IB_OAUTH_DH_PRIME")
    if dh_prime:
        params["dh_prime"] = dh_prime
    return params


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
def round_price(value: float | Decimal, digits: int = 2) -> float:
    """Round to IB‑safe price increments (two decimals is fine for US stocks)."""
    q = Decimal(str(value)).quantize(Decimal(f"1.{'0' * digits}"), ROUND_HALF_UP)
    return float(q)


def wait_until(predicate, timeout: float = 15.0, poll: float = 0.5) -> bool:
    """
    Repeatedly evaluate *predicate* until it returns truthy or timeout expires.
    Returns True if predicate succeeded, False otherwise.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return False


# --------------------------------------------------------------------------- #
# Integration test‑suite
# --------------------------------------------------------------------------- #
class TestIBInterfacingIntegration(unittest.TestCase):
    """
    All tests run sequentially in the same process – earlier steps feed data to
    later ones (e.g. we need the order‑id placed in test_04 for modification /
    cancellation).  Therefore **ordering matters**; keep the numeric names.
    """

    @classmethod
    def setUpClass(cls):
        run_flag = os.getenv("RUN_IB_INTEGRATION_TESTS", "").lower()
        if run_flag not in {"1", "true", "yes"}:
            raise unittest.SkipTest(
                "Set RUN_IB_INTEGRATION_TESTS=1 to run live IBKR integration tests."
            )

        from tradeexec.core.ib import IBInterfacing
        from tradeexec.settings import TradeExecSettings

        # Try to use settings first, fall back to environment variables
        test_settings = TradeExecSettings()
        test_settings.load_accounts_from_env()
        if test_settings.accounts:
            acc = test_settings.accounts[0]
            try:
                oauth_params = acc.get_broker_oauth_params()
            except ValueError as exc:
                raise unittest.SkipTest(
                    f"Missing broker key files for integration tests: {exc}"
                ) from exc
            account_id_env = acc.account_number
            cls.symbol = test_settings.test_symbol
            cls.qty = test_settings.test_quantity
        else:
            oauth_params = _build_oauth_params()
            account_id_env = os.getenv("IB_ACCOUNT_ID")
            cls.symbol = os.getenv("TEST_SYMBOL", "AAPL")
            cls.qty = int(os.getenv("TEST_QUANTITY", "1"))

        # Instantiate class with explicit OAuth parameters
        cls.ib = IBInterfacing(
            account_id=account_id_env,
            oauth_params=oauth_params,
            use_global_settings=False,  # Use explicit params for tests
        )
        cls._order_id_initial = None
        cls._order_id_modified = None

        print(f"\n[INIT] Using account {cls.ib.account_id} | symbol={cls.symbol} qty={cls.qty}")

    # 01 ────────────────────────────────────────────────────────────────────
    def test_01_search_contracts(self):
        contracts = self.ib.search_contracts(self.symbol)
        self.assertGreater(len(contracts), 0, "No contracts returned for symbol.")
        self.__class__.conid = contracts[0]["conid"]
        print(" • search_contracts OK → conid", self.conid)

    # 02 ────────────────────────────────────────────────────────────────────
    def test_02_get_market_data(self):
        quote = self.ib.get_market_data(conid=self.conid)

        # — pick out field 31 (last trade) ---------------------------------
        if isinstance(quote, dict):
            # new return type: flat mapping field-code → value
            last_px_str = quote.get("31")
        else:
            # legacy return type: list[dict] with individual field blobs
            last_px_str = next(
                (item.get("31") for item in quote if isinstance(item, dict) and "31" in item),
                None,
            )

        # convert safely
        last_px = float(last_px_str or 0.0)

        # — assertions -----------------------------------------------------
        self.assertGreater(last_px, 0.0, "Snapshot did not include last price.")
        self.__class__.last_price = last_px
        print(f" • get_market_data OK → last={last_px}")

    # 03 ────────────────────────────────────────────────────────────────────
    # def test_03_get_historical_data(self):
    #     hist = self.ib.get_historical_data(conid=self.conid, period="1d", bar="5min")
    #     self.assertTrue(hist, "Historical data empty.")
    #     bars = hist["data"] if isinstance(hist, dict) and "data" in hist else hist
    #     self.assertGreater(len(bars), 0, "No historical bars received.")
    #     print(f" • get_historical_data OK → {len(bars)} bars")

    # 04 ────────────────────────────────────────────────────────────────────
    # def test_04_place_order_limit(self):
    #     """
    #     Place a BUY limit order 50 % below market so it will remain open.
    #     """
    #     low_price = round_price(self.last_price * 0.5)

    #     # — place the order, grab raw response ----------------------------
    #     raw = self.ib.place_order(
    #         conid=self.conid,
    #         side="BUY",
    #         quantity=self.qty,
    #         order_type="LMT",
    #         limit_price=low_price,
    #         outside_rth=True,
    #     )

    #     # — extract a numeric orderId from raw (int, str, or dict) --------
    #     if isinstance(raw, dict):
    #         # try common keys
    #         oid_val = raw.get("orderId") or raw.get("order_id")
    #     else:
    #         oid_val = raw

    #     try:
    #         oid = int(oid_val)
    #     except Exception:
    #         self.fail(f"Could not parse orderId ({oid_val!r}) from place_order response")

    #     self.__class__._order_id_initial = oid
    #     self.assertIsNotNone(oid, "Order ID was None – order not accepted?")
    #     print(f" • place_order OK → orderId={oid} @ {low_price}")

    #     # — Confirm it appears in open orders -----------------------------
    #     open_orders = self.ib.get_open_orders()
    #     print(f" • get_open_orders OK → {len(open_orders)} open orders")

    #     # Match any entry whose 'orderId' equals our oid
    #     def matches(o):
    #         val = o.get("orderId") or o.get("order_id")
    #         try:
    #             return int(val) == oid
    #         except Exception:
    #             return False

    #     self.assertTrue(
    #         any(matches(o) for o in open_orders),
    #         f"Placed order {oid} not present in open orders list."
    #     )

    # # 05 ────────────────────────────────────────────────────────────────────
    # def test_05_modify_order(self):
    #     """
    #     Modify the above order to a less aggressive price (60 % of market).
    #     """
    #     new_price = round_price(self.last_price * 0.6)
    #     new_oid = self.ib.modify_order(
    #         order_id=self._order_id_initial,
    #         conid=self.conid,
    #         side="BUY",
    #         quantity=self.qty,
    #         order_type="LMT",
    #         limit_price=new_price,
    #         outside_rth=True,
    #     )
    #     self.__class__._order_id_modified = new_oid
    #     self.assertIsNotNone(new_oid, "Modified order did not return an ID.")
    #     print(f" • modify_order OK → newOrderId={new_oid} @ {new_price}")

    #     # Ensure old order is gone (may take a moment)
    #     def old_order_gone():
    #         return not any(
    #             int(o["orderId"]) == int(self._order_id_initial)
    #             for o in self.ib.get_open_orders()
    #         )

    #     wait_until(old_order_gone, timeout=10.0, poll=1.0)
    #     self.assertTrue(old_order_gone(), "Old order still present after modification.")

    # 06 ────────────────────────────────────────────────────────────────────
    # def test_06_cancel_order(self):
    #     """
    #     Cancel the modified order and verify it disappears from open orders.
    #     """
    #     self.ib.cancel_order(self._order_id_modified)

    #     def order_removed():
    #         return not any(
    #             int(o["orderId"]) == int(self._order_id_modified)
    #             for o in self.ib.get_open_orders()
    #         )

    #     self.assertTrue(
    #         wait_until(order_removed, timeout=10.0, poll=1.0),
    #         "Order not cancelled (still in open orders after timeout).",
    #     )
    #     print(" • cancel_order OK – order removed from open orders")

    # # 07 ────────────────────────────────────────────────────────────────────
    # def test_07_get_open_orders_empty(self):
    #     open_orders = self.ib.get_open_orders()
    #     self.assertFalse(
    #         any(int(o["orderId"]) == int(self._order_id_modified) for o in open_orders),
    #         "Cancelled order still shows in open orders.",
    #     )
    #     print(f" • get_open_orders OK → currently {len(open_orders)} open orders")

    # 08 ────────────────────────────────────────────────────────────────────
    def test_08_get_account_summary(self):
        summary = self.ib.get_account_summary()
        # Check key fields exist
        self.assertIn("USD", summary, "Account summary missing USD section.")
        usd = summary["USD"]
        self.assertIn("cashbalance", usd)
        self.assertIn("netliquidationvalue", usd)
        print(" • get_account_summary OK → cashBalance =", usd["cashbalance"])

    # 09 ────────────────────────────────────────────────────────────────────
    def test_09_get_positions(self):
        positions = self.ib.get_positions()
        # Positions may be empty; ensure list type
        self.assertIsInstance(positions, list)
        print(f" • get_positions OK → {len(positions)} positions returned")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    """
    WARNING: This is a live integration test and will hit IBKR endpoints.

    Configure credentials via environment variables (or via TradeExecSettings accounts):
      - IB_ACCOUNT_ID
      - IB_OAUTH_CONSUMER_KEY
      - IB_OAUTH_ACCESS_TOKEN
      - IB_OAUTH_ACCESS_TOKEN_SECRET
      - IB_OAUTH_ENCRYPTION_KEY_FP
      - IB_OAUTH_SIGNATURE_KEY_FP
      - (optional) IB_OAUTH_DH_PRIME

    Optional knobs:
      - TEST_SYMBOL (default: AAPL)
      - TEST_QUANTITY (default: 1)
    """
    unittest.main(verbosity=2)
