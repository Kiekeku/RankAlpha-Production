"""
ib.py
=====

Stateless Python wrapper around Interactive Brokers Client‑Portal Web API,
built on top of the **ibind** library.  Re‑implements (almost) every feature
from the original C# `IBInterfacing` class while embracing REST semantics
and OAuth 1.0a authentication.

Highlights
----------
• OAuth handled via `ibind.OAuth1aConfig`  (or environment variables).
• Automatic *keep‑alive* (`/tickle`) before every outbound request.
• Contract search (stocks, futures, FX), snapshot quotes, historical data.
• Place / modify / cancel orders (including bracket orders).
• Open orders, account summary, positions.
• Graceful clean‑up (`logout`) and context‑manager support.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Standard library
# --------------------------------------------------------------------------- #
import hashlib
import logging
import os
import random
import re
import threading
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

# --------------------------------------------------------------------------- #
# Third‑party
# --------------------------------------------------------------------------- #
from ibind import IbkrClient, QuestionType, StockQuery, make_order_request

try:  # Allow tests to stub minimal `ibind` without support package
    from ibind.support.errors import ExternalBrokerError  # type: ignore
except Exception:  # pragma: no cover - test stubs

    class ExternalBrokerError(Exception):
        pass


from ibind.oauth.oauth1a import OAuth1aConfig

from ..metrics import Timer, observe_ibkr_request_seconds, record_ibkr_request_error

# --------------------------------------------------------------------------- #
# Local imports
# --------------------------------------------------------------------------- #
from ..settings import settings
from ..utils.sentry_quiet import is_broker_sentry_quiet_hours
from .rate_limits import (
    _GLOBAL_BURST,
    _GLOBAL_RPS,
    _HISTORY_MAX_CONCURRENCY,
    _LIMIT_CONFIG,
    _LimiterRegistry,
)

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #
_TICKLE_INTERVAL = 55  # seconds – CP API docs: tickle at least once /min
T = TypeVar("T")


def _round_price(val: float, digits: int = 2) -> float:
    """Round *val* to *digits* decimal places (helps with LMT/STP ticks)."""
    return float(Decimal(str(val)).quantize(Decimal(f"1.{'0' * digits}"), ROUND_HALF_UP))


def _normalize_stock_symbol(symbol: str) -> str:
    """Normalize equity symbols (IBKR prefers spaces instead of dots)."""
    if not symbol:
        return symbol
    cleaned = symbol.replace(".", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned or symbol


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
def _default_exchange_for(sec_type: str) -> Optional[str]:
    st = (sec_type or "").upper()
    if st in ("STK", "STOCK"):
        return "SMART"
    if st in ("FUT", "FUTURE", "FUTURES"):
        return "GLOBEX"
    if st in ("CASH", "FX", "FOREX"):
        return "IDEALPRO"
    return None


def _normalize_order_type(order_type: str) -> str:
    """Map friendly order type strings to IBKR orderType codes.

    The Client-Portal API expects canonical codes like MKT/LMT/STP/MOC.
    Upstream callers sometimes pass human-friendly strings (e.g. "Market").
    """
    raw = (order_type or "").strip()
    if not raw:
        return "MKT"
    key = raw.upper().replace(" ", "").replace("_", "")
    mapping = {
        "MKT": "MKT",
        "MARKET": "MKT",
        "LMT": "LMT",
        "LIMIT": "LMT",
        "STP": "STP",
        "STOP": "STP",
        "STOPLIMIT": "STP LMT",
        "STPLMT": "STP LMT",
        "STPLIMIT": "STP LMT",
        "STOPLMT": "STP LMT",
        "TRAIL": "TRAIL",
        "TRAILSTOP": "TRAIL",
        "TRAILINGSTOP": "TRAIL",
        "MOC": "MOC",
        "MARKETONCLOSE": "MOC",
        "MOO": "MOO",
        "MARKETONOPEN": "MOO",
    }
    return mapping.get(key, raw.upper())


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #
class IBInterfacing:
    """
    Stateless interface to Interactive Brokers Web API.

    Parameters
    ----------
    account_id : str, optional
        IB account to use (e.g. "DU-changeme").  If omitted, uses global settings
        or the first account returned by `/portfolio/accounts`.
    cacert_path : str, optional
        Path to a custom CA bundle (rarely needed unless the Gateway cert
        chain is non‑standard). If omitted, uses global settings.
    oauth_params : dict, optional
        Explicit OAuth credential dictionary:
        {
            "consumer_key": ...,
            "access_token": ...,
            "access_token_secret": ...,
            "encryption_key_fp": "...pem",
            "signature_key_fp": "...pem",
            "dh_prime": "...",   # optional
        }
        If omitted and use_global_settings=True, uses global settings.
    use_global_settings : bool, optional
        Whether to use global settings for missing parameters. Default True.
    """

    # -------------------- construction & teardown --------------------- #
    def __init__(
        self,
        *,
        account_id: Optional[str] = None,
        cacert_path: Optional[str] = None,
        oauth_params: Optional[Dict[str, Any]] = None,
        use_global_settings: bool = True,
    ) -> None:
        # ---- build kwargs for IbkrClient --------------------------------
        client_kwargs: Dict[str, Any] = {}

        # Global settings fallback removed; require explicit oauth/account from caller
        if use_global_settings and not cacert_path:
            cacert_path = settings.ib_cacert_path

        if cacert_path or os.getenv("IBIND_CACERT"):
            client_kwargs["cacert"] = cacert_path or os.getenv("IBIND_CACERT")

        # OAuth
        if oauth_params:
            # ibind's OAuth1aConfig accepts a set of keyword args; stubs may differ.
            # Use a flexible type to satisfy static checkers.
            oauth_cfg: Any = OAuth1aConfig(**oauth_params)
            oauth_cfg.verify_config()  # raises if incomplete
            client_kwargs.update({"use_oauth": True, "oauth_config": oauth_cfg})

        # Instantiate the REST client
        self.client: IbkrClient = IbkrClient(**client_kwargs)
        logger.info(
            "IbkrClient instantiated (OAuth=%s).",
            "Yes" if client_kwargs.get("use_oauth") else "Env/None",
        )

        # Determine account
        self.account_id: str = account_id or self._select_default_account()
        # ibind exposes attribute for convenience
        try:
            self.client.account_id = self.account_id
        except AttributeError:
            pass
        self._limit_key: str = (self.account_id or "GLOBAL").upper()

        # Track last successful tickle time
        self._last_tickle: float = 0.0
        # In-process cache for IBKR contract ids to skip repeated searches
        self._conid_cache: Dict[str, Tuple[int, float]] = {}
        self._conid_cache_lock = threading.RLock()
        try:
            self._conid_ttl: float = float(os.getenv("IB_CONID_CACHE_TTL_SECONDS", "86400"))
        except Exception:
            self._conid_ttl = 86400.0
        self._retry_attempts: int = max(1, _env_int("IBKR_RETRY_ATTEMPTS", 3))
        self._retry_base_delay: float = max(
            0.0, _env_float("IBKR_RETRY_BASE_DELAY_SECONDS", 0.25)
        )
        self._retry_max_delay: float = max(0.0, _env_float("IBKR_RETRY_MAX_DELAY_SECONDS", 2.0))
        self._retry_jitter: float = max(0.0, _env_float("IBKR_RETRY_JITTER_RATIO", 0.2))
        self._futures_manual_indicator: bool = _env_bool(
            "IBKR_FUTURES_MANUAL_INDICATOR", False
        )

    def _instrument_ibkr_call(self, operation: str, fn: Callable[[], T]) -> T:
        timer = Timer()
        try:
            return fn()
        except Exception as exc:
            record_ibkr_request_error(account=self.account_id, operation=operation, exc=exc)
            raise
        finally:
            observe_ibkr_request_seconds(
                account=self.account_id, operation=operation, seconds=timer.seconds()
            )

    # ------------------------------------------------------------------ #
    # Context‑manager & explicit close
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "IBInterfacing":
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        """
        Optional explicit end of Web‑API session.

        By default we DO NOT call `/logout` to avoid tearing down the bridge
        used by other long‑lived clients in the same process/host. To enable
        explicit logout on close, set env `IBKR_LOGOUT_ON_CLOSE=true`.
        """
        try:
            if str(os.getenv("IBKR_LOGOUT_ON_CLOSE", "false")).lower() in (
                "1",
                "true",
                "yes",
            ):  # pragma: no cover
                if hasattr(self.client, "logout"):
                    self.client.logout()
                    logger.info("Logged out from IBKR session.")
                else:
                    # Fallback: POST /logout endpoint directly
                    self.client.post("logout")
                    logger.info("POST /logout sent.")
            else:
                logger.debug("Skipping IBKR logout on close (env disabled).")
        except Exception as e:  # pragma: no cover - non-critical
            logger.warning("Failed to logout cleanly: %s", e)

    # --------------------------- internals ----------------------------- #
    def _select_default_account(self) -> str:
        accounts_resp = self.client.portfolio_accounts()  # [{accountId: ..}, ...]
        accounts = accounts_resp.data if hasattr(accounts_resp, "data") else accounts_resp
        if not accounts:
            # Test stubs may not return accounts; fall back to client attribute
            fallback = getattr(self.client, "account_id", None)
            if fallback:
                logger.info("Using fallback account %s.", fallback)
                return str(fallback)
            raise RuntimeError("No IBKR accounts accessible with provided credentials.")
        first = accounts[0]
        aid: str = first.get("accountId") or first.get("id") or str(first)
        logger.info("Using account %s.", aid)
        return aid

    def _tickle_if_needed(self) -> None:
        """
        Keep the Client‑Portal session alive: GET /tickle at least once a minute.
        """
        now = time.time()
        if now - self._last_tickle < _TICKLE_INTERVAL:
            return
        try:
            self.client.get("tickle")
            self._last_tickle = now
            logger.debug("Tickle OK – session refreshed.")
        except ExternalBrokerError as e:
            msg = str(e).lower()
            # Reinitialize the bridge/session if it has fallen over
            if "no bridge" in msg or "initialize_brokerage_session" in msg:
                try:
                    self.client.initialize_brokerage_session()
                    self.client.receive_brokerage_accounts()
                    self._last_tickle = now
                    logger.info("IBKR bridge reinitialized after tickle.")
                    return
                except Exception as init_exc:
                    logger.warning("Tickle reinit failed: %s", init_exc)
            logger.warning("Tickle failed (will retry later): %s", e)
        except Exception as e:
            logger.warning("Tickle failed (session may reconnect automatically): %s", e)

    # Decorator for methods that require keep‑alive
    @staticmethod
    def _needs_alive(func):
        def wrapper(self: "IBInterfacing", *args, **kwargs):
            self._tickle_if_needed()
            return func(self, *args, **kwargs)

        return wrapper

    def _throttle(self, category: Optional[str] = None) -> None:
        if _GLOBAL_RPS > 0:
            _LimiterRegistry.acquire("GLOBAL", "global", _GLOBAL_RPS, _GLOBAL_BURST)
        if not category:
            return
        cfg = _LIMIT_CONFIG.get(category)
        if not cfg:
            return
        rate = cfg.get("rate", 0.0)
        burst = cfg.get("burst")
        if rate <= 0:
            return
        _LimiterRegistry.acquire(self._limit_key, category, rate, burst)

    @staticmethod
    def _error_message(exc: Exception) -> str:
        return str(exc).lower()

    @classmethod
    def _is_bridge_error(cls, exc: Exception) -> bool:
        msg = cls._error_message(exc)
        return "no bridge" in msg or "initialize_brokerage_session" in msg

    @classmethod
    def _is_retryable_error(cls, exc: Exception) -> bool:
        msg = cls._error_message(exc)
        retry_tokens = (
            "no bridge",
            "initialize_brokerage_session",
            "429",
            "rate limit",
            "too many requests",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "service unavailable",
            "connection aborted",
            "remote end closed connection",
            "gateway timeout",
            "bad gateway",
        )
        return any(token in msg for token in retry_tokens)

    def _retry_sleep(self, attempt: int) -> None:
        if self._retry_base_delay <= 0:
            return
        delay = min(self._retry_base_delay * (2 ** max(attempt - 1, 0)), self._retry_max_delay)
        if self._retry_jitter > 0:
            jitter = random.uniform(-self._retry_jitter, self._retry_jitter)
            delay = max(0.0, delay * (1.0 + jitter))
        if delay > 0:
            time.sleep(delay)

    def _reinitialize_bridge(self) -> None:
        self.client.initialize_brokerage_session()
        self.client.receive_brokerage_accounts()

    def _request_with_retry(
        self,
        operation: str,
        fn: Callable[[], T],
        *,
        throttle_category: Optional[str] = None,
        max_attempts: Optional[int] = None,
    ) -> T:
        attempts = max(1, int(max_attempts or self._retry_attempts))
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            if throttle_category:
                self._throttle(throttle_category)
            try:
                return self._instrument_ibkr_call(operation, fn)
            except Exception as exc:
                last_exc = exc
                retryable = self._is_retryable_error(exc)
                bridge_error = self._is_bridge_error(exc)
                if bridge_error:
                    try:
                        self._reinitialize_bridge()
                    except Exception as bridge_exc:
                        logger.warning("IBKR bridge reinit failed during %s: %s", operation, bridge_exc)
                if (not retryable) or attempt >= attempts:
                    raise
                logger.warning(
                    "%s failed (attempt %s/%s): %s; retrying",
                    operation,
                    attempt,
                    attempts,
                    exc,
                )
                self._retry_sleep(attempt)

        # Defensive fallback: loop always returns or raises.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"{operation} failed without exception")

    def _use_futures_manual_indicator(self, sec_type: str) -> bool:
        st = (sec_type or "").upper()
        return st in {"FUT", "FUTURE", "FUTURES", "FOP"}

    @staticmethod
    def _sanitize_idempotency_key(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")
        return cleaned[:48] if cleaned else ""

    def _build_order_coid(
        self,
        *,
        conid: int,
        side: str,
        quantity: int,
        order_type: str,
        limit_price: Optional[float],
        stop_price: Optional[float],
        trail_percent: Optional[float],
        outside_rth: bool,
        idempotency_key: Optional[str],
    ) -> str:
        if idempotency_key:
            normalized = self._sanitize_idempotency_key(idempotency_key)
            digest = hashlib.sha1(idempotency_key.encode("utf-8")).hexdigest()[:12]
            if normalized:
                return f"ra-{normalized[:35]}-{digest}"
            return f"ra-{digest}"
        return f"py{int(time.time() * 1000)}"

    def ping(self) -> bool:
        """
        Actively verify the IBKR session is alive. Attempts to re-initialize the
        bridge if the Client-Portal reports \"no bridge\".
        """
        try:
            self.client.get("tickle")
            self._last_tickle = time.time()
            return True
        except ExternalBrokerError as exc:
            if (
                "no bridge" in str(exc).lower()
                or "initialize_brokerage_session" in str(exc).lower()
            ):
                try:
                    self.client.initialize_brokerage_session()
                    self.client.receive_brokerage_accounts()
                    self.client.get("tickle")
                    self._last_tickle = time.time()
                    return True
                except Exception as inner:
                    logger.warning("IBKR ping reinit failed: %s", inner)
                    raise
            raise

    # ------------------------------------------------------------------ #
    # 1) Contract search
    # ------------------------------------------------------------------ #
    @_needs_alive
    def search_contracts(
        self,
        symbol: str,
        sec_type: str = "STK",
        *,
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        # Ensure brokerage session is initialized; tolerate failures (calls below also retry)
        try:
            self._ensure_account_selection()
        except Exception:
            pass
        sec_type = sec_type.upper()
        raw_symbol = symbol
        query_symbol = symbol
        if sec_type in ("STK", "STOCK"):
            query_symbol = _normalize_stock_symbol(symbol)

        logger.info(
            "Searching contracts %s (query=%s) %s (ex=%s cur=%s)",
            raw_symbol,
            query_symbol,
            sec_type,
            exchange or "-",
            currency or "-",
        )
        try:
            if sec_type in ("STK", "STOCK"):
                # Hard default exchange for stocks
                ex = exchange or _default_exchange_for(sec_type) or None
                q: Dict[str, str] = {}
                if ex:
                    q["exchange"] = ex
                if currency:
                    q["currency"] = currency
                # Use explicit query to honor exchange filtering
                query = StockQuery(query_symbol, contract_conditions=q)
                # One-shot reconnect on 'no bridge'
                try:
                    resp = self.client.security_stocks_by_symbol(query, default_filtering=False)
                except ExternalBrokerError as exc:
                    if "no bridge" in str(exc).lower():
                        self.client.initialize_brokerage_session()
                        self._ensure_account_selection()
                        resp = self.client.security_stocks_by_symbol(query, default_filtering=False)
                    else:
                        raise
                data = resp.data if hasattr(resp, "data") else resp
                # Normalize to a list of "items", where each item is a dict
                # containing a "contracts" list. ibind/IBKR sometimes return:
                # - dict keyed by symbol -> [ {assetClass, name, contracts:[...]}, ...]
                # - list of such dicts
                # - or, on transient errors, a plain string. Be defensive.
                items = None
                if isinstance(data, dict):
                    candidates = [
                        query_symbol.upper(),
                        raw_symbol.upper(),
                        query_symbol,
                        raw_symbol,
                    ]
                    for cand in candidates:
                        candidate_items = data.get(cand)
                        if candidate_items:
                            items = candidate_items
                            break
                    if items is None:
                        # Some ibind versions wrap directly under 'data' or similar
                        # Try to treat any dict value that looks like a list-of-items
                        for v in data.values():
                            if isinstance(v, list):
                                items = v
                                break
                elif isinstance(data, list):
                    items = data
                else:
                    # Unexpected type (e.g., string); fall back to secdef search
                    items = None

                # Guard against scalar/str items
                if not isinstance(items, list):
                    items = []

                # Build results defensively, skipping malformed entries
                results: List[Dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    contracts = item.get("contracts") or []
                    if not isinstance(contracts, list):
                        continue
                    for contract in contracts:
                        if not isinstance(contract, dict):
                            continue
                        results.append(
                            {
                                **contract,
                                "assetClass": item.get("assetClass"),
                                "name": item.get("name"),
                            }
                        )

                # If exchange specified or defaulted, prefer matching entries first
                def _reorder_by_exchange(
                    lst: List[Dict[str, Any]], ex: Optional[str]
                ) -> List[Dict[str, Any]]:
                    if not ex:
                        return lst
                    ex_up = ex.upper()
                    matches: List[Dict[str, Any]] = []
                    rest: List[Dict[str, Any]] = []
                    for c in lst:
                        cx = (
                            c.get("exchange")
                            or c.get("listingExchange")
                            or c.get("primaryExchange")
                            or ""
                        ).upper()
                        (matches if cx == ex_up else rest).append(c)
                    return matches + rest

                results = _reorder_by_exchange(results, ex)
                if results:
                    return results
                # fallback to secdef search with normalized symbol
                try:
                    secdef = self.client.get(
                        "iserver/secdef/search", params={"symbol": query_symbol}
                    )
                except ExternalBrokerError as exc:
                    if "no bridge" in str(exc).lower():
                        self.client.initialize_brokerage_session()
                        self._ensure_account_selection()
                        secdef = self.client.get(
                            "iserver/secdef/search", params={"symbol": query_symbol}
                        )
                    else:
                        raise
                sd_data = secdef.data if hasattr(secdef, "data") else secdef
                # Normalize secdef payload to a list of dicts
                if isinstance(sd_data, list):
                    return sd_data
                if isinstance(sd_data, dict):
                    # Some shapes: {"data": [...]}
                    inner = sd_data.get("data") if hasattr(sd_data, "get") else None  # type: ignore[attr-defined]
                    return inner if isinstance(inner, list) else []
                return []
            if sec_type in ("FUT", "FUTURE"):
                try:
                    resp = self.client.get("trsrv/futures", params={"symbols": symbol})
                except ExternalBrokerError as exc:
                    if "no bridge" in str(exc).lower():
                        self.client.initialize_brokerage_session()
                        self._ensure_account_selection()
                        resp = self.client.get("trsrv/futures", params={"symbols": symbol})
                    else:
                        raise
                data = resp.data if hasattr(resp, "data") else resp
                from typing import cast

                lst = cast(
                    List[Dict[str, Any]], data.get(symbol.upper()) or data.get(symbol) or data
                )
                # Prefer exchange (default GLOBEX) if present
                ex = exchange or _default_exchange_for(sec_type) or None
                if ex and isinstance(lst, list):
                    ex_up = ex.upper()
                    matches: List[Dict[str, Any]] = []
                    rest: List[Dict[str, Any]] = []
                    for it in lst:
                        cx = (
                            it.get("exchange")
                            or it.get("listingExchange")
                            or it.get("primaryExchange")
                            or it.get("market")
                            or ""
                        ).upper()
                        (matches if cx == ex_up else rest).append(it)
                    lst = matches + rest
                return lst
            if sec_type in ("CASH", "FX", "FOREX"):
                base = symbol[:3].upper()
                quote = symbol[3:].upper() if len(symbol) > 3 else (currency or "USD")
                # Hard default to IDEALPRO for FX/CASH
                exch = exchange or _default_exchange_for(sec_type) or "IDEALPRO"
                query = StockQuery(base, contract_conditions={"exchange": exch, "currency": quote})
                resp = self.client.security_stocks_by_symbol(query, default_filtering=False)
                data = resp.data if hasattr(resp, "data") else resp
                items = None
                if isinstance(data, dict):
                    items = data.get(base)
                elif isinstance(data, list):
                    items = data
                # Normalize
                if not isinstance(items, list):
                    items = []

                results: List[Dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    contracts = item.get("contracts") or []
                    if not isinstance(contracts, list):
                        continue
                    for contract in contracts:
                        if not isinstance(contract, dict):
                            continue
                        results.append(
                            {
                                **contract,
                                "assetClass": item.get("assetClass", "CASH"),
                                "name": f"{base}/{quote}",
                            }
                        )
                # fallback to secdef search if empty or malformed
                if not results:
                    try:
                        sd = self.client.get(
                            "iserver/secdef/search", params={"symbol": f"{base}{quote}"}
                        )
                    except ExternalBrokerError as exc:
                        if "no bridge" in str(exc).lower():
                            self.client.initialize_brokerage_session()
                            self._ensure_account_selection()
                            sd = self.client.get(
                                "iserver/secdef/search", params={"symbol": f"{base}{quote}"}
                            )
                        else:
                            raise
                    sd_data = sd.data if hasattr(sd, "data") else sd
                    if isinstance(sd_data, list):
                        return sd_data
                    if isinstance(sd_data, dict):
                        inner = sd_data.get("data") if hasattr(sd_data, "get") else None  # type: ignore[attr-defined]
                        return inner if isinstance(inner, list) else []
                    return []
                return results
            raise ValueError(f"Unsupported sec_type {sec_type}")
        except Exception as e:
            if is_broker_sentry_quiet_hours():
                logger.warning("search_contracts failed during quiet hours: %s", e)
            else:
                logger.error("search_contracts failed: %s", e)
            raise

    # ------------------------------------------------------------------ #
    # 2) Market‑data snapshot
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # 2) Market-data snapshot (via MarketdataMixin)                     #
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_market_data(
        self,
        symbol: Optional[str] = None,
        exchange: Optional[str] = None,
        *,
        conid: Optional[int] = None,
        sec_type: str = "STK",
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve snapshot market data as a dict mapping field codes to values.

        Now delegates to ibind.MarketdataMixin.live_marketdata_snapshot
        instead of making a raw REST call.
        """
        # ----------- resolve conid (with cache) ------------------------
        # Apply hard default exchange if not provided
        exchange = exchange or _default_exchange_for(sec_type) or exchange

        if not conid:
            if not symbol:
                raise ValueError("Must provide either symbol or conid.")
            key_symbol = symbol
            if sec_type.upper() in ("STK", "STOCK"):
                key_symbol = _normalize_stock_symbol(symbol)
            cache_key = f"{sec_type.upper()}:{key_symbol.upper()}:{exchange or ''}:{currency or ''}"
            now_ts = time.time()
            with self._conid_cache_lock:
                cached = self._conid_cache.get(cache_key)
                if cached and (now_ts - cached[1]) < self._conid_ttl:
                    conid = int(cached[0])

            if not conid:
                contracts = self.search_contracts(
                    symbol, sec_type, exchange=exchange, currency=currency
                )
                if not contracts:
                    raise RuntimeError(f"No contracts found for {symbol}.")
                conid = int(contracts[0]["conid"])  # heuristic: first match
                with self._conid_cache_lock:
                    self._conid_cache[cache_key] = (conid, now_ts)
                    # also store raw symbol key for completeness if different
                    raw_key = (
                        f"{sec_type.upper()}:{symbol.upper()}:{exchange or ''}:{currency or ''}"
                    )
                    if raw_key != cache_key:
                        self._conid_cache[raw_key] = (conid, now_ts)

        # ----------- IBKR pre-reqs -------------------------------------
        self._ensure_account_selection()  # /iserver/accounts
        # Request only the fields we need (LAST=31, Yesterday CLOSE=7741, CHANGE%=83) to reduce payload/latency.
        # https://www.interactivebrokers.com/campus/ibkr-api-page/webapi-ref/#tag/Trading-Market-Data/paths/~1iserver~1marketdata~1snapshot/get
        fields = ["31", "7741", "83"]

        # ----------- snapshot (do the “priming” call + real call) ------
        # First call occasionally returns an empty list; retry. If we hit
        # "no bridge", reinitialize the session once and retry.
        def _do_snapshot() -> Any:
            self._throttle("snapshot")
            return self.client.live_marketdata_snapshot(conids=[str(conid)], fields=fields)

        try:
            _do_snapshot()
        except ExternalBrokerError as e:
            if "no bridge" in str(e).lower():
                self.client.initialize_brokerage_session()
                self._ensure_account_selection()
            else:
                raise
        time.sleep(0.25)
        for attempt in range(3):  # up to 3 tries after priming
            try:
                resp = _do_snapshot()
            except ExternalBrokerError as e:
                if "no bridge" in str(e).lower() and attempt == 0:
                    self.client.initialize_brokerage_session()
                    self._ensure_account_selection()
                    time.sleep(0.2)
                    continue
                raise
            if (
                resp.data
                and isinstance(resp.data, list)
                and resp.data
                and isinstance(resp.data[0], dict)
                and (
                    "31" in resp.data[0]
                    or "55" in resp.data[0]
                    or "84" in resp.data[0]
                    or "86" in resp.data[0]
                    or "7741" in resp.data[0]
                )
            ):
                break  # got something meaningful
            time.sleep(0.25)

        raw = resp.data if hasattr(resp, "data") else resp

        # ----------- massage the payload -------------------------------
        # live_marketdata_snapshot returns a list of dicts like
        # [{'31': '208.77', '55': '208.79', …, 'conid': 265598}, …]
        #
        # We flatten that to {field_code: value}.
        if not isinstance(raw, list) or not raw:
            raise RuntimeError(f"Unexpected snapshot format for conid {conid}: {raw}")

        entry = raw[0] if isinstance(raw[0], dict) else {}
        result: Dict[str, Any] = {str(k): v for k, v in entry.items() if k != "conid"}

        # Add convenient field names for common use cases
        def _maybe_float(val):
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        if "55" in result:  # Bid
            result["bid"] = _maybe_float(result["55"])
        if "84" in result:  # Ask
            result["ask"] = _maybe_float(result["84"])
        if "31" in result:  # Last
            result["last"] = _maybe_float(result["31"])
        if "7741" in result:  # Close
            result["close"] = _maybe_float(result["7741"])
        if "83" in result:  # Change %
            result["change_pct"] = _maybe_float(result["83"])

        return result

    # ------------------------------------------------------------------ #
    # 3) Historical data
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_historical_data(
        self,
        *,
        symbol: Optional[str] = None,
        conid: Optional[int] = None,
        period: str = "1 D",
        bar: str = "1 hour",
        outside_rth: bool = False,
        sec_type: str = "STK",
        exchange: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> Any:
        """
        Retrieve historical OHLC bars.

        Tries primary intraday request; on server error (500), retries once
        with daily bars (bar='1 day') as a fallback.
        """

        # Apply hard default exchange if not provided
        exchange = exchange or _default_exchange_for(sec_type) or exchange

        # Resolve conid if necessary
        if not conid:
            if not symbol:
                raise ValueError("Must provide symbol or conid.")
            ctrs = self.search_contracts(symbol, sec_type, exchange=exchange, currency=currency)
            if not ctrs:
                raise RuntimeError(f"Cannot resolve contract for {symbol}.")
            conid = ctrs[0]["conid"]

        def _history_request(bar_size: str):
            with _LimiterRegistry.hold_semaphore(
                self._limit_key, "history", _HISTORY_MAX_CONCURRENCY
            ):
                self._throttle("history")
                resp_inner = self.client.marketdata_history_by_conid(
                    conid, period=period, bar=bar_size, outside_rth=outside_rth
                )
            return resp_inner.data if hasattr(resp_inner, "data") else resp_inner

        try:
            return _history_request(bar)
        except ExternalBrokerError as e:
            # Reinitialize once on 'no bridge' and retry the same request
            if "no bridge" in str(e).lower():
                try:
                    self.client.initialize_brokerage_session()
                    self._ensure_account_selection()
                    return _history_request(bar)
                except Exception as e2:
                    # fall through to daily fallback below
                    e = e2  # type: ignore[assignment]
            # 500 from IBKR often means intraday endpoint not available
            logger.warning(
                "History request failed (%s) for period=%s bar=%s; retrying with daily bars.",
                e,
                period,
                bar,
            )
        except Exception as e:
            # 500 from IBKR often means intraday endpoint not available
            logger.warning(
                "History request failed (%s) for period=%s bar=%s; retrying with daily bars.",
                e,
                period,
                bar,
            )
            try:
                return _history_request("1 day")
            except ExternalBrokerError as e2:
                if "no bridge" in str(e2).lower():
                    self.client.initialize_brokerage_session()
                    self._ensure_account_selection()
                    return _history_request("1 day")
                raise RuntimeError(
                    f"Historical data failed for conid {conid}: {e} (fallback failed: {e2})"
                ) from None
            except Exception as e2:
                raise RuntimeError(
                    f"Historical data failed for conid {conid}: {e} (fallback failed: {e2})"
                ) from None

    # ------------------------------------------------------------------ #
    # 4) Order placement / modification / cancel
    # ------------------------------------------------------------------ #
    @_needs_alive
    def place_order(
        self,
        position_settings=None,
        price_hint: Optional[float] = None,
        *,
        symbol: Optional[str] = None,
        conid: Optional[int] = None,
        sec_type: str = "STK",
        side: str = "BUY",
        quantity: int = 1,
        order_type: str = "MKT",
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        profit_target: Optional[float] = None,
        stop_loss: Optional[float] = None,
        trail_percent: Optional[float] = None,
        outside_rth: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        # Handle PositionSettings object if provided
        if position_settings is not None:
            symbol = position_settings.symbol
            quantity = position_settings.size
            order_type = position_settings.order_type or "MKT"
            limit_price = position_settings.limit_price
            stop_price = position_settings.stop_price
            trail_percent = getattr(position_settings, "trail_percent", None)
            profit_target = position_settings.profit_target
            stop_loss = position_settings.stop_loss
            sec_type = getattr(position_settings, "sec_type", sec_type)
            idempotency_key = (
                idempotency_key
                or getattr(position_settings, "idempotency_key", None)
                or getattr(position_settings, "custom_string", None)
                or getattr(position_settings, "tag", None)
            )
            # Determine side from position_type
            side = "BUY" if position_settings.position_type == "Long" else "SELL"

        if not conid:
            if not symbol:
                raise ValueError("Need symbol or conid.")
            conid = self.search_contracts(symbol, sec_type)[0]["conid"]
        side = side.upper()
        order_type = _normalize_order_type(order_type)

        parent_price = None
        aux_price = None
        if order_type == "LMT":
            if limit_price is None:
                raise ValueError("Limit price required for LMT order.")
            parent_price = _round_price(limit_price)
        elif order_type == "STP":
            if stop_price is None:
                raise ValueError("Stop price required for STP order.")
            parent_price = _round_price(stop_price)
        elif order_type == "STP LMT":
            if limit_price is None or stop_price is None:
                raise ValueError("Limit and stop price required for STP LMT order.")
            parent_price = _round_price(limit_price)
            aux_price = _round_price(stop_price)
        elif order_type == "TRAIL":
            if trail_percent is None:
                raise ValueError("Trail percent required for TRAIL order.")

        tag = self._build_order_coid(
            conid=int(conid),
            side=side,
            quantity=int(quantity),
            order_type=order_type,
            limit_price=parent_price,
            stop_price=aux_price,
            trail_percent=trail_percent,
            outside_rth=outside_rth,
            idempotency_key=idempotency_key,
        )
        parent = make_order_request(
            conid=conid,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=parent_price,
            aux_price=aux_price,
            tif="DAY",
            acct_id=self.account_id,
            coid=tag,
            outside_rth=outside_rth,
        )
        if self._use_futures_manual_indicator(sec_type):
            parent["manualIndicator"] = self._futures_manual_indicator
        if order_type == "TRAIL" and trail_percent is not None:
            # Client Portal (CP) API trailing stop uses trailingType + trailingAmt (percent).
            # - trailingType: "%" for percent-based trailing
            # - trailingAmt:  0..100 (percent, not a fraction)
            try:
                parent["trailingType"] = "%"
                parent["trailingAmt"] = float(trail_percent)
            except Exception:
                pass
        requests: List[Dict[str, Any]] = [parent]

        if profit_target or stop_loss:
            close_side = "SELL" if side == "BUY" else "BUY"
            if profit_target:
                tp = make_order_request(
                    conid=conid,
                    side=close_side,
                    quantity=quantity,
                    order_type="LMT",
                    price=_round_price(profit_target),
                    tif="GTC",
                    acct_id=self.account_id,
                    parent_id=tag,
                )
                if self._use_futures_manual_indicator(sec_type):
                    tp["manualIndicator"] = self._futures_manual_indicator
                requests.append(tp)
            if stop_loss:
                sl = make_order_request(
                    conid=conid,
                    side=close_side,
                    quantity=quantity,
                    order_type="STP",
                    price=_round_price(stop_loss),
                    tif="GTC",
                    acct_id=self.account_id,
                    parent_id=tag,
                )
                if self._use_futures_manual_indicator(sec_type):
                    sl["manualIndicator"] = self._futures_manual_indicator
                requests.append(sl)

        answers = {
            QuestionType.PRICE_PERCENTAGE_CONSTRAINT: True,
            QuestionType.ORDER_VALUE_LIMIT: True,
            QuestionType.MISSING_MARKET_DATA: True,
            QuestionType.STOP_ORDER_RISKS: True,
        }
        self._ensure_account_selection()
        resp = self._request_with_retry(
            "place_order",
            lambda: self.client.place_order(
                requests if len(requests) > 1 else requests[0], answers, self.account_id
            ),
            throttle_category="orders",
        )
        result = resp.data if hasattr(resp, "data") else resp
        logger.info("Order placed – response: %s", result)

        # Extract order IDs from the response and return as a list
        order_ids = []
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    order_id = item.get("order_id") or item.get("orderId") or item.get("id")
                    if order_id:
                        try:
                            order_ids.append(int(order_id))
                        except (ValueError, TypeError):
                            pass
        elif isinstance(result, dict):
            order_id = result.get("order_id") or result.get("orderId") or result.get("id")
            if order_id:
                try:
                    order_ids.append(int(order_id))
                except (ValueError, TypeError):
                    pass

        # Return list of order IDs for compatibility with order_placement.py
        return order_ids if order_ids else [0]  # Return [0] as fallback if no IDs found

    @_needs_alive
    def modify_order(self, position_settings_or_order_id, order_id_or_kwargs=None, **kwargs) -> Any:
        """
        Modify an existing order.

        Can be called in two ways:
        1. modify_order(position_settings, order_id) - new style from order_placement.py
        2. modify_order(order_id, **kwargs) - legacy style
        """
        if hasattr(position_settings_or_order_id, "symbol"):
            # New style: position_settings as first argument, order_id as second
            position_settings = position_settings_or_order_id
            order_id = order_id_or_kwargs
            sec_type = getattr(position_settings, "sec_type", "STK")
            self.cancel_order(order_id, sec_type=sec_type)
            return self.place_order(position_settings)
        else:
            # Legacy style: order_id as first argument
            order_id = position_settings_or_order_id
            kwargs.update(order_id_or_kwargs or {})
            sec_type = kwargs.get("sec_type", "STK")
            self.cancel_order(order_id, sec_type=sec_type)
            return self.place_order(**kwargs)

    @_needs_alive
    def cancel_order(self, order_id: int, *, sec_type: str = "STK") -> Any:
        self._ensure_account_selection()

        def _cancel_with_optional_manual() -> Any:
            payload: Dict[str, Any] = {"order_id": order_id, "account_id": self.account_id}
            if self._use_futures_manual_indicator(sec_type):
                payload["manualIndicator"] = self._futures_manual_indicator
            try:
                return self.client.cancel_order(**payload)
            except TypeError:
                payload.pop("manualIndicator", None)
                return self.client.cancel_order(**payload)

        resp = self._request_with_retry(
            "cancel_order", _cancel_with_optional_manual, throttle_category="orders"
        )
        logger.debug("Cancel order response: %s", resp)
        data = resp.data if hasattr(resp, "data") else resp
        return data

    # ------------------------------------------------------------------ #
    # 5) Open orders                                                     #
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """
        Return every open order as a list[dict], no matter which shape ibind
        decides to send back.

        Supported upstream formats
        --------------------------
        • ibind ≤ 0.8.x  →  {"orders": [ … ]}  or  {"openOrders": [ … ]}
        • ibind ≥ 0.9.x  →  [ … ]  (plain list-of-dicts)

        We normalise all of them to list[dict].
        """
        self._ensure_account_selection()

        # ---------- refresh the cache / force full pull -----------------
        try:
            # old signature
            self._request_with_retry(
                "live_orders_refresh",
                lambda: self.client.live_orders(filters=[], force=True),
                throttle_category="orders",
                max_attempts=2,
            )
        except TypeError:
            # new signature (≥ 0.9) – 'filters' param removed
            self._request_with_retry(
                "live_orders_refresh",
                lambda: self.client.live_orders(force=True),
                throttle_category="orders",
                max_attempts=2,
            )
        except Exception:
            # ignore – the next call will still succeed if the session is live
            pass

        # ---------- actual pull ----------------------------------------
        resp = self._request_with_retry(
            "live_orders", lambda: self.client.live_orders(), throttle_category="orders"
        )
        raw = resp.data if hasattr(resp, "data") else resp

        # ---------- normalise ------------------------------------------
        if isinstance(raw, dict):  # legacy wrapper
            return raw.get("orders") or raw.get("openOrders") or []

        if isinstance(raw, list):  # new straight-through list
            return raw

        logger.warning("Unexpected live_orders payload: %s", raw)
        return []

    # ------------------------------------------------------------------ #
    # 6) Account summary
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_account_summary(self) -> Dict[str, Any]:
        self._ensure_account_selection()
        resp = self._request_with_retry(
            "account_ledger",
            lambda: self.client.get(f"portfolio/{self.account_id}/ledger"),
            throttle_category="account",
        )
        from typing import cast

        return cast(Dict[str, Any], resp.data if hasattr(resp, "data") else resp)

    # ------------------------------------------------------------------ #
    # 7) Positions
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_positions(self) -> List[Dict[str, Any]]:
        resp = self._request_with_retry("positions", lambda: self.client.positions())
        data = resp.data if hasattr(resp, "data") else resp
        return list(data) if isinstance(data, Iterable) else [data]

    @_needs_alive
    def get_contract_details(self, contract_id: str) -> Dict[str, Any]:
        """
        Get contract details (symbol, exchange, etc.) from IBKR contract ID.

        Parameters
        ----------
        contract_id : str
            The IBKR contract ID (conid)

        Returns
        -------
        dict
            Contract details including symbol, exchange, currency, etc.
            Returns empty dict if contract not found.
        """
        self._tickle_if_needed()
        try:
            # Use the secdef/info endpoint to get contract details
            resp = self.client.get("iserver/secdef/info", params={"conid": str(contract_id)})
            data = resp.data if hasattr(resp, "data") else resp

            if isinstance(data, list) and len(data) > 0:
                from typing import cast

                return cast(Dict[str, Any], data[0])  # Return first contract details
            elif isinstance(data, dict):
                from typing import cast

                return cast(Dict[str, Any], data)
            else:
                logger.warning("No contract details found for conid %s", contract_id)
                return {}

        except Exception as e:
            logger.error("Failed to get contract details for conid %s: %s", contract_id, e)
            return {}

    @_needs_alive
    def get_symbol_from_contract_id(self, contract_id: str) -> Optional[str]:
        """
        Get the trading symbol from an IBKR contract ID.

        Parameters
        ----------
        contract_id : str
            The IBKR contract ID (conid)

        Returns
        -------
        str or None
            The trading symbol (e.g., "AAPL") if found, None otherwise
        """
        contract_details = self.get_contract_details(contract_id)
        sym = contract_details.get("symbol") or contract_details.get("ticker")
        return sym if isinstance(sym, str) else None

    # --------------------- helper to satisfy IB pre‑req ---------------- #
    def _ensure_account_selection(self) -> None:
        """
        `/iserver/marketdata/snapshot`, orders, etc. require a prior call to
        `/iserver/accounts`.  ibind wraps this in `receive_brokerage_accounts`.
        """
        try:
            self._request_with_retry(
                "receive_brokerage_accounts", lambda: self.client.receive_brokerage_accounts()
            )
        except AttributeError:
            # Fallback to portfolio_accounts if older ibind version
            self._request_with_retry("portfolio_accounts", lambda: self.client.portfolio_accounts())

    # ------------------------------------------------------------------ #
    # 8) Additional methods for place_transaction.py
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_last_close_price(self, symbol: str, exchange: Optional[str] = None) -> Optional[float]:
        """
        Get the last closing price for a symbol.

        Parameters
        ----------
        symbol : str
            The trading symbol
        exchange : str, optional
            The exchange (not used in current implementation)

        Returns
        -------
        float or None
            The last closing price if available, None otherwise
        """
        try:
            # Get market data which includes closing price
            quote = self.get_market_data(symbol=symbol, exchange=exchange)
            # Field 86 is the prior close
            close_price = quote.get("86") or quote.get("close")
            if close_price is not None:
                return float(close_price)
            # Fallback to last price if close not available
            last_price = quote.get("31")
            if last_price is not None:
                return float(last_price)
            return None
        except Exception as e:
            logger.warning("Failed to get last close price for %s: %s", symbol, e)
            return None

    @_needs_alive
    def get_available_fund(self) -> float:
        """
        Get available funds from account summary.

        Returns
        -------
        float
            Available funds amount
        """
        try:
            account_summary = self.get_account_summary()
            # Try to extract available funds from the ledger data
            if isinstance(account_summary, dict):
                # Look for fund data in various possible structures
                for _key, value in account_summary.items():
                    if isinstance(value, dict):
                        funds = value.get("funds")
                        if funds is not None:
                            return float(funds)
                        # Also try other fund-related fields
                        for fund_field in ["availablefunds", "fullavailablefunds", "cashbalance"]:
                            fund_value = value.get(fund_field)
                            if fund_value is not None and fund_value != 0:
                                return float(fund_value)
            logger.warning("Could not extract available funds from account summary")
            return 0.0
        except Exception as e:
            logger.warning("Failed to get available funds: %s", e)
            return 0.0

    @_needs_alive
    def get_available_fund_currency(self) -> str:
        """
        Get the currency of available funds.

        Returns
        -------
        str
            Currency code (e.g., 'USD', 'CAD')
        """
        try:
            account_summary = self.get_account_summary()
            if isinstance(account_summary, dict):
                # Look for currency in the ledger data
                for _key, value in account_summary.items():
                    if isinstance(value, dict):
                        currency = value.get("currency")
                        if isinstance(currency, str) and currency:
                            return currency
            return "USD"  # Default fallback
        except Exception as e:
            logger.warning("Failed to get available fund currency: %s", e)
            return "USD"

    @_needs_alive
    def get_yesterday_bar(
        self,
        symbol: str,
        exchange: Optional[str] = None,
        *,
        sec_type: str = "STK",
        currency: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get yesterday's OHLCV bar data for a symbol.

        Parameters
        ----------
        symbol : str
            The trading symbol
        exchange : str, optional
            The exchange (not used in current implementation)

        Returns
        -------
        dict or None
            Dictionary with OHLCV data including 'volume' key, or None if not available
        """
        try:
            # Get 2 days of daily data to ensure we have yesterday's bar
            hist_data = self.get_historical_data(
                symbol=symbol,
                period="2d",
                bar="1d",
                sec_type=sec_type,
                exchange=exchange,
                currency=currency,
            )

            if hist_data and isinstance(hist_data, dict):
                data = hist_data.get("data", [])
                if data and len(data) >= 1:
                    # Return the most recent complete bar (yesterday's)
                    latest_bar = data[-1] if len(data) == 1 else data[-2]
                    return {
                        "open": latest_bar.get("o"),
                        "high": latest_bar.get("h"),
                        "low": latest_bar.get("l"),
                        "close": latest_bar.get("c"),
                        "volume": latest_bar.get("v"),
                        "date": latest_bar.get("t"),
                    }
            return None
        except Exception as e:
            logger.warning("Failed to get yesterday's bar for %s: %s", symbol, e)
            return None

    # -------------------- destructor (fallback) ------------------------ #
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 9) Recent trades (executions)
    # ------------------------------------------------------------------ #
    @_needs_alive
    def get_recent_trades(self, since_seconds: int = 900) -> List[Dict[str, Any]]:
        """
        Fetch recent executions from IBKR. Returns a list[dict].

        Attempts the Client-Portal endpoint `/iserver/account/trades` and
        tolerates shape differences across ibind versions.
        """
        self._ensure_account_selection()
        try:
            # Try with a 'since' parameter (seconds)
            resp = self._request_with_retry(
                "recent_trades",
                lambda: self.client.get(
                    "iserver/account/trades", params={"since": int(max(since_seconds, 0))}
                ),
                throttle_category="trades",
            )
        except Exception:
            # Fallback without params
            resp = self._request_with_retry(
                "recent_trades_fallback",
                lambda: self.client.get("iserver/account/trades"),
                throttle_category="trades",
            )

        data = resp.data if hasattr(resp, "data") else resp

        # Normalise: prefer a flat list of dicts
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Common wrappers: {trades: [...]} or {executions: [...]}
            for key in ("trades", "executions", "data"):
                lst = data.get(key)
                if isinstance(lst, list):
                    return lst
        logger.debug("Unexpected trades payload: %s", data)
        return []
