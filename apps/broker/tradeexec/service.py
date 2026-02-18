# tradeexec/service.py
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.common.src.observability import instrument_fastapi_app

from .core.ib import IBInterfacing
from .events import RealTimeSignal, SignalBus
from .metrics import record_prev_close_error, record_price_snapshot_error
from .reports.daily import DailyReport
from .settings import AccountConfig, settings
from .trade_execution import ExecutionProgram
from .utils.sentry_quiet import is_broker_sentry_quiet_hours, is_ibkr_maintenance_error

logger = logging.getLogger(__name__)
_EASTERN_TZ = ZoneInfo("America/New_York")


def _is_prev_close_sentry_quiet_hours(now_et: datetime | None = None) -> bool:
    return is_broker_sentry_quiet_hours(now_et)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: build one ExecutionProgram per configured account and run forever.
    if not settings.accounts:
        logger.error("No accounts configured; check your .env")
        yield
        return
    for acc in settings.accounts:
        await start_account(acc)
    yield


app = FastAPI(title="TradeExec Service", lifespan=lifespan)
instrument_fastapi_app(app, service_name="rankalpha-broker")


# --------------------------- Models -----------------------------------
class SignalIn(BaseModel):
    account: str
    symbol: str
    action: str  # buy|sell|exit
    quantity: Optional[int] = None
    order_type: str = "MKT"  # MKT|LMT|STP|MOC
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    system: Optional[str] = None
    tag: Optional[str] = None
    custom_string: Optional[str] = None


class Status(BaseModel):
    account: str
    executing: bool
    ib_connected: Optional[bool] = None
    ib_last_error: Optional[str] = None
    last_checked_utc: Optional[datetime] = None


class PriceSnapshot(BaseModel):
    account: str
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    close: Optional[float] = None
    change_pct: Optional[float] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class PreviousClose(BaseModel):
    account: str
    symbol: str
    previous_close: Optional[float] = None
    as_of: Optional[str] = None
    source: str = Field(default="history", description="history|snapshot")
    raw: Dict[str, Any] = Field(default_factory=dict)


class SofrFuture(BaseModel):
    root: str = Field(description="SR3 (3M SOFR) or SR1 (1M SOFR)")
    local_symbol: str
    conid: Optional[int] = None
    year: int
    month: int
    expiry: Optional[str] = None
    last: Optional[float] = None
    settle: Optional[float] = None


class SofrFuturesResponse(BaseModel):
    account: str
    root: str
    exchange: str = "GLOBEX"
    items: list[SofrFuture]


class SofrDailyBar(BaseModel):
    as_of_date: date
    close: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class BrokerPositionItem(BaseModel):
    symbol: str
    quantity: float
    avg_cost: Optional[float] = None
    currency_code: Optional[str] = None
    conid: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)


class BrokerAccountSnapshot(BaseModel):
    account: str
    as_of_utc: datetime
    positions: List[BrokerPositionItem] = Field(default_factory=list)
    cash_by_ccy: Dict[str, float] = Field(default_factory=dict)
    nlv_by_ccy: Dict[str, float] = Field(default_factory=dict)
    ledger_raw: Dict[str, Any] = Field(default_factory=dict)


class IngestFillsRequest(BaseModel):
    lookback_seconds: int = Field(default=36 * 3600, ge=60, le=7 * 24 * 3600)


class IngestFillsResponse(BaseModel):
    account: str
    inserted: int
    lookback_seconds: int
    as_of_utc: datetime


class SofrContractHistory(BaseModel):
    root: str
    local_symbol: str
    conid: Optional[int] = None
    year: int
    month: int
    expiry: Optional[str] = None
    bars: list[SofrDailyBar]


class SofrFuturesHistoryResponse(BaseModel):
    account: str
    root: str
    exchange: str = "GLOBEX"
    period: str
    items: list[SofrContractHistory]


# --------------------------- State ------------------------------------
bus = SignalBus()
programs: Dict[str, ExecutionProgram] = {}
account_status: Dict[str, Status] = {}


class _TTLCache:
    def __init__(self, ttl_seconds: float) -> None:
        self.ttl = max(ttl_seconds, 0.0)
        self._lock = threading.Lock()
        self._store: Dict[Tuple[Any, ...], Tuple[float, Any]] = {}

    def get(self, key: Tuple[Any, ...]) -> Optional[Any]:
        if self.ttl <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires, value = entry
            if expires <= now:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: Tuple[Any, ...], value: Any) -> None:
        if self.ttl <= 0:
            return
        expires = time.monotonic() + self.ttl
        with self._lock:
            self._store[key] = (expires, value)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid value for %s=%r; falling back to %s", name, raw, default)
        return default


_PRICE_CACHE_TTL = _env_float("BROKER_PRICE_CACHE_TTL_SECONDS", 5.0)
_PREV_CLOSE_CACHE_TTL = _env_float("BROKER_PREV_CLOSE_CACHE_TTL_SECONDS", 30.0)
_price_cache = _TTLCache(_PRICE_CACHE_TTL)
_prev_close_cache = _TTLCache(_PREV_CLOSE_CACHE_TTL)


async def start_account(acc: AccountConfig) -> None:
    prog = ExecutionProgram(acc, settings)
    programs[acc.account_number] = prog
    account_status[acc.account_number] = Status(account=acc.account_number, executing=False)

    async def _runner():
        account_status[acc.account_number].executing = True
        try:
            await prog.run_supervised(bus)  # forever
        finally:
            account_status[acc.account_number].executing = False

    asyncio.create_task(_runner())
    logger.info("Started supervised executor for %s", acc.account_number)


# --------------------------- Endpoints --------------------------------
def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


