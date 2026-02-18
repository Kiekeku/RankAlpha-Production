"""
Python translation of the C# DailyReport class from the IBBrokerExecution project.

This module defines a DailyReport class that gathers position, order and account
information from Interactive Brokers via the IBInterfacing wrapper, computes
basic technical indicators (EMAs and a SMA) for each open position using
yfinance, and composes a rich HTML summary.  The report is then delivered
via email through the GmailSMTP utility and may optionally be forwarded to
a Telegram chat via the TelegramCommunicator class.

The goal of this translation is not to reproduce every database join found in
IBBrokerExecution.DailyReport.cs, but rather to illustrate how the same high‑
level behaviour can be achieved in Python using the existing ibkrwebapi
components.  Developers are encouraged to adapt and extend this class to
match their own data models and reporting requirements.
"""

import datetime
from typing import Any, Dict, List, Optional, Tuple

import yfinance as yf
from tradeexec.comms.telegram import TelegramCommunicator

# Local imports from the ibkrwebapi project
from tradeexec.core.ib import IBInterfacing

from apps.broker.utils.GmailSMTP import GmailSMTP


class DailyReport:
    """Generate and send a daily trading report.

    Parameters
    ----------
    ib_interface : IBInterfacing
        An authenticated instance used to query positions, orders and account
        information from Interactive Brokers.
    telegram_bot : TelegramCommunicator, optional
        An optional telegram communicator used to send a copy of the report
        via Telegram.  If ``None``, Telegram delivery is skipped.
    """

    def __init__(
        self, ib_interface: IBInterfacing, telegram_bot: Optional[TelegramCommunicator] = None
    ) -> None:
        self.ib = ib_interface
        self.telegram = telegram_bot

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _compute_indicators(
        self, symbol: str
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Compute simple moving average and exponential moving averages.

        Pull the last 220 daily closing prices for ``symbol`` using yfinance
        and compute:

        - 200‑period SMA
        - 50‑period EMA
        - 21‑period EMA
        - 8‑period EMA

        Returns ``(ema8, ema21, ema50, sma200)`` with ``None`` for any
        indicator that could not be calculated (e.g. insufficient data).
        """
        try:
            # Download ~220 days of daily data (enough for 200‑period SMA)
            data = yf.download(symbol, period="220d", interval="1d", progress=False)
            closes = data["Close"].dropna()
            if closes.empty:
                return (None, None, None, None)

            # Exponential moving averages - use .item() to get scalar values
            ema8 = (
                closes.ewm(span=8, adjust=False).mean().iloc[-1].item()
                if len(closes) >= 8
                else None
            )
            ema21 = (
                closes.ewm(span=21, adjust=False).mean().iloc[-1].item()
                if len(closes) >= 21
                else None
            )
            ema50 = (
                closes.ewm(span=50, adjust=False).mean().iloc[-1].item()
                if len(closes) >= 50
                else None
            )
            # Simple moving average
            sma200 = (
                closes.rolling(window=200).mean().iloc[-1].item() if len(closes) >= 200 else None
            )
            return (ema8, ema21, ema50, sma200)
        except Exception:
            # Silence any network or data issues
            return (None, None, None, None)

    def _get_last_price(
        self, symbol: str, sec_type: str = "STK", exchange: Optional[str] = None
    ) -> Optional[float]:
        """Retrieve the last traded price for ``symbol`` using IBInterfacing.

        IB's market data snapshot returns a mapping of field codes to values.
        The field code ``31`` corresponds to the last trade price.  Returns
        ``None`` on failure.
        """
        try:
            quote = self.ib.get_market_data(symbol=symbol, sec_type=sec_type, exchange=exchange)
            if isinstance(quote, dict):
                # Newer ibind versions return a flat dict of field codes
                last_px = quote.get("31")
                return float(last_px) if last_px is not None else None
            # For older versions (list of dicts), find first item with field 31
            if isinstance(quote, list):
                for item in quote:
                    if isinstance(item, dict) and "31" in item:
                        return float(item["31"])
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def record_current_holdings(self) -> List[Dict[str, Any]]:
        """Return a snapshot of the current holdings.

        In the original C# implementation, this method truncates and
        repopulates a SQL table.  In Python we simply return the current
        positions as a list of dictionaries so the caller can decide how to
        persist or display them.  Each position dictionary is as returned
        by ``IBInterfacing.get_positions``.
        """
        positions: List[Dict[str, Any]] = self.ib.get_positions()
        return positions

    def email_report(self) -> None:
        """Generate a daily report and send it via Gmail and optionally Telegram.

        Gathers the current positions, account summary, and any open orders
        from IB.  For each position, the function computes basic technical
        indicators and calculates the unrealised PnL.  The results are
        assembled into a simple HTML email and dispatched through Gmail.
        If a ``TelegramCommunicator`` is configured, a plain‑text version of
        the report is also sent via Telegram.
        """
        # Fetch IB data
        positions = self.ib.get_positions()
        account_summary = self.ib.get_account_summary()
        open_orders = self.ib.get_open_orders()

        # Start building the HTML report
        today_str = datetime.date.today().strftime("%Y‑%m‑%d")
        html_parts: List[str] = []
        html_parts.append("<html><body>")
        html_parts.append(f"<h2>Daily Report – {today_str}</h2>")

        # Current positions table
        html_parts.append("<h3>Current Positions</h3>")
        html_parts.append(
            "<table style='width:100%; border-collapse:collapse;'>"
            "<tr>"
            "<th style='border:1px solid #ddd; padding:8px;'>Symbol</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>Quantity</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>Avg Cost</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>Last Price</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>PnL</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>8 EMA</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>21 EMA</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>50 EMA</th>"
            "<th style='border:1px solid #ddd; padding:8px;'>200 SMA</th>"
            "</tr>"
        )
        for pos in positions:
            # Derive symbol and size fields; different IB API versions return different keys
            symbol = pos.get("ticker") or pos.get("symbol")

            # If no symbol found, try to resolve from contract ID
            if not symbol:
                conid = pos.get("conid")
                if conid:
                    try:
                        symbol = self.ib.get_symbol_from_contract_id(str(conid))
                        if not symbol:
                            symbol = str(conid)  # fallback to conid string
                    except Exception as e:
                        print(f"Failed to resolve symbol for contract ID {conid}: {e}")
                        symbol = str(conid)  # fallback to conid string
                else:
                    symbol = "UNKNOWN"
            qty = pos.get("position") or pos.get("pos") or pos.get("quantity") or 0
            avg_cost = pos.get("averageCost") or pos.get("avgCost") or pos.get("costBasis") or 0.0
            # Attempt to extract exchange and security type for market data
            exchange = pos.get("exchange") or pos.get("exchangeCode")
            sec_type = pos.get("assetClass") or pos.get("asset_class") or "STK"
            # Retrieve current price
            last_price = self._get_last_price(
                str(symbol), sec_type=str(sec_type), exchange=exchange
            )
            # Compute PnL
            pnl = None
            if avg_cost and last_price:
                try:
                    pnl = (last_price - avg_cost) / float(avg_cost)
                except Exception:
                    pnl = None
            # Compute indicators
            ema8, ema21, ema50, sma200 = self._compute_indicators(str(symbol))

            # Format row
            def fmt(v: Optional[float], pct: bool = False) -> str:
                if v is None:
                    return "N/A"
                return f"{v:.2%}" if pct else f"{v:.2f}"

            html_parts.append(
                "<tr>"
                f"<td style='border:1px solid #ddd; padding:8px;'>{symbol}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{qty}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(avg_cost, False)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(last_price, False)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(pnl, True)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(ema8, False)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(ema21, False)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(ema50, False)}</td>"
                f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{fmt(sma200, False)}</td>"
                "</tr>"
            )
        html_parts.append("</table>")

        # Account summary section
        html_parts.append("<h3>Account Summary</h3>")
        if isinstance(account_summary, dict):
            html_parts.append(
                "<table style='width:100%; border-collapse:collapse;'>"
                "<tr>"
                "<th style='border:1px solid #ddd; padding:8px; text-align:left;'>Measurement</th>"
                "<th style='border:1px solid #ddd; padding:8px; text-align:right;'>Value</th>"
                "</tr>"
            )

            # Extract ledger data - it could be in different currencies
            ledger_data = {}
            base_currency = "USD"

            # Parse the account summary to extract ledger information
            for _key, value in account_summary.items():
                if isinstance(value, dict) and "currency" in value:
                    # This is ledger data for a specific currency
                    currency = value.get("currency", "USD")
                    ledger_data[currency] = value
                    # Set base currency based on the account's primary currency
                    if value.get("cashbalance", 0) != 0 or value.get("netliquidationvalue", 0) != 0:
                        base_currency = currency

            # If no parsed ledger data, try to use the raw data
            if not ledger_data and any(isinstance(v, dict) for v in account_summary.values()):
                # Try to find the first dictionary value as ledger data
                for _k, v in account_summary.items():
                    if isinstance(v, dict):
                        currency = v.get("currency", "USD")
                        ledger_data[currency] = v
                        base_currency = currency
                        break

            # Get the base currency ledger data
            base_ledger = ledger_data.get(base_currency, {})

            # Define the fields to display with their labels
            fields_to_display = [
                ("netliquidationvalue", "Net Liquidation"),
                ("cashbalance", "Total Cash Value"),
                ("funds", "Available Funds"),
                ("fullavailablefunds", "Full Available Funds"),
                ("excessliquidity", "Excess Liquidity"),
                ("buyingpower", "Buying Power"),
                ("exchangerate", "Exchange Rate"),
                ("grosspositionvalue", "Gross Position Value"),
                ("unrealizedpnl", "Unrealized PnL"),
                ("stockmarketvalue", "Stock Market Value"),
                ("cashbalancefxsegment", "FX Cash Balance"),
                ("tbillsmarketvalue", "TBill Market Value"),
                ("tbondsmarketvalue", "TBond Market Value"),
            ]

            # Format and display the fields
            for field_key, label in fields_to_display:
                value = base_ledger.get(field_key)
                if value is not None:
                    # Format currency values
                    if field_key in [
                        "netliquidationvalue",
                        "cashbalance",
                        "funds",
                        "fullavailablefunds",
                        "excessliquidity",
                        "buyingpower",
                        "grosspositionvalue",
                        "unrealizedpnl",
                        "stockmarketvalue",
                        "cashbalancefxsegment",
                        "tbillsmarketvalue",
                        "tbondsmarketvalue",
                    ]:
                        formatted_value = f"${value:,.2f} {base_currency}"
                    elif field_key == "exchangerate":
                        formatted_value = f"{value:.5f}"
                    else:
                        formatted_value = str(value)

                    html_parts.append(
                        "<tr>"
                        f"<td style='border:1px solid #ddd; padding:8px;'>{label}</td>"
                        f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{formatted_value}</td>"
                        "</tr>"
                    )

            # Also show data for other currencies if available
            for currency, data in ledger_data.items():
                if currency != base_currency and data.get("cashbalance", 0) != 0:
                    html_parts.append(
                        "<tr>"
                        f"<td style='border:1px solid #ddd; padding:8px;'>{currency} Cash Balance</td>"
                        f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>${data.get('cashbalance', 0):,.2f} {currency}</td>"
                        "</tr>"
                    )

            html_parts.append("</table>")
        else:
            html_parts.append("<p>No account summary available.</p>")

        # Open orders section
        html_parts.append("<h3>Open Orders</h3>")
        if open_orders:
            html_parts.append(
                "<table style='width:100%; border-collapse:collapse;'>"
                "<tr>"
                "<th style='border:1px solid #ddd; padding:8px;'>OrderId</th>"
                "<th style='border:1px solid #ddd; padding:8px;'>Symbol</th>"
                "<th style='border:1px solid #ddd; padding:8px;'>Side</th>"
                "<th style='border:1px solid #ddd; padding:8px;'>Qty</th>"
                "<th style='border:1px solid #ddd; padding:8px;'>Type</th>"
                "<th style='border:1px solid #ddd; padding:8px;'>Limit Price</th>"
                "</tr>"
            )
            for order in open_orders:
                order_id = order.get("orderId") or order.get("order_id") or "?"
                sym = order.get("ticker") or order.get("symbol") or order.get("conid")
                side = order.get("side") or order.get("action") or "?"
                qty = order.get("quantity") or order.get("qty") or order.get("orderQty") or "?"
                order_type = (
                    order.get("orderType") or order.get("type") or order.get("order_type") or "?"
                )
                limit_price = order.get("lmtPrice") or order.get("limitPrice") or ""
                html_parts.append(
                    "<tr>"
                    f"<td style='border:1px solid #ddd; padding:8px;'>{order_id}</td>"
                    f"<td style='border:1px solid #ddd; padding:8px;'>{sym}</td>"
                    f"<td style='border:1px solid #ddd; padding:8px; text-align:center;'>{side}</td>"
                    f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{qty}</td>"
                    f"<td style='border:1px solid #ddd; padding:8px;'>{order_type}</td>"
                    f"<td style='border:1px solid #ddd; padding:8px; text-align:right;'>{limit_price}</td>"
                    "</tr>"
                )
            html_parts.append("</table>")
        else:
            html_parts.append("<p>No open orders.</p>")

        html_parts.append("<p>End of report.</p>")
        html_parts.append("</body></html>")
        html_body = "".join(html_parts)

        # Send via Gmail
        subject = f"Daily Report for {self.ib.account_id} – {today_str}"
        try:
            GmailSMTP.sendEmail(subject, html_body)
        except Exception as e:
            # Fail silently but log to stdout so tests can notice
            print(f"Failed to send email: {e}")

        # Optionally send to Telegram as plain text (strip HTML tags)
        if self.telegram:
            # Very simple tag stripping; for production use BeautifulSoup or similar
            import re

            plain_text = re.sub("<[^>]+>", "", html_body)
            try:
                self.telegram.send_text(plain_text)
            except Exception as e:
                print(f"Failed to send Telegram message: {e}")


# Example usage (uncomment to run as a script):
if __name__ == "__main__":
    from tradeexec.settings import settings  # load accounts from broker.env

    # Use the first configured account for a quick ad‑hoc report
    if not settings.accounts:
        print("No accounts configured in broker.env; cannot run daily report.")
    else:
        acc = settings.accounts[0]
        ib = IBInterfacing(
            account_id=acc.account_number,
            oauth_params=acc.get_broker_oauth_params(),
            use_global_settings=False,
        )
        telegram = None
        report = DailyReport(ib_interface=ib, telegram_bot=telegram)
        report.email_report()