async def _require_service_token(
    authorization: str | None = Header(default=None),
    service_token_header: str | None = Header(default=None, alias="X-RA-Service-Token"),
) -> None:
    token = (getattr(settings, "service_token", None) or "").strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Broker service token not configured",
        )

    supplied = (service_token_header or "").strip() or _extract_bearer(authorization)
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing service token (send X-RA-Service-Token or Authorization: Bearer <token>)",
        )
    if supplied != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


def _resolve_account_program(account: Optional[str] = None) -> tuple[str, ExecutionProgram]:
    target_account = account or next(iter(programs.keys()), None)
    if not target_account:
        raise HTTPException(status_code=503, detail="No accounts configured")
    program = programs.get(target_account)
    if program is None:
        raise HTTPException(status_code=404, detail="Unknown account")
    return target_account, program


@app.get("/health")
async def health(probe: bool = False):
    """Service health endpoint.

    By default this is a shallow health check (fast, no outbound calls) suitable for Docker healthchecks.
    Use `?probe=true` for a deeper check that pings IBKR for each configured account.
    """

    results: Dict[str, Any] = {}

    # Shallow: report last-known status without forcing an IBKR ping (which can be slow/noisy).
    if not probe:
        for acct, stat in account_status.items():
            results[acct] = stat.model_dump()
        # Include any programs without status (unlikely but safe guard).
        for acct in programs:
            if acct not in results:
                results[acct] = {
                    "account": acct,
                    "executing": programs[acct].is_running
                    if hasattr(programs[acct], "is_running")
                    else False,
                    "ib_connected": None,
                    "ib_last_error": None,
                    "last_checked_utc": None,
                }
        return results

    # Deep: best-effort IBKR ping with a timeout so /health never hangs indefinitely.
    timeout_seconds = _env_float("BROKER_HEALTH_PROBE_TIMEOUT_SECONDS", 2.0)
    tasks: Dict[str, asyncio.Task[Tuple[bool, Optional[str]]]] = {}

    for acct, prog in programs.items():
        tasks[acct] = asyncio.create_task(asyncio.to_thread(_probe_ib_connection, prog))

    now = datetime.now(UTC)
    for acct, stat in account_status.items():
        connected = None
        error_msg = None
        if acct in tasks:
            try:
                connected, error_msg = await asyncio.wait_for(tasks[acct], timeout=timeout_seconds)
            except TimeoutError:
                connected = False
                error_msg = f"IB probe timed out after {timeout_seconds:.1f}s"
            except Exception as exc:  # pragma: no cover
                connected = False
                error_msg = str(exc)
        stat.ib_connected = connected
        stat.ib_last_error = error_msg
        stat.last_checked_utc = now
        results[acct] = stat.model_dump()

    # include any programs without status (unlikely but safe guard)
    for acct, task in tasks.items():
        if acct in results:
            continue
        try:
            connected, error_msg = await asyncio.wait_for(task, timeout=timeout_seconds)
        except TimeoutError:
            connected = False
            error_msg = f"IB probe timed out after {timeout_seconds:.1f}s"
        results[acct] = {
            "account": acct,
            "executing": programs[acct].is_running
            if hasattr(programs[acct], "is_running")
            else False,
            "ib_connected": connected,
            "ib_last_error": error_msg,
            "last_checked_utc": now,
        }

    return results


@app.get("/accounts", dependencies=[Depends(_require_service_token)])
async def accounts():
    return [a.account_number for a in settings.accounts]


@app.post("/signal", dependencies=[Depends(_require_service_token)])
async def submit_signal(signal: SignalIn):
    if signal.account not in programs:
        raise HTTPException(status_code=404, detail="Unknown account")
    await bus.publish(RealTimeSignal(**signal.model_dump()))
    return {"status": "queued", "account": signal.account, "symbol": signal.symbol}


@app.post("/report/{account}", dependencies=[Depends(_require_service_token)])
async def send_report(account: str):
    if account not in programs:
        raise HTTPException(status_code=404, detail="Unknown account")
    # Ad-hoc daily report trigger
    oauth = programs[account].account_config.get_broker_oauth_params()
    logger.info("Daily report requested for %s", account)

    def _send() -> None:
        with IBInterfacing(
            account_id=account,
            oauth_params=oauth,
            use_global_settings=False,
        ) as ib:
            DailyReport(ib_interface=ib, telegram_bot=None).email_report()

    max_attempts = 3
    base_delay = 5
    max_delay = 60
    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.to_thread(_send)
            return {"status": "sent"}
        except Exception as exc:
            if attempt >= max_attempts:
                logger.exception(
                    "Daily report failed for %s after %s attempts: %s", account, attempt, exc
                )
                raise HTTPException(
                    status_code=500,
                    detail="Daily report failed; check broker logs.",
                ) from exc
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            logger.warning(
                "Daily report attempt %s/%s failed for %s: %s. Retrying in %ss.",
                attempt,
                max_attempts,
                account,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


def _extract_cash_and_nlv(ledger: Any) -> tuple[Dict[str, float], Dict[str, float]]:
    """Best-effort parse IBKR ledger into cash + NLV by currency."""
    cash: Dict[str, float] = {}
    nlv: Dict[str, float] = {}
    if not isinstance(ledger, dict):
        return cash, nlv

    def _num(raw: Any) -> Optional[float]:
        try:
            if raw is None:
                return None
            return float(raw)
        except Exception:
            return None

    cash_keys = ("cashbalance", "cashBalance", "totalcashvalue", "totalCashValue")
    nlv_keys = ("netliquidationvalue", "netLiquidationValue", "netliquidation", "netLiquidation")

    for k, v in ledger.items():
        ccy = str(k or "").upper()
        if len(ccy) != 3:
            continue
        if not isinstance(v, dict):
            continue
        cash_val = None
        for ck in cash_keys:
            if ck in v:
                cash_val = _num(v.get(ck))
                break
        nlv_val = None
        for nk in nlv_keys:
            if nk in v:
                nlv_val = _num(v.get(nk))
                break
        if cash_val is not None:
            cash[ccy] = cash_val
        if nlv_val is not None:
            nlv[ccy] = nlv_val
    return cash, nlv


@app.get(
    "/snapshot/{account}",
    response_model=BrokerAccountSnapshot,
    dependencies=[Depends(_require_service_token)],
)
async def get_account_snapshot(account: str):
    """Return current holdings + cash/NLV by currency (best-effort)."""
    if account not in programs:
        raise HTTPException(status_code=404, detail="Unknown account")
    oauth = programs[account].account_config.get_broker_oauth_params()

    def _fetch() -> BrokerAccountSnapshot:
        with IBInterfacing(
            account_id=account,
            oauth_params=oauth,
            use_global_settings=False,
        ) as ib:
            positions_raw = ib.get_positions()
            ledger = ib.get_account_summary()
            cash_by_ccy, nlv_by_ccy = _extract_cash_and_nlv(ledger)

            out_positions: List[BrokerPositionItem] = []
            for pos in positions_raw:
                if not isinstance(pos, dict):
                    continue
                sym = pos.get("ticker") or pos.get("symbol")
                conid = pos.get("conid") or pos.get("conId") or pos.get("contractId")
                if not sym and conid:
                    try:
                        sym = ib.get_symbol_from_contract_id(str(conid))
                    except Exception:
                        sym = None
                if not sym:
                    continue
                qty = pos.get("position") or pos.get("pos") or pos.get("quantity") or 0
                try:
                    qty_f = float(qty)
                except Exception:
                    continue
                if qty_f == 0:
                    continue
                avg = pos.get("averageCost") or pos.get("avgCost") or pos.get("costBasis")
                avg_f = None
                try:
                    if avg is not None:
                        avg_f = float(avg)
                except Exception:
                    avg_f = None
                ccy = pos.get("currency") or pos.get("currencyCode") or pos.get("ccy")
                ccy_u = str(ccy or "").upper() or None
                out_positions.append(
                    BrokerPositionItem(
                        symbol=str(sym).upper(),
                        quantity=qty_f,
                        avg_cost=avg_f,
                        currency_code=ccy_u,
                        conid=str(conid) if conid is not None else None,
                        raw=pos,
                    )
                )

            return BrokerAccountSnapshot(
                account=account,
                as_of_utc=datetime.now(UTC),
                positions=out_positions,
                cash_by_ccy=cash_by_ccy,
                nlv_by_ccy=nlv_by_ccy,
                ledger_raw=ledger if isinstance(ledger, dict) else {},
            )

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        logger.exception("Failed to fetch broker snapshot for %s: %s", account, exc)
        raise HTTPException(
            status_code=502, detail="Failed to query broker positions/ledger"
        ) from exc


@app.post(
    "/fills/ingest/{account}",
    response_model=IngestFillsResponse,
    dependencies=[Depends(_require_service_token)],
)
async def ingest_fills(account: str, payload: IngestFillsRequest):
    """Ingest recent broker fills into `rankalpha.fact_portfolio_trade` (idempotent)."""
    if account not in programs:
        raise HTTPException(status_code=404, detail="Unknown account")
    oauth = programs[account].account_config.get_broker_oauth_params()

    def _ingest() -> IngestFillsResponse:
        from .order.fills_ingestor import FillsIngestor

        with IBInterfacing(
            account_id=account,
            oauth_params=oauth,
            use_global_settings=False,
        ) as ib:
            inserted = int(
                FillsIngestor(ib, account_number=account).ingest_once(payload.lookback_seconds)
            )
            return IngestFillsResponse(
                account=account,
                inserted=inserted,
                lookback_seconds=int(payload.lookback_seconds),
                as_of_utc=datetime.now(UTC),
            )

    try:
        return await asyncio.to_thread(_ingest)
    except Exception as exc:
        logger.exception("Failed to ingest fills for %s: %s", account, exc)
        raise HTTPException(status_code=502, detail="Failed to query broker fills") from exc


def _parse_year_month(val: Any) -> tuple[Optional[int], Optional[int]]:
    try:
        s = str(val)
        # Extract digits only to handle formats like YYYY-MM-DD or YYYYMMDD
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 6:
            y = int(digits[:4])
            m = int(digits[4:6])
            if 1 <= m <= 12:
                return y, m
    except Exception:
        pass
    return None, None


def _secdef_search_futures(ib: IBInterfacing, symbols: List[str]) -> List[Dict[str, Any]]:
    """Search FUT contracts via secdef when trsrv/futures returns nothing.

    Returns a list of dicts with keys similar to trsrv/futures entries, including
    'localSymbol', 'expiry', 'conid'. Filters to GLOBEX when possible.
    """
    results: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for sym in symbols:
        try:
            resp = ib.client.get("iserver/secdef/search", params={"symbol": sym})
            data = resp.data if hasattr(resp, "data") else resp
        except Exception as e:
            logger.debug("secdef/search(%s) failed: %s", sym, e)
            continue
        items = data if isinstance(data, list) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            st = str(it.get("secType") or it.get("sectype") or it.get("type") or "").upper()
            if st != "FUT":
                continue
            ex = str(
                it.get("listingExchange") or it.get("exchange") or it.get("primaryExchange") or ""
            ).upper()
            # Prefer GLOBEX, but if empty accept and filter later
            expiry = (
                it.get("expiry")
                or it.get("lastTradingDate")
                or it.get("maturity")
                or it.get("monthYear")
            )
            y, m = _parse_year_month(expiry)
            if y is None or m is None:
                continue
            conid = None
            try:
                conid = int(it.get("conid")) if it.get("conid") is not None else None
            except Exception:
                conid = None
            local = str(
                it.get("localSymbol") or it.get("local_symbol") or it.get("symbol") or ""
            ).strip()
            if conid is not None and conid in seen:
                continue
            if ex and ex not in ("GLOBEX", "CME", "CME GLOBEX"):
                # Keep only CME/GLOBEX venues
                continue
            results.append(
                {
                    "localSymbol": local,
                    "expiry": str(expiry) if expiry is not None else None,
                    "conid": conid,
                }
            )
            if conid is not None:
                seen.add(conid)
    return results


_FUT_MONTH_CODES = {
    1: "F",
    2: "G",
    3: "H",
    4: "J",
    5: "K",
    6: "M",
    7: "N",
    8: "Q",
    9: "U",
    10: "V",
    11: "X",
    12: "Z",
}


def _generate_local_symbol_guesses(root: str, horizon_months: int = 24) -> List[str]:
    from datetime import date

    today = date.today()
    root = root.upper()
    guesses: List[str] = []
    for i in range(max(1, horizon_months)):
        y = today.year + (today.month - 1 + i) // 12
        m = (today.month - 1 + i) % 12 + 1
        code = _FUT_MONTH_CODES[m]
        yy1 = str(y)[-1]
        yy2 = str(y)[-2:]
        guesses.append(f"{root}{code}{yy1}")
        guesses.append(f"{root}{code}{yy2}")
    # Deduplicate keep order
    seen: set[str] = set()
    out: List[str] = []
    for s in guesses:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _secdef_search_by_locals(ib: IBInterfacing, root: str) -> List[Dict[str, Any]]:
    candidates = _generate_local_symbol_guesses(root, 24)
    results: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for sym in candidates:
        try:
            resp = ib.client.get("iserver/secdef/search", params={"symbol": sym})
            data = resp.data if hasattr(resp, "data") else resp
        except Exception as e:
            logger.debug("secdef/search(local=%s) failed: %s", sym, e)
            continue
        items = data if isinstance(data, list) else []
        for it in items:
            if not isinstance(it, dict):
                continue
            st = str(it.get("secType") or it.get("sectype") or it.get("type") or "").upper()
            if st != "FUT":
                continue
            ex = str(
                it.get("listingExchange") or it.get("exchange") or it.get("primaryExchange") or ""
            ).upper()
            if ex and ex not in ("GLOBEX", "CME", "CME GLOBEX"):
                continue
            expiry = (
                it.get("expiry")
                or it.get("lastTradingDate")
                or it.get("maturity")
                or it.get("monthYear")
            )
            y, m = _parse_year_month(expiry)
            if y is None or m is None:
                continue
            conid = None
            try:
                conid = int(it.get("conid")) if it.get("conid") is not None else None
            except Exception:
                conid = None
            if conid is not None and conid in seen:
                continue
            local = str(
                it.get("localSymbol") or it.get("local_symbol") or it.get("symbol") or sym
            ).strip()
            results.append(
                {
                    "localSymbol": local,
                    "expiry": str(expiry) if expiry is not None else None,
                    "conid": conid,
                }
            )
            if conid is not None:
                seen.add(conid)
    return results


def _list_sofr_contracts(
    ib: IBInterfacing, root: str, limit: int
) -> Tuple[str, List[Dict[str, Any]]]:
    """Return normalized SOFR futures contracts (year/month/local/conid) sorted front-to-back."""
    tried: list[tuple[str, int]] = []
    contracts: list[Dict[str, Any]] = []
    base = root.upper()
    # Normalize to ICE/CME directory names and stop searching other roots.
    if base in ("SR3", "SOFR"):
        base = "SOFR3"
    if base == "SR1":
        base = "SOFR1"
    ordered_syms: List[str] = [base]
    for sym in ordered_syms:
        try:
            res = ib.search_contracts(sym, sec_type="FUT", exchange="GLOBEX")
            cnt = len(res) if isinstance(res, list) else 0
            tried.append((sym, cnt))
            if cnt > 0:
                contracts = res  # type: ignore[assignment]
                root = sym  # normalize to the symbol that worked
                break
        except Exception as e:
            tried.append((sym, -1))
            logger.debug("[broker:/rates/sofr-futures] search_contracts(%s) failed: %s", sym, e)
            continue
    logger.info(
        "[broker:/rates/sofr-futures] trsrv/futures attempts: %s",
        ", ".join(f"{sym}:{cnt}" for sym, cnt in tried) or "(none)",
    )

    # Fallback: use secdef search when directory returns nothing
    if not contracts:
        try:
            # Only use the normalized symbol for secdef fallback
            search_list = [ordered_syms[0]]
            contracts = _secdef_search_futures(ib, search_list)
            logger.info(
                "[broker:/rates/sofr-futures] secdef fallback returned %d candidates",
                len(contracts) if isinstance(contracts, list) else 0,
            )
        except Exception as e:
            logger.debug("[broker:/rates/sofr-futures] secdef fallback error: %s", e)
    # Second fallback: guess localSymbols and search via secdef
    if not contracts:
        try:
            # Use SR3/SR1 style roots for local symbols corresponding to SOFR3/SOFR1
            local_roots = (
                ["SR3"]
                if ordered_syms[0] == "SOFR3"
                else ["SR1"]
                if ordered_syms[0] == "SOFR1"
                else ["SR3", "SR1"]
            )
            acc: List[Dict[str, Any]] = []
            for lr in local_roots:
                acc.extend(_secdef_search_by_locals(ib, lr))
            contracts = acc
            logger.info(
                "[broker:/rates/sofr-futures] localSymbol fallback returned %d candidates",
                len(contracts) if isinstance(contracts, list) else 0,
            )
        except Exception as e:
            logger.debug("[broker:/rates/sofr-futures] localSymbol fallback error: %s", e)

    # Normalize entries and keep those with year/month data
    normalized: list[dict[str, Any]] = []

    def _normalize_entry(entry: Dict[str, Any]) -> None:
        local = str(
            entry.get("localSymbol") or entry.get("local_symbol") or entry.get("symbol") or ""
        ).strip()
        expiry = (
            entry.get("expiry")
            or entry.get("expirationDate")
            or entry.get("lastTradingDate")
            or entry.get("ltd")
            or entry.get("maturity")
            or entry.get("monthYear")
        )
        year, month = _parse_year_month(expiry)
        conid = None
        try:
            conid = (
                int(entry.get("conid") or entry.get("conId"))
                if (entry.get("conid") is not None or entry.get("conId") is not None)
                else None
            )
        except Exception:
            conid = None
        if not local or year is None or month is None:
            logger.debug(
                "[broker:/rates/sofr-futures] skip contract: local=%r expiry=%r parsed=(%r,%r) conid=%r",
                local,
                expiry,
                year,
                month,
                conid,
            )
            return
        logger.debug(
            "[broker:/rates/sofr-futures] normalized: local=%s expiry=%s y=%s m=%s conid=%s",
            local,
            expiry,
            year,
            month,
            conid,
        )
        normalized.append(
            {
                "local_symbol": local,
                "expiry": str(expiry) if expiry is not None else None,
                "year": year,
                "month": month,
                "conid": conid,
            }
        )

    for c in contracts or []:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("contracts"), list) and c.get("contracts"):
            for cc in c["contracts"]:
                if isinstance(cc, dict):
                    _normalize_entry(cc)
        else:
            _normalize_entry(c)

    if not normalized:
        # Log keys of the first few raw entries to help diagnose shape mismatches
        sample_keys = []
        for c in (contracts or [])[:3]:
            if isinstance(c, dict):
                sample_keys.append(sorted(list(c.keys()))[:12])
        logger.info(
            "[broker:/rates/sofr-futures] no normalized entries; sample keys: %s", sample_keys
        )

    # Sort by year, month and take front N
    normalized.sort(key=lambda x: (x["year"], x["month"]))
    if limit and limit > 0:
        normalized = normalized[:limit]
    logger.info(
        "[broker:/rates/sofr-futures] selected %d front contracts: %s",
        len(normalized),
        ", ".join(f"{e['year']}-{e['month']:02d}(conid={e.get('conid')})" for e in normalized)
        if normalized
        else "(none)",
    )
    return root, normalized


def _fetch_sofr_futures_with_program(
    prog: ExecutionProgram, root: str, limit: int
) -> Dict[str, Any]:
    """Blocking IBKR calls to fetch a compact SOFR futures chain.

    Runs in a worker thread via asyncio.to_thread from the async route.
    """
    ib = prog.market_ib or prog.broker_ib
    if ib is None:
        prog.connect()
        ib = prog.market_ib or prog.broker_ib
    if ib is None:
        raise RuntimeError("IBKR session not available")

    # Fetch the listed contracts for the root (GLOBEX) with fallbacks
    root, normalized = _list_sofr_contracts(ib, root, limit)

    # Fetch quotes for each contract (best‑effort)
    items: list[Dict[str, Any]] = []
    for entry in normalized:
        last = None
        settle = None
        try:
            logger.debug(
                "[broker:/rates/sofr-futures] snapshot y=%s m=%s local=%s conid=%s",
                entry.get("year"),
                entry.get("month"),
                entry.get("local_symbol"),
                entry.get("conid"),
            )
            quote = (
                ib.get_market_data(conid=entry.get("conid"), sec_type="FUT")
                if entry.get("conid")
                else {}
            )
            if isinstance(quote, dict):
                # Field 31 = last, 7741 = close/settle
                raw_last = quote.get("last") or quote.get("31")
                raw_close = quote.get("close") or quote.get("7741")
                try:
                    last = float(raw_last) if raw_last is not None else None
                except (TypeError, ValueError):
                    last = None
                try:
                    settle = float(raw_close) if raw_close is not None else None
                except (TypeError, ValueError):
                    settle = None
        except Exception as exc:
            logger.warning(
                "Snapshot failed for %s (%s): %s",
                entry.get("local_symbol"),
                entry.get("conid"),
                exc,
            )

        items.append(
            {
                "root": root.upper(),
                "local_symbol": entry["local_symbol"],
                "conid": entry.get("conid"),
                "year": entry["year"],
                "month": entry["month"],
                "expiry": entry.get("expiry"),
                "last": last,
                "settle": settle,
            }
        )

    return {
        "account": prog.account_config.account_number,
        "root": root.upper(),
        "exchange": "GLOBEX",
        "items": items,
    }


@app.get(
    "/rates/sofr-futures",
    response_model=SofrFuturesResponse,
    dependencies=[Depends(_require_service_token)],
)
async def sofr_futures(
    root: str = "SR3",  # 3M SOFR futures; SR1 = 1M SOFR futures
    limit: int = 8,
    account: Optional[str] = None,
):
    """Return a compact chain of SOFR futures with last/settle prices.

    - root: SR3 (3M) or SR1 (1M)
    - limit: number of contracts from the front to include
    """
    target_account, prog = _resolve_account_program(account)

    logger.info(
        "[broker:/rates/sofr-futures] account=%s root=%s limit=%s", target_account, root, limit
    )
    try:
        payload = await asyncio.to_thread(_fetch_sofr_futures_with_program, prog, root, int(limit))
    except Exception as exc:
        logger.exception("/rates/sofr-futures failed for %s: %s", root, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch SOFR futures") from exc
    # Pydantic model validation + response
    return SofrFuturesResponse(**payload)


@app.get(
    "/rates/sofr-futures/history",
    response_model=SofrFuturesHistoryResponse,
    dependencies=[Depends(_require_service_token)],
)
async def sofr_futures_history(
    root: str = "SR3",
    years: int = 2,
    limit: int = 16,
    account: Optional[str] = None,
):
    """Return daily historical bars (1d) for front SOFR futures contracts."""
    target_account, prog = _resolve_account_program(account)

    if years < 1:
        years = 1
    if years > 2:
        years = 2  # IBKR limit ~2y

    try:
        payload = await asyncio.to_thread(
            _fetch_sofr_history_with_program, prog, root, years, int(limit)
        )
    except Exception as exc:
        logger.exception("/rates/sofr-futures/history failed for %s: %s", root, exc)
        raise HTTPException(status_code=502, detail="Failed to fetch SOFR futures history") from exc
    return SofrFuturesHistoryResponse(**payload)


def _parse_bar_date(val: Any) -> Optional[date]:
    try:
        if isinstance(val, (int, float)):
            # IBKR returns epoch milliseconds
            return datetime.fromtimestamp(float(val) / 1000.0, tz=UTC).date()
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val).date()
            except Exception:
                return datetime.fromtimestamp(float(val) / 1000.0, tz=UTC).date()
    except Exception:
        return None
    return None


def _fetch_sofr_history_with_program(
    prog: ExecutionProgram, root: str, years: int, limit: int
) -> Dict[str, Any]:
    """Blocking IBKR calls to fetch EOD historical bars for SOFR futures."""
    ib = prog.market_ib or prog.broker_ib
    if ib is None:
        prog.connect()
        ib = prog.market_ib or prog.broker_ib
    if ib is None:
        raise RuntimeError("IBKR session not available")

    _, normalized = _list_sofr_contracts(ib, root, limit)
    period = f"{int(years)} y"
    history_items: list[Dict[str, Any]] = []

    for entry in normalized:
        conid = entry.get("conid")
        if not conid:
            continue
        try:
            hist = ib.get_historical_data(
                conid=conid,
                period=period,
                bar="1 day",
                outside_rth=False,
                sec_type="FUT",
                exchange="GLOBEX",
            )
        except Exception as exc:
            # One-shot retry on bridge errors
            if (
                "no bridge" in str(exc).lower()
                or "initialize_brokerage_session" in str(exc).lower()
            ):
                try:
                    ib.client.initialize_brokerage_session()
                    ib._ensure_account_selection()  # type: ignore[attr-defined]
                    hist = ib.get_historical_data(
                        conid=conid,
                        period=period,
                        bar="1 day",
                        outside_rth=False,
                        sec_type="FUT",
                        exchange="GLOBEX",
                    )
                except Exception as exc2:  # pragma: no cover - best effort
                    raise RuntimeError(
                        f"Historical data retry failed for conid {conid}: {exc2}"
                    ) from exc2
            else:
                raise RuntimeError(f"Historical data failed for conid {conid}: {exc}") from exc

        bars_raw = hist.get("data") if isinstance(hist, dict) else hist
        bars: list[Dict[str, Any]] = []
        for b in bars_raw or []:
            if not isinstance(b, dict):
                continue
            as_of = _parse_bar_date(b.get("t"))
            if as_of is None:
                continue
            close = _coerce_float(b.get("c"))
            open_px = _coerce_float(b.get("o"))
            high = _coerce_float(b.get("h"))
            low = _coerce_float(b.get("l"))
            volume = _coerce_float(b.get("v"))
            bars.append(
                {
                    "as_of_date": as_of,
                    "close": close,
                    "open": open_px,
                    "high": high,
                    "low": low,
                    "volume": volume,
                    "raw": dict(b),
                }
            )
        if not bars:
            continue
        bars.sort(key=lambda x: x["as_of_date"])
        history_items.append(
            {
                "root": root.upper(),
                "local_symbol": entry.get("local_symbol"),
                "conid": conid,
                "year": entry.get("year"),
                "month": entry.get("month"),
                "expiry": entry.get("expiry"),
                "bars": bars,
            }
        )

    if not history_items:
        raise RuntimeError("No historical bars returned for SOFR futures")

    return {
        "account": prog.account_config.account_number,
        "root": root.upper(),
        "exchange": "GLOBEX",
        "period": period,
        "items": history_items,
    }


# --------------------------- Helpers ----------------------------------
def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)  # handles numeric strings
    except (TypeError, ValueError):
        return None


def _fetch_snapshot_with_program(
    prog: ExecutionProgram, symbol: str, exchange: Optional[str]
) -> Dict[str, Any]:
    # Prefer the long-lived market IB from the per-account program to avoid
    # tearing down the bridge between calls.
    cache_key = (prog.account_config.account_number, symbol.upper(), exchange or "")
    cached = _price_cache.get(cache_key)
    if isinstance(cached, dict):
        return dict(cached)
    if prog.market_ib is None:
        # If the supervised runner hasn't connected yet, connect now
        logger.info("[broker:/price] program has no market_ib; attempting connect()")
        prog.connect()
    ib = prog.market_ib or prog.broker_ib
    if ib is None:
        # Fallback: last resort ephemeral client (should be rare)
        oauth = prog.account_config.get_market_oauth_params()
        logger.warning(
            "[broker:/price] no persistent IB; using ephemeral client for %s (exch=%s)",
            symbol,
            exchange or "(none)",
        )
        with IBInterfacing(
            account_id=prog.account_config.account_number,
            oauth_params=oauth,
            use_global_settings=False,
        ) as tmp:
            quote = tmp.get_market_data(symbol=symbol, exchange=exchange)
            if isinstance(quote, dict):
                _price_cache.set(cache_key, dict(quote))
            return quote
    logger.info(
        "[broker:/price] using %s to fetch %s (exch=%s)",
        "market_ib" if prog.market_ib is ib else "broker_ib",
        symbol,
        exchange or "(none)",
    )
    try:
        quote = ib.get_market_data(symbol=symbol, exchange=exchange)
        if isinstance(quote, dict):
            _price_cache.set(cache_key, dict(quote))
        return quote
    except Exception as exc:
        # One-shot reconnect on 'no bridge'
        msg = str(exc).lower()
        if "no bridge" in msg or "initialize_brokerage_session" in msg:
            try:
                ib.ping()
                quote = ib.get_market_data(symbol=symbol, exchange=exchange)
                if isinstance(quote, dict):
                    _price_cache.set(cache_key, dict(quote))
                return quote
            except Exception as inner_exc:
                exc = inner_exc

        # During business hours, attempt a full reconnect before failing.
        if not is_broker_sentry_quiet_hours() and is_ibkr_maintenance_error(exc):
            logger.warning(
                "[broker:/price] IBKR session dropped; reconnecting before retry (account=%s).",
                prog.account_config.account_number,
            )
            try:
                for conn in (prog.market_ib, prog.broker_ib):
                    try:
                        if conn is not None:
                            conn.close()
                    except Exception:
                        pass
                prog.connect()
                retry_ib = prog.market_ib or prog.broker_ib
                if retry_ib is not None:
                    quote = retry_ib.get_market_data(symbol=symbol, exchange=exchange)
                    if isinstance(quote, dict):
                        _price_cache.set(cache_key, dict(quote))
                    return quote
            except Exception as retry_exc:
                logger.warning(
                    "[broker:/price] IBKR reconnect retry failed (account=%s): %s",
                    prog.account_config.account_number,
                    retry_exc,
                )
        raise


def _fetch_prev_close_with_program(
    prog: ExecutionProgram,
    symbol: str,
    exchange: Optional[str],
    *,
    sec_type: str = "STK",
    currency: Optional[str] = None,
) -> Tuple[Optional[float], Optional[str], Dict[str, Any], str]:
    """Return (prev_close, as_of, raw, source).

    Prefers IBKR daily bars (yesterday's close), falls back to snapshot 'prior close'.
    """
    cache_key = (
        prog.account_config.account_number,
        symbol.upper(),
        exchange or "",
        sec_type,
        currency or "",
    )

    cached = _prev_close_cache.get(cache_key)
    if cached:
        return cached

    def _cache_and_return(value: Tuple[Optional[float], Optional[str], Dict[str, Any], str]):
        _prev_close_cache.set(cache_key, value)
        return value

    # Prefer the long-lived market IB from the per-account program.
    if prog.market_ib is None:
        logger.info("[broker:/price/prev-close] program has no market_ib; attempting connect()")
        prog.connect()
    ib = prog.market_ib or prog.broker_ib

    if ib is None:
        # Fallback: ephemeral client with market OAuth (or broker OAuth)
        oauth = prog.account_config.get_market_oauth_params()
        logger.warning(
            "[broker:/price/prev-close] no persistent IB; using ephemeral client for %s (exch=%s)",
            symbol,
            exchange or "(none)",
        )
        with IBInterfacing(
            account_id=prog.account_config.account_number,
            oauth_params=oauth,
            use_global_settings=False,
        ) as tmp:
            bar = tmp.get_yesterday_bar(
                symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
            )
            if bar and (bar.get("close") is not None or bar.get("c") is not None):
                prev = bar.get("close") or bar.get("c")
                as_of = str(bar.get("date") or bar.get("t") or "")
                try:
                    return _cache_and_return((float(prev), as_of, bar, "history"))
                except (TypeError, ValueError):
                    pass
            # Fallback: snapshot prior close
            quote = tmp.get_market_data(
                symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
            )
            prev = quote.get("86") or quote.get("close")
            try:
                return _cache_and_return(
                    (float(prev) if prev is not None else None, None, quote, "snapshot")
                )
            except (TypeError, ValueError):
                return _cache_and_return((None, None, quote, "snapshot"))

    # Use persistent client
    try:
        bar = ib.get_yesterday_bar(
            symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
        )
    except Exception as exc:
        if "no bridge" in str(exc).lower() or "initialize_brokerage_session" in str(exc).lower():
            ib.ping()
            bar = ib.get_yesterday_bar(
                symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
            )
        else:
            raise
    if bar and (bar.get("close") is not None or bar.get("c") is not None):
        prev = bar.get("close") or bar.get("c")
        as_of = str(bar.get("date") or bar.get("t") or "")
        try:
            return _cache_and_return((float(prev), as_of, bar, "history"))
        except (TypeError, ValueError):
            pass

    # Fallback to snapshot
    try:
        quote = ib.get_market_data(
            symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
        )
    except Exception as exc:
        if "no bridge" in str(exc).lower() or "initialize_brokerage_session" in str(exc).lower():
            ib.ping()
            quote = ib.get_market_data(
                symbol=symbol, exchange=exchange, sec_type=sec_type, currency=currency
            )
        else:
            raise
    prev = quote.get("86") or quote.get("close")
    try:
        return _cache_and_return(
            (float(prev) if prev is not None else None, None, quote, "snapshot")
        )
    except (TypeError, ValueError):
        return _cache_and_return((None, None, quote, "snapshot"))


def _probe_ib_connection(prog: ExecutionProgram) -> Tuple[bool, Optional[str]]:
    try:
        ib = prog.market_ib or prog.broker_ib
        if ib is None:
            return False, "IB interface not yet initialized"
        ib.ping()
        return True, None
    except Exception as exc:  # pragma: no cover - diagnostic path
        return False, str(exc)


# --------------------------- Price Endpoint ---------------------------
@app.get(
    "/price/{symbol}",
    response_model=PriceSnapshot,
    dependencies=[Depends(_require_service_token)],
)
async def snapshot_price(
    symbol: str,
    account: Optional[str] = None,
    exchange: Optional[str] = None,
    sec_type: Optional[str] = None,
    currency: Optional[str] = None,
):
    logger.info(
        "[broker:/price] request symbol=%s account=%s exchange=%s",
        symbol,
        account or "(default)",
        exchange or "(none)",
    )
    target_account, prog = _resolve_account_program(account)
    try:
        # Allow FUT/FX snapshots via sec_type/currency hints
        if sec_type and sec_type.upper() in ("FUT", "FUTURE", "FUTURES", "FX", "FOREX", "CASH"):
            prev_close_result = await asyncio.to_thread(
                _fetch_prev_close_with_program,  # reuse path to pass sec_type
                prog,
                symbol,
                exchange,
                sec_type=sec_type.upper(),
                currency=currency,
            )
            if isinstance(prev_close_result, tuple):
                _, _, raw_quote, _ = prev_close_result
                quote = raw_quote if isinstance(raw_quote, dict) else {}
            else:
                quote = prev_close_result if isinstance(prev_close_result, dict) else {}
            if not quote:
                # Fallback only when no raw snapshot payload was returned.
                quote = await asyncio.to_thread(
                    lambda: (prog.market_ib or prog.broker_ib).get_market_data(
                        symbol=symbol,
                        exchange=exchange,
                        sec_type=sec_type.upper(),
                        currency=currency,
                    )  # type: ignore
                )
        else:
            quote = await asyncio.to_thread(_fetch_snapshot_with_program, prog, symbol, exchange)
        # Log a concise view of the raw quote
        if isinstance(quote, dict):
            keys = list(quote.keys())[:12]
            logger.info(
                "[broker:/price] fetched quote for %s via %s keys=%s",
                symbol,
                "market_ib" if prog.market_ib is not None else "broker_ib",
                keys,
            )
    except Exception as exc:  # IBKR client failure
        message = str(exc)
        is_no_contracts = isinstance(exc, RuntimeError) and "no contracts" in message.lower()
        if is_no_contracts:
            # Expected for delisted tickers; audit via metrics/logs but don't page Sentry.
            record_price_snapshot_error(account=target_account, exc=exc, suppressed=True)
            logger.info(
                "Snapshot quote missing contract for %s (account=%s): %s",
                symbol,
                target_account,
                exc,
            )
            return JSONResponse(status_code=404, content={"detail": "Symbol not found"})

        quiet_hours = is_broker_sentry_quiet_hours()
        suppress = quiet_hours
        record_price_snapshot_error(account=target_account, exc=exc, suppressed=suppress)
        if suppress:
            logger.warning(
                "Snapshot quote failed during quiet hours for %s (account=%s): %s",
                symbol,
                target_account,
                exc,
            )
            return JSONResponse(
                status_code=502, content={"detail": "Snapshot price request failed"}
            )

        logger.exception(
            "Snapshot quote failed for %s (account=%s): %s",
            symbol,
            target_account,
            exc,
        )
        raise HTTPException(status_code=502, detail="Snapshot price request failed") from exc

    if not quote:
        raise HTTPException(status_code=502, detail="No market data returned")

    raw = dict(quote)
    bid = _coerce_float(raw.get("bid") or raw.get("55"))
    ask = _coerce_float(raw.get("ask") or raw.get("84"))
    last = _coerce_float(raw.get("last") or raw.get("31"))
    close = _coerce_float(raw.get("close") or raw.get("86"))
    change_pct = _coerce_float(raw.get("change_pct") or raw.get("83"))

    res = PriceSnapshot(
        account=target_account,
        symbol=symbol.upper(),
        bid=bid,
        ask=ask,
        last=last,
        close=close,
        change_pct=change_pct,
        raw=raw,
    )
    logger.info(
        "[broker:/price] result symbol=%s bid=%s ask=%s last=%s close=%s change_pct=%s",
        res.symbol,
        res.bid,
        res.ask,
        res.last,
        res.close,
        res.change_pct,
    )
    return res


def _normalize_sec_type(s: Optional[str]) -> str:
    if not s:
        return "STK"
    s_up = s.upper()
    if s_up in ("STK", "STOCK"):
        return "STK"
    if s_up in ("FUT", "FUTURE", "FUTURES"):
        return "FUT"
    if s_up in ("FX", "FOREX", "CASH"):
        return "CASH"
    return s_up


@app.get(
    "/price/prev-close/{symbol}",
    response_model=PreviousClose,
    dependencies=[Depends(_require_service_token)],
)
async def previous_close(
    symbol: str,
    account: Optional[str] = None,
    exchange: Optional[str] = None,
    sec_type: Optional[str] = None,
    currency: Optional[str] = None,
):
    logger.info(
        "[broker:/price/prev-close] request symbol=%s account=%s exchange=%s",
        symbol,
        account or "(default)",
        exchange or "(none)",
    )
    target_account, prog = _resolve_account_program(account)
    try:
        prev_close, as_of, raw, source = await asyncio.to_thread(
            _fetch_prev_close_with_program,
            prog,
            symbol,
            exchange,
            sec_type=_normalize_sec_type(sec_type),
            currency=currency,
        )
        logger.info(
            "[broker:/price/prev-close] %s → prev_close=%s source=%s",
            symbol,
            prev_close,
            source,
        )
    except Exception as exc:
        message = str(exc)
        is_no_contracts = isinstance(exc, RuntimeError) and "no contracts" in message.lower()
        suppress = is_no_contracts or _is_prev_close_sentry_quiet_hours()
        record_prev_close_error(account=target_account, exc=exc, suppressed=suppress)
        if suppress:
            level = logger.info if is_no_contracts else logger.warning
            level(
                "Prev-close fetch failed%s for %s (account=%s): %s",
                " (no contracts)" if is_no_contracts else " during quiet hours",
                symbol,
                target_account,
                exc,
            )
            return JSONResponse(
                status_code=502, content={"detail": "Previous close request failed"}
            )

        logger.exception(
            "Prev-close fetch failed for %s (account=%s): %s", symbol, target_account, exc
        )
        raise HTTPException(status_code=502, detail="Previous close request failed") from exc

    if prev_close is None:
        raise HTTPException(status_code=502, detail="No previous close available")

    return PreviousClose(
        account=target_account,
        symbol=symbol.upper(),
        previous_close=prev_close,
        as_of=as_of,
        source=source,
        raw=raw if isinstance(raw, dict) else {},
    )
