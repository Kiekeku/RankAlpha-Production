import json
import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Type, Union
from urllib.parse import urlsplit, urlunsplit

from openai import AsyncOpenAI

from apps.common.src.ai.budget import Budget, BudgetLedger, get_redis_counter_from_env
from apps.common.src.ai.costing import preflight_estimate_cost, reconcile_cost
from apps.common.src.ai.notifications import BudgetAlertEvent

try:
    import httpx  # used for direct PDF downloads
except Exception:  # pragma: no cover - optional
    httpx = None  # type: ignore

from mcp.types import CallToolRequest, CallToolRequestParams, PromptMessage
from mcp_agent.logging.logger import get_logger
from mcp_agent.workflows.llm.augmented_llm import (
    AugmentedLLM,
    MessageParamT,
    ModelT,
    RequestParams,
)

# Optional Redis support for cross-process caching
try:  # pragma: no cover - optional dependency
    from redis.asyncio import Redis as AsyncRedis  # type: ignore
except Exception:  # pragma: no cover - fallback when redis is unavailable
    AsyncRedis = None  # type: ignore


def _budget_alert_log_only(event: BudgetAlertEvent) -> None:
    """Suppress direct email alerts; rely on Prometheus/Grafana alerting instead."""
    try:
        logging.getLogger(__name__).warning(
            "AI budget threshold crossed (Grafana alerting)",
            extra={
                "service": event.service,
                "metric": event.metric,
                "threshold": event.threshold,
                "percent": event.percent,
                "used": event.used,
                "limit": event.limit,
                "date_utc": event.date_utc,
            },
        )
    except Exception:
        return


def _extract_json_obj(text: str) -> Optional[dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback: try to extract the largest {...} block by trimming to first '{' and last '}'
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = text[first : last + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # As a last attempt, the first simple {...} match
    m = re.search(r"\{[\s\S]*?\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


MessageLike = Union[
    str,
    MessageParamT,
    PromptMessage,
    List[Union[str, MessageParamT, PromptMessage]],
]


def _extract_tool_call_fields(call: Any) -> tuple[Optional[str], Optional[str], Any]:
    """Return (call_id, name, arguments) for different tool call payload shapes."""

    call_id = getattr(call, "call_id", None)
    name = getattr(call, "name", None)
    arguments = getattr(call, "arguments", None)

    if isinstance(call, dict):
        call_id = call.get("call_id") or call.get("id") or call_id
        function_blob = call.get("function")
        if isinstance(function_blob, dict):
            name = function_blob.get("name") or call.get("name") or name
            if function_blob.get("arguments") is not None:
                arguments = function_blob.get("arguments")
            elif arguments is None and call.get("arguments") is not None:
                arguments = call.get("arguments")
        else:
            name = call.get("name") or name
            if call.get("arguments") is not None:
                arguments = call.get("arguments")

    return call_id, name, arguments


class Gpt5ResponsesPlannerLLM(AugmentedLLM[MessageParamT, str]):
    """Planner LLM using the OpenAI Responses API for GPT‑5 family.

    - Sends a single developer message (instruction) and a user message.
    - Avoids system messages entirely.
    - Implements simple JSON parsing for structured outputs.
    """

    provider: str | None = "OpenAI"
    logger = get_logger(__name__)

    # ---- Global tool usage counters (per-process) ----
    # Counts by tool name across all agents
    _TOOL_COUNTS: Dict[str, int] = {}
    # Counts of tool errors (tool returned isError or raised)
    _TOOL_ERROR_COUNTS: Dict[str, int] = {}
    # Nested counts by agent -> tool name
    _AGENT_TOOL_COUNTS: Dict[str, Dict[str, int]] = {}
    _AGENT_TOOL_ERROR_COUNTS: Dict[str, Dict[str, int]] = {}
    # Last-emitted values (for Prometheus delta export without resetting totals)
    _TOOL_COUNTS_EMITTED: Dict[str, int] = {}
    _TOOL_ERROR_COUNTS_EMITTED: Dict[str, int] = {}
    # Price-source metrics across the process
    _PRICE_METRICS: Dict[str, int] = {
        "api_attempts": 0,
        "api_success": 0,
        "api_fail": 0,
        "yf_attempts": 0,
        "yf_success": 0,
        "yf_fail": 0,
    }
    # Remember working/failed API bases within the process
    _API_BASE_WORKING: Optional[str] = None
    _API_BASE_FAILED: set[str] = set()

    @classmethod
    def record_tool_use(cls, agent_name: str, tool_name: str) -> None:
        try:
            key = str(tool_name or "unknown").strip()
            cls._TOOL_COUNTS[key] = int(cls._TOOL_COUNTS.get(key, 0)) + 1
            a = str(agent_name or "unknown").strip()
            by_agent = cls._AGENT_TOOL_COUNTS.get(a) or {}
            by_agent[key] = int(by_agent.get(key, 0)) + 1
            cls._AGENT_TOOL_COUNTS[a] = by_agent
        except Exception:
            pass

    @classmethod
    def record_tool_error(cls, agent_name: str, tool_name: str) -> None:
        try:
            key = str(tool_name or "unknown").strip()
            cls._TOOL_ERROR_COUNTS[key] = int(cls._TOOL_ERROR_COUNTS.get(key, 0)) + 1
            a = str(agent_name or "unknown").strip()
            by_agent = cls._AGENT_TOOL_ERROR_COUNTS.get(a) or {}
            by_agent[key] = int(by_agent.get(key, 0)) + 1
            cls._AGENT_TOOL_ERROR_COUNTS[a] = by_agent
        except Exception:
            pass

    @classmethod
    def get_tool_usage_snapshot(cls, reset: bool = False) -> dict:
        """Return a snapshot dict of tool usage counts; optionally reset counters."""
        snapshot = {
            "by_tool": dict(cls._TOOL_COUNTS),
            "by_tool_errors": dict(cls._TOOL_ERROR_COUNTS),
            "by_agent": {k: dict(v) for k, v in cls._AGENT_TOOL_COUNTS.items()},
            "by_agent_errors": {k: dict(v) for k, v in cls._AGENT_TOOL_ERROR_COUNTS.items()},
        }
        if reset:
            try:
                cls._TOOL_COUNTS.clear()
                cls._TOOL_ERROR_COUNTS.clear()
                cls._AGENT_TOOL_COUNTS.clear()
                cls._AGENT_TOOL_ERROR_COUNTS.clear()
            except Exception:
                pass
        return snapshot

    @classmethod
    def consume_tool_usage_delta(cls) -> dict:
        """Return deltas since the last consume, without resetting totals."""
        cur = dict(cls._TOOL_COUNTS)
        cur_err = dict(cls._TOOL_ERROR_COUNTS)
        delta: Dict[str, int] = {}
        delta_err: Dict[str, int] = {}
        for name, cnt in cur.items():
            prev = int(cls._TOOL_COUNTS_EMITTED.get(name, 0) or 0)
            d = int(cnt or 0) - prev
            if d:
                delta[name] = d
        for name, cnt in cur_err.items():
            prev = int(cls._TOOL_ERROR_COUNTS_EMITTED.get(name, 0) or 0)
            d = int(cnt or 0) - prev
            if d:
                delta_err[name] = d
        cls._TOOL_COUNTS_EMITTED = cur
        cls._TOOL_ERROR_COUNTS_EMITTED = cur_err
        return {"by_tool": delta, "by_tool_errors": delta_err}

    @classmethod
    def log_tool_usage_summary(
        cls, logger: logging.Logger | None = None, reset: bool = True
    ) -> None:
        try:
            snap = cls.get_tool_usage_snapshot(reset=False)
            if not logger:
                logger = logging.getLogger("sentiment.prompts")
            # Summaries sorted desc
            by_tool = sorted(snap.get("by_tool", {}).items(), key=lambda x: (-int(x[1] or 0), x[0]))
            by_tool_err = sorted(
                snap.get("by_tool_errors", {}).items(), key=lambda x: (-int(x[1] or 0), x[0])
            )
            lines = ["TOOL USAGE SUMMARY (this process):"]
            if by_tool:
                lines.append("- By tool:")
                for name, cnt in by_tool:
                    lines.append(f"  • {name}: {cnt}")
            if by_tool_err:
                lines.append("- By tool errors:")
                for name, cnt in by_tool_err:
                    lines.append(f"  • {name}: {cnt}")
            by_agent = snap.get("by_agent", {}) or {}
            if by_agent:
                lines.append("- By agent:")
                for agent, d in sorted(by_agent.items()):
                    parts = ", ".join(
                        f"{n}:{c}"
                        for n, c in sorted(d.items(), key=lambda x: (-int(x[1] or 0), x[0]))
                    )
                    lines.append(f"  • {agent}: {parts}")
            # Working/failed API bases observed
            try:
                wb = cls._API_BASE_WORKING
                fb = sorted(list(cls._API_BASE_FAILED)) if cls._API_BASE_FAILED else []
                lines.append(f"- API base (working): {wb or 'unknown'}")
                if fb:
                    lines.append(f"- API bases (failed): {', '.join(fb)}")
            except Exception:
                pass
            logger.info("\n".join(lines))
        except Exception:
            pass

    # ---- Price metrics helpers ----
    @classmethod
    def _price_mark(cls, source: str, success: bool) -> None:
        try:
            src = "api" if str(source or "").lower().startswith("api") else "yf"
            key_att = f"{src}_attempts"
            key_suc = f"{src}_success"
            key_fail = f"{src}_fail"
            pm = cls._PRICE_METRICS
            pm[key_att] = int(pm.get(key_att, 0) or 0) + 1
            if success:
                pm[key_suc] = int(pm.get(key_suc, 0) or 0) + 1
            else:
                pm[key_fail] = int(pm.get(key_fail, 0) or 0) + 1
        except Exception:
            pass

    def _settings(self):  # lazy load centralized settings
        s = getattr(self, "__settings", None)
        if s is not None:
            return s
        try:
            from apps.sentiment.src.settings import Settings as _S  # type: ignore

            s = _S()
        except Exception:
            s = None
        setattr(self, "__settings", s)
        return s

    @staticmethod
    def _coerce_evaluation_from_text(text: str) -> Optional[dict[str, Any]]:
        """Parse evaluator free-text into a structured object with string-digit rating.

        String mapping required by schema: "0"=POOR, "1"=FAIR, "2"=GOOD, "3"=EXCELLENT
        """
        if not isinstance(text, str) or not text.strip():
            return None
        import re as _re

        # Extract rating label if present
        rating = None
        m = _re.search(r"Quality\s*rating\s*:\s*([A-Za-z_\-]+)", text, _re.IGNORECASE)
        if not m:
            m = _re.search(r"OVERALL\s*RATING\s*:\s*([A-Za-z_\-]+)", text, _re.IGNORECASE)
        if m:
            rating = m.group(1).strip().upper().replace(" ", "_")
        # Extract needs improvement hint
        needs = None
        m2 = _re.search(r"Improvement\s*needed\s*:\s*(true|false|yes|no)", text, _re.IGNORECASE)
        if m2:
            needs = m2.group(1).strip().lower() in {"true", "yes"}
        # Fallbacks
        if rating is None and needs is not None:
            rating = "FAIR" if needs else "GOOD"
        if rating is None:
            return None
        rating_map = {"POOR": "0", "FAIR": "1", "GOOD": "2", "EXCELLENT": "3"}
        rating_code = rating_map.get(rating, "1")
        return {
            "rating": rating_code,
            "feedback": text,
            "needs_improvement": bool(needs) if needs is not None else True,
        }

    @staticmethod
    def _normalize_evaluation_data(data: dict) -> dict:
        """Normalize evaluator JSON to match string-digit enum schema expected by the model.

        - rating: convert labels or ints to string digits ("0".."3")
        - needs_improvement: coerce from string to boolean
        """
        out = dict(data) if isinstance(data, dict) else {}
        if "rating" in out:
            r = out["rating"]
            if isinstance(r, str):
                r_str = r.strip().upper()
                label_map = {"POOR": "0", "FAIR": "1", "GOOD": "2", "EXCELLENT": "3"}
                if r_str in label_map:
                    out["rating"] = label_map[r_str]
                elif r_str in {"0", "1", "2", "3"}:
                    out["rating"] = r_str
            elif isinstance(r, (int, float)):
                # Coerce numeric to string digit within 0..3
                try:
                    ival = int(r)
                    if 0 <= ival <= 3:
                        out["rating"] = str(ival)
                except Exception:
                    out["rating"] = "1"
        if "needs_improvement" in out and isinstance(out["needs_improvement"], str):
            out["needs_improvement"] = out["needs_improvement"].strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        return out

    @staticmethod
    def _to_snake(s: str) -> str:
        s2 = s.replace("-", " ").replace("/", " ").replace(".", " ")
        parts = [p for p in s2.strip().lower().split() if p]
        return "_".join(parts) if parts else s.strip()

    @classmethod
    def _normalize_plan_data(cls, data: dict) -> dict:
        """Normalize common planner JSON variants to match Orchestrator schema.

        - Enforce steps: list of { description: str, tasks: list[{ description, agent }] }
        - Map agent aliases to known names: research_quality_controller, financial_analyst, report_writer
        - Coerce is_complete to boolean; default False
        - Rename 'subtasks' -> 'tasks' if needed
        """
        if not isinstance(data, dict):
            return {"steps": [], "is_complete": False}
        out = dict(data)
        steps = out.get("steps")
        if not isinstance(steps, list):
            steps = []
        normalized_steps: list[dict] = []
        for st in steps:
            if not isinstance(st, dict):
                continue
            desc = st.get("description")
            tasks = st.get("tasks")
            if tasks is None and isinstance(st.get("subtasks"), list):
                tasks = st.get("subtasks")
            if not isinstance(tasks, list):
                tasks = []
            normalized_tasks: list[dict] = []
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                tdesc = t.get("description")
                agent = t.get("agent")
                if isinstance(agent, str):
                    agen_lower = agent.lower()
                    snake = cls._to_snake(agent)
                    if ("evaluatoroptimizerllm" in agen_lower) or (
                        "research_quality" in agen_lower
                    ):
                        agent_fixed = "research_quality_controller"
                    elif "financial" in agen_lower and "analyst" in agen_lower:
                        agent_fixed = "financial_analyst"
                    elif "report" in agen_lower and "writer" in agen_lower:
                        agent_fixed = "report_writer"
                    else:
                        agent_fixed = snake
                else:
                    agent_fixed = "research_quality_controller"
                normalized_tasks.append({"description": tdesc, "agent": agent_fixed})
            normalized_steps.append({"description": desc, "tasks": normalized_tasks})
        out["steps"] = normalized_steps
        is_complete_raw = out.get("is_complete", None)
        if is_complete_raw is None:
            for alt in ("isComplete", "complete", "completed", "done", "status"):
                if alt in out:
                    is_complete_raw = out[alt]
                    break

        if isinstance(is_complete_raw, str):
            norm = is_complete_raw.strip().lower()
            is_complete = norm in {
                "true",
                "1",
                "yes",
                "on",
                "complete",
                "completed",
                "done",
                "finished",
                "success",
            }
        elif isinstance(is_complete_raw, bool):
            is_complete = is_complete_raw
        else:
            is_complete = False

        # If the plan returns no remaining steps, default to complete
        if not steps and is_complete is False:
            is_complete = True

        out["is_complete"] = is_complete
        return out

    @classmethod
    def _normalize_plan_with_context(cls, data: dict, context_text: str | None) -> dict:
        """Temporarily disabled context-based completion heuristics.

        This method now defers to _normalize_plan_data without using the context
        to avoid premature completion or step skipping.
        """
        return cls._normalize_plan_data(data)

    def _tool_cache_ttl(self, tool_name: str | None, args: dict[str, Any] | None = None) -> int:
        """Determine cache TTL for a tool call, honoring overrides and heuristics."""
        try:
            default_ttl = int(getattr(self, "_mcp_tool_cache_default_ttl", 86400) or 86400)
        except Exception:
            default_ttl = 86400
        overrides = getattr(self, "_mcp_tool_cache_ttl_overrides", {}) or {}
        ttl = default_ttl
        name = str(tool_name or "").strip().lower()
        if overrides and name in overrides:
            try:
                ttl = int(overrides[name])
            except Exception:
                ttl = default_ttl
        else:
            heuristic_ttl: Optional[int] = None
            try:
                if name:
                    if "yfinance" in name or name.endswith(".quote") or "quote" in name:
                        heuristic_ttl = 900  # 15 minutes for market data
                    elif "search" in name or "serper" in name or "g-search" in name:
                        heuristic_ttl = 900  # search results get refreshed frequently
                    elif "fetch" in name:
                        url = ""
                        if isinstance(args, dict):
                            for key in ("url", "uri", "href"):
                                val = args.get(key)
                                if isinstance(val, str) and val:
                                    url = val.lower()
                                    break
                        if url:
                            if any(
                                token in url
                                for token in (
                                    "quote",
                                    "price",
                                    "marketdata",
                                    "market-data",
                                    "intraday",
                                    "real-time",
                                    "realtime",
                                )
                            ):
                                heuristic_ttl = 600
                            elif any(
                                token in url
                                for token in (
                                    "sec.gov",
                                    "edgar",
                                    "10-k",
                                    "10q",
                                    "10-k",
                                    "10-q",
                                    "8-k",
                                )
                            ):
                                heuristic_ttl = default_ttl
            except Exception:
                heuristic_ttl = None
            if heuristic_ttl and heuristic_ttl > 0 and heuristic_ttl < ttl:
                ttl = heuristic_ttl
        if ttl <= 0:
            ttl = 60
        return max(60, int(ttl))

    async def _call_openai(
        self,
        message: Union[str, MessageParamT, List[MessageParamT]],
        request_params: RequestParams,
        response_model: Optional[Type[ModelT]] = None,
        previous_response_id: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        # Simple per-instance cache for MCP tool calls to avoid repeated searches/fetches
        try:
            # --- Inside _call_openai(), near the start (before bridge loop) ---
            # Add these locals so increments never NameError and flags are available everywhere
            tool_calls_total_local = 0
            cache_enabled = bool(getattr(self._settings(), "sentiment_tool_cache", True))
            max_pdf_chars = None
            try:
                max_pdf_chars = int(
                    getattr(self._settings(), "sentiment_pdf_extract_max_chars", 200_000)
                )
            except Exception:
                max_pdf_chars = 200_000

            if not hasattr(self, "_mcp_tool_cache"):
                self._mcp_tool_cache: dict[str, dict[str, Any]] = {}
            if not hasattr(self, "_mcp_tool_cache_default_ttl"):
                s = self._settings()
                ttl = None
                try:
                    ttl = int(getattr(s, "sentiment_tool_cache_ttl_seconds", 0)) if s else None
                except Exception:
                    ttl = None
                default_ttl = ttl if ttl and ttl > 0 else 86400
                overrides_raw = None
                overrides: dict[str, int] = {}
                try:
                    overrides_raw = getattr(s, "sentiment_tool_cache_ttl_overrides", None)
                except Exception:
                    overrides_raw = None
                if isinstance(overrides_raw, str):
                    try:
                        overrides_raw = json.loads(overrides_raw)
                    except Exception:
                        overrides_raw = None
                if isinstance(overrides_raw, dict):
                    for key, val in list(overrides_raw.items()):
                        try:
                            name = str(key or "").strip().lower()
                            ival = int(val)
                            if name and ival > 0:
                                overrides[name] = ival
                        except Exception:
                            continue
                self._mcp_tool_cache_default_ttl = default_ttl
                self._mcp_tool_cache_ttl_overrides = overrides
            # Initialize Redis client lazily if available
            if AsyncRedis is not None and not hasattr(self, "_redis_client"):
                s = self._settings()
                url = getattr(s, "redis_url", None) if s else None
                host = getattr(s, "redis_host", None) or "localhost"
                port_raw = str(getattr(s, "redis_port", "6379") or "6379")
                db_raw = str(getattr(s, "redis_db", "0") or "0")
                password = getattr(s, "redis_password", None) if s else None
                try:
                    if url:
                        self._redis_client = AsyncRedis.from_url(url, decode_responses=True)  # type: ignore[attr-defined]
                    else:
                        self._redis_client = AsyncRedis(  # type: ignore[call-arg]
                            host=host,
                            port=int(port_raw),
                            db=int(db_raw),
                            password=password,
                            decode_responses=True,
                        )
                except Exception:
                    self._redis_client = None
        except Exception:
            pass
        # Toggle for capturing full prompts/responses to logs
        s = self._settings()
        log_prompts = bool(getattr(s, "sentiment_log_prompts", False))
        if log_prompts:
            try:
                self.logger.setLevel(logging.DEBUG)
            except Exception:
                pass
        prompt_logger = logging.getLogger("sentiment.prompts")
        if log_prompts:
            prompt_logger.setLevel(logging.DEBUG)
            # Attach a rotating file handler directly to this logger to
            # guarantee capture even if root level is INFO.
            try:
                log_path = getattr(s, "sentiment_log_file", None)
                if log_path:
                    # De-duplicate by filename
                    already = False
                    for h in prompt_logger.handlers:
                        if (
                            isinstance(h, RotatingFileHandler)
                            and getattr(h, "baseFilename", None) == log_path
                        ):
                            already = True
                            break
                    if not already:
                        fh = RotatingFileHandler(
                            log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
                        )
                        fh.setLevel(logging.DEBUG)
                        fh.setFormatter(
                            logging.Formatter(
                                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                            )
                        )
                        prompt_logger.addHandler(fh)
                        # Avoid double logging via root when a dedicated handler is present
                        prompt_logger.propagate = False
            except Exception:
                pass
        # Visibility hook: confirm this path is active in the logs
        try:
            prompt_logger.debug(
                "[PROMPT_HOOK] agent=%s log_prompts=%s",
                getattr(self.agent, "name", "unknown"),
                str(log_prompts),
            )
        except Exception:
            pass
        # Extra tool-call tracing toggle: only when SENTIMENT_OPENAI_DEBUG=1 (or Settings flag)
        debug_tools = False
        try:
            debug_tools = bool(getattr(s, "sentiment_openai_debug", False))
            if not debug_tools:
                env_flag = os.getenv("SENTIMENT_OPENAI_DEBUG") or os.getenv(
                    "SEntiment_OPENAI_DEBUG"
                )
                debug_tools = str(env_flag).strip().lower() in {"1", "true", "yes", "on"}
        except Exception:
            debug_tools = False

        def _args_preview(obj: Any, maxlen: int = 400) -> str:
            try:
                s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
            except Exception:
                s = str(obj)
            return s if len(s) <= maxlen else (s[:maxlen] + "…")

        def _log_tool_failure(
            call_id: Any,
            name: Any,
            args: Any,
            exc: Exception,
            *,
            nested: bool = False,
        ) -> None:
            """Emit structured log entry when an MCP tool call raises."""
            try:
                try:
                    self.record_tool_error(getattr(self.agent, "name", "unknown"), str(name))
                except Exception:
                    pass
                self.logger.error(
                    "MCP tool call failed",
                    exc_info=True,
                    data={
                        "agent": getattr(self.agent, "name", "unknown"),
                        "call_id": call_id,
                        "name": name,
                        "nested": nested,
                        "args_preview": _args_preview(args),
                        "exception_type": type(exc).__name__,
                    },
                )
            except Exception:
                pass

        # Collect messages as Responses API input
        messages: List[dict[str, Any]] = []
        # If caller provided a prebuilt conversation (list of role/content dicts), use it directly
        if isinstance(message, list) and all(
            isinstance(m, dict) and m.get("role") and m.get("content") is not None for m in message
        ):
            messages = list(message)
            if self.instruction and not any(m.get("role") == "developer" for m in messages):
                messages.insert(
                    0,
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": self.instruction}],
                    },
                )
        else:
            if self.instruction:
                messages.append(
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": self.instruction}],
                    }
                )

            if isinstance(message, str):
                messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": message}],
                    }
                )
            elif isinstance(message, list):
                # Best-effort: stringify complex inputs
                joined = "\n".join(str(m) for m in message)
                messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": joined}],
                    }
                )
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": str(message)}],
                    }
                )

        model = request_params.model or (
            self.default_request_params.model if self.default_request_params else None
        )
        if not model:
            raise ValueError("Planner model not specified")

        # Map token + reasoning params
        kwargs: dict[str, Any] = {"model": model, "input": messages, "stream": False}
        # If the caller provides a previous_response_id, continue that Responses session
        if previous_response_id:
            kwargs["previous_response_id"] = previous_response_id
        # Default higher token budgets for verbose worker agents
        agent_name = str(getattr(self.agent, "name", "")).lower()
        default_tokens = 2048
        try:
            if agent_name == "financial_analyst":
                v = getattr(s, "sentiment_analyst_max_tokens", None)
                default_tokens = int(v) if v else 8192
            elif agent_name == "report_writer":
                v = getattr(s, "sentiment_writer_max_tokens", None)
                default_tokens = int(v) if v else 8192
        except Exception:
            pass
        if hasattr(request_params, "maxTokens") and request_params.maxTokens:
            kwargs["max_output_tokens"] = int(request_params.maxTokens)
            if kwargs["max_output_tokens"] < default_tokens:
                kwargs["max_output_tokens"] = default_tokens
        else:
            # Provide a sane default to avoid truncation
            kwargs["max_output_tokens"] = default_tokens

        # Reasoning effort from context.openai if present
        try:
            context = getattr(self, "context", None)
            cfg = getattr(context, "config", None) if context is not None else None
            openai_cfg = getattr(cfg, "openai", None) if cfg is not None else None
            effort = (
                getattr(openai_cfg, "reasoning_effort", None) if openai_cfg is not None else None
            )
            if effort:
                kwargs["reasoning"] = {"effort": effort}
        except Exception:
            pass

        # Map MCP tools to Responses function tools
        try:
            tools_resp = await self.agent.list_tools()
            tools_list: list[dict[str, Any]] = []
            # Cache schemas to guide argument augmentation (e.g., fetch PDF handling)
            self._tool_schemas: dict[str, dict[str, Any]] = {}
            # Hard allowlist for Serper MCP: only general and news search
            SERPER_ALLOWLIST = {"serper_google_search", "serper_google_search_news"}
            filtered_out: list[str] = []
            raw_tools = list(getattr(tools_resp, "tools", []) or [])
            # Deterministic ordering helps OpenAI prompt caching and makes logs diff-friendly.
            try:
                raw_tools.sort(key=lambda tt: str(getattr(tt, "name", "") or ""))
            except Exception:
                pass
            for t in raw_tools:
                name = getattr(t, "name", None)
                if not name:
                    continue
                # Names are namespaced as "<server>_<tool>" by the aggregator.
                # Enforce Serper allowlist to reduce irrelevant tools (images, videos, maps, etc.).
                try:
                    n = str(name)
                    if n.startswith("serper_") and n not in SERPER_ALLOWLIST:
                        filtered_out.append(n)
                        continue
                except Exception:
                    pass
                schema = getattr(t, "inputSchema", {}) or {}
                try:
                    self._tool_schemas[str(name)] = schema
                except Exception:
                    pass
                tool_def = {
                    "type": "function",
                    "name": name,
                    "description": getattr(t, "description", "") or "",
                    "parameters": schema,
                }
                tools_list.append(tool_def)
            if tools_list:
                try:
                    tools_list.sort(key=lambda td: str(td.get("name", "") or ""))
                except Exception:
                    pass
                kwargs["tools"] = tools_list
                # Avoid OpenAI's multi_tool_use.parallel aggregator; bridge tools individually
                # by not advertising parallel tool calls support.
                # (Some SDKs/models auto-infer parallel usage; this reduces aggregator usage.)
            # Log filtering summary (debug-level)
            try:
                if filtered_out:
                    self.logger.debug(
                        "Serper tool filtering: pruned tools",
                        data={
                            "filtered_count": len(filtered_out),
                            "filtered": sorted(filtered_out),
                            "allowed": sorted(
                                [
                                    t["name"]
                                    for t in tools_list
                                    if str(t.get("name", "")).startswith("serper_")
                                ]
                            ),
                        },
                    )
            except Exception:
                pass
        except Exception:
            pass

        # Prefer JSON-only responses when a structured model is requested
        if response_model is not None:
            try:
                schema = response_model.model_json_schema()
                self._disallow_additional_props(schema)
                # _disallow_additional_props(schema)
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": schema,
                    },
                }
                # Do not set temperature: some gpt-5 models don't support it
            except Exception:
                # last-resort fallback
                kwargs["response_format"] = {"type": "json_object"}
        else:
            # Encourage JSON-only outputs only for the analyst to keep structure.
            try:
                if agent_name == "financial_analyst":
                    kwargs["response_format"] = {"type": "json_object"}
            except Exception:
                pass

        # Build client from context config
        config = getattr(self.context, "config", None)
        api_key = getattr(getattr(config, "openai", None), "api_key", None)
        base_url = getattr(getattr(config, "openai", None), "base_url", None)
        client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else AsyncOpenAI(api_key=api_key)
        )

        # Log request (without secrets)
        try:
            safe_kwargs = {
                k: (v if k not in {"input"} else f"messages[{len(v)}]") for k, v in kwargs.items()
            }
            agent_name = getattr(self.agent, "name", "unknown")
            self.logger.debug(
                "BEGIN OAI Responses.create",
                data={
                    "agent": agent_name,
                    "model": kwargs.get("model"),
                    "max_output_tokens": kwargs.get("max_output_tokens"),
                    "reasoning": kwargs.get("reasoning"),
                    "messages_count": len(messages),
                    "response_format": kwargs.get("response_format"),
                },
            )
            self.logger.debug("Responses.create kwargs:", data=safe_kwargs)
            if log_prompts:
                try:
                    msgs_json = json.dumps(messages, ensure_ascii=False)
                except Exception:
                    msgs_json = str(messages)
                self.logger.debug(
                    "PROMPT messages",
                    data={
                        "agent": agent_name,
                        "model": kwargs.get("model"),
                        "messages_json": msgs_json,
                    },
                )
                # Also log prompts via standard logger to ensure file capture
                try:
                    prompt_logger.debug(
                        "[PROMPT] agent=%s model=%s messages=%s",
                        agent_name,
                        kwargs.get("model"),
                        msgs_json,
                    )
                except Exception:
                    pass
        except Exception:
            pass

        # Budget guard: build rough system/user text from messages for preflight
        def _flatten_messages(msgs: List[dict[str, Any]]) -> tuple[str, str]:
            sys_parts: list[str] = []
            user_parts: list[str] = []
            for m in msgs:
                try:
                    role = m.get("role")
                    content = m.get("content")
                    if isinstance(content, list):
                        txt = " ".join(
                            [str(c.get("text", "")) for c in content if isinstance(c, dict)]
                        )
                    else:
                        txt = str(content or "")
                    rlow = str(role or "").lower()
                    # Treat developer/system/instruction(s) as system-equivalent for budgeting
                    if rlow in {"developer", "system", "instruction", "instructions"}:
                        sys_parts.append(txt)
                    elif rlow in {
                        "user",
                        "assistant",
                    }:  # include assistant history for conservative estimate
                        user_parts.append(txt)
                except Exception:
                    continue
            return "\n".join(sys_parts), "\n".join(user_parts)

        sys_txt, usr_txt = _flatten_messages(messages)
        if os.getenv("AI_DISABLE", "0").lower() in {"1", "true", "yes"}:
            raise RuntimeError("AI disabled by AI_DISABLE=1")
        # Shared ledger per process for sentiment
        if not hasattr(type(self), "_LEDGER"):
            type(self)._LEDGER = BudgetLedger(
                service="sentiment_llm",
                budget=Budget(),
                counter=get_redis_counter_from_env(),
                alert_handler=_budget_alert_log_only,
            )  # type: ignore[attr-defined]
        ledger: BudgetLedger = type(self)._LEDGER  # type: ignore[attr-defined]

        # Preflight and reserve
        try:
            est_in, est_cost = preflight_estimate_cost(
                str(kwargs.get("model", "")), sys_txt, usr_txt
            )
            reservation = ledger.begin_call(tokens_estimate=est_in, cost_estimate_usd=est_cost)
        except Exception as e:
            raise RuntimeError(f"budget_block: {e}")

        # Create response, with fallback if SDK does not support response_format
        try:
            resp = await client.responses.create(**kwargs)  # type: ignore[arg-type]
        except TypeError as e:
            # Older SDKs may not accept response_format; retry without it
            if "response_format" in str(e):
                try:
                    _ = kwargs.pop("response_format", None)
                    self.logger.debug(
                        "Responses.create: retrying without response_format (unsupported by SDK)",
                        data={"had_response_format": True},
                    )
                except Exception:
                    pass
                resp = await client.responses.create(**kwargs)  # type: ignore[arg-type]
            else:
                raise

        # Helper: augment fetch args (PDF-aware) based on tool schema and apply API base override
        def _augment_fetch_args(tool_name: str, args: dict[str, Any] | None) -> dict[str, Any]:
            a: dict[str, Any] = dict(args or {})
            try:
                if "fetch" not in (tool_name or "").lower():
                    return a
                # Identify potential URL field from schema
                schema = (getattr(self, "_tool_schemas", {}) or {}).get(tool_name) or {}
                props = (schema.get("properties") if isinstance(schema, dict) else None) or {}
                url_key = None
                for cand in ("url", "uri", "href"):
                    if cand in props or cand in a:
                        url_key = cand
                        break
                if not url_key and any(k in a for k in ("url", "uri", "href")):
                    for k in ("url", "uri", "href"):
                        if k in a:
                            url_key = k
                            break
                url_val = a.get(url_key) if url_key else None

                # Apply SENTIMENT_API_BASE to internal API URLs or placeholders
                try:
                    s = self._settings()
                    api_base = None
                    if s is not None:
                        api_base = getattr(s, "sentiment_api_base", None)
                    if not api_base:
                        import os as _os

                        api_base = _os.getenv("SENTIMENT_API_BASE")
                    if isinstance(api_base, str) and api_base.strip():
                        api_base = api_base.strip().rstrip("/")
                        if isinstance(url_val, str) and url_val:
                            new_url = url_val
                            # Placeholder replacement
                            if "{BASE}" in new_url:
                                new_url = new_url.replace("{BASE}", api_base)
                            else:
                                # Rewrite common local hostnames to api_base while preserving path/query
                                try:
                                    parts = urlsplit(new_url)
                                    # If relative path like "/api/...", join with base
                                    if (
                                        not parts.scheme
                                        and not parts.netloc
                                        and new_url.startswith("/api/")
                                    ):
                                        new_url = f"{api_base}{new_url}"
                                    else:
                                        host = parts.hostname or ""
                                        # Known local aliases we want to override
                                        if host in {
                                            "api",
                                            "localhost",
                                            "127.0.0.1",
                                            "host.docker.internal",
                                        }:
                                            # Rebuild using api_base for scheme/netloc
                                            b = urlsplit(api_base)
                                            new_url = urlunsplit(
                                                (
                                                    b.scheme,
                                                    b.netloc,
                                                    parts.path or "",
                                                    parts.query or "",
                                                    parts.fragment or "",
                                                )
                                            )
                                except Exception:
                                    # best-effort; leave as-is on parse failure
                                    pass
                            if new_url != url_val and url_key:
                                a[url_key] = new_url
                                url_val = new_url
                    else:
                        # No explicit base configured. If we have learned a working base, prefer it.
                        try:
                            wb = type(self)._API_BASE_WORKING
                            if wb and isinstance(url_val, str) and url_val:
                                parts = urlsplit(url_val)
                                # only rewrite local aliases
                                if (parts.hostname or "") in {
                                    "api",
                                    "localhost",
                                    "127.0.0.1",
                                    "host.docker.internal",
                                } or (
                                    not parts.scheme
                                    and not parts.netloc
                                    and str(url_val).startswith("/api/")
                                ):
                                    b = urlsplit(wb)
                                    new_url = (
                                        urlunsplit(
                                            (
                                                b.scheme,
                                                b.netloc,
                                                parts.path or "",
                                                parts.query or "",
                                                parts.fragment or "",
                                            )
                                        )
                                        if parts.scheme
                                        else f"{wb}{url_val}"
                                    )
                                    a[url_key] = new_url
                                    url_val = new_url
                            # Avoid retrying known-bad bases
                            fb = type(self)._API_BASE_FAILED
                            if isinstance(url_val, str) and url_val:
                                parts2 = urlsplit(url_val)
                                base2 = (
                                    f"{parts2.scheme}://{parts2.netloc}"
                                    if parts2.scheme and parts2.netloc
                                    else None
                                )
                                if base2 and base2 in fb and wb:
                                    b = urlsplit(wb)
                                    new_url2 = urlunsplit(
                                        (
                                            b.scheme,
                                            b.netloc,
                                            parts2.path or "",
                                            parts2.query or "",
                                            parts2.fragment or "",
                                        )
                                    )
                                    a[url_key] = new_url2
                                    url_val = new_url2
                        except Exception:
                            pass
                except Exception:
                    pass
                # Hint JSON handling for API endpoints
                try:
                    if isinstance(url_val, str) and url_val:
                        low = url_val.lower()
                        looks_api = "/api/" in low or low.endswith(".json")
                        # Add Accept header to prefer JSON
                        if looks_api and ("headers" in props or True):
                            try:
                                headers_obj = a.get("headers")
                                if not isinstance(headers_obj, dict):
                                    headers_obj = {}
                                # Set Accept only if caller didn't set one
                                if not any(k.lower() == "accept" for k in headers_obj.keys()):
                                    headers_obj["Accept"] = "application/json"
                                a["headers"] = headers_obj
                            except Exception:
                                pass
                        # If server supports a 'format' argument, prefer json
                        if looks_api and "format" in props and not a.get("format"):
                            a["format"] = "json"
                except Exception:
                    pass

                is_pdf = False
                if isinstance(url_val, str):
                    u = url_val.lower()
                    is_pdf = (
                        ".pdf" in u
                        or "content=pdf" in u
                        or "format=pdf" in u
                        or "download=pdf" in u
                    )
                # Ensure minimum max_length
                fl = getattr(self._settings(), "sentiment_fetch_max_length", None)
                try:
                    min_len = int(fl) if fl else 5000
                except Exception:
                    min_len = 5000
                if "max_length" in props or "max_length" in a:
                    try:
                        if int(a.get("max_length", 0) or 0) < min_len:
                            a["max_length"] = min_len
                    except Exception:
                        a["max_length"] = min_len
                # If PDF, hint the server to return plain text if supported
                if is_pdf and isinstance(props, dict):
                    if "extract_text" in props:
                        a.setdefault("extract_text", True)
                    if "as_text" in props:
                        a.setdefault("as_text", True)
                    if "format" in props:
                        # Common pattern: format: "text" | "html" | "json"
                        a.setdefault("format", "text")
                    if "mime" in props:
                        a.setdefault("mime", "text/plain")
                    if "encoding" in props and not a.get("encoding"):
                        a["encoding"] = "utf-8"
                return a
            except Exception:
                return a

        # --- Replace your _pdf_to_markdown with a streaming version + length cap ---
        async def _pdf_to_markdown(url: str) -> Optional[str]:
            try:
                if httpx is None:
                    return None
                timeout = httpx.Timeout(30.0, connect=15.0)
                headers = {"User-Agent": "Mozilla/5.0 (compatible; RankAlpha/1.0)"}

                from datetime import datetime as _dt
                from pathlib import Path as _Path

                base_dir = getattr(self._settings(), "sentiment_data_dir", None) or "/tmp"
                tmp_dir = _Path(base_dir) / "pdf_tmp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                fname = _dt.now().strftime("pdf_%Y%m%d_%H%M%S_%f.pdf")
                fpath = tmp_dir / fname

                # Stream to disk to avoid loading entire file in memory
                async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                    async with client.stream("GET", url, headers=headers) as r:
                        r.raise_for_status()
                        ct = (r.headers.get("content-type") or "").lower()
                        # optional: basic size guard
                        cl = r.headers.get("content-length")
                        if cl and int(cl) > 50 * 1024 * 1024:
                            return None  # bail on >50MB by policy; adjust as needed
                        with fpath.open("wb") as w:
                            async for chunk in r.aiter_bytes():
                                w.write(chunk)

                # Quick validation by magic header if possible
                head = fpath.read_bytes(5)
                if not head.startswith(b"%PDF") and "pdf" not in ct:
                    return None

                # Prefer PyMuPDF markdown
                try:
                    import pymupdf4llm as _pdf4llm  # type: ignore

                    md = _pdf4llm.to_markdown(str(fpath))
                    if isinstance(md, str) and md.strip():
                        pass
                    else:
                        md = None
                except Exception:
                    md = None

                # Fallback to pdfminer text
                if not md:
                    try:
                        from pdfminer.high_level import (
                            extract_text as _extract_text,  # type: ignore
                        )

                        txt = _extract_text(str(fpath))
                        if txt and txt.strip():
                            md = "# Extracted PDF Text\n\n" + txt
                    except Exception:
                        md = None

                if not md:
                    return None

                # Hard cap length to avoid blowing the model context
                nonlocal max_pdf_chars  # uses the variable defined above
                if max_pdf_chars and len(md) > max_pdf_chars:
                    md = md[:max_pdf_chars] + f"\n\n[Truncated at {max_pdf_chars} chars]"

                return md
            except Exception:
                return None

        # Bridge Responses function calls to MCP tools (with per-instance caching)
        try:
            while True:
                outputs = getattr(resp, "output", []) or []
                fn_outputs: list[dict[str, Any]] = []

                # Helper predicates for price API detection
                def _is_price_api_url(u: str | None) -> bool:
                    if not isinstance(u, str) or not u:
                        return False
                    ul = u.lower()
                    return ("/api/v1/prices/latest" in ul) or ("/api/v1/prices/history" in ul)

                for item in outputs:
                    if getattr(item, "type", "") != "function_call":
                        continue
                    call_id, name, args_raw = _extract_tool_call_fields(item)
                    try:
                        args = (
                            json.loads(args_raw or "{}")
                            if isinstance(args_raw, str)
                            else (args_raw or {})
                        )
                    except Exception:
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    if debug_tools:
                        try:
                            self.logger.debug(
                                "TOOL_CALL",
                                data={
                                    "agent": getattr(self.agent, "name", "unknown"),
                                    "call_id": call_id,
                                    "name": name,
                                    "args_preview": _args_preview(args),
                                },
                            )
                        except Exception:
                            pass
                    # Special handling for OpenAI's aggregator tool which requests multiple tool calls in parallel
                    try:
                        nlower = str(name or "").lower()
                        if nlower in {
                            "multi_tool_use.parallel",
                            "multi_tool_use.serial",
                            "functions.multi_tool_use.parallel",
                        }:
                            nested = []
                            # Common schema: { "tool_calls": [ {"id": "call_...", "name": "fetch", "arguments": {...}}, ...] }
                            if isinstance(args, dict):
                                if isinstance(args.get("tool_calls"), list):
                                    nested = args.get("tool_calls") or []
                                elif isinstance(args.get("calls"), list):
                                    nested = args.get("calls") or []
                            for nc in nested:
                                try:
                                    nid, nname, nargs_raw = _extract_tool_call_fields(nc)
                                    if isinstance(nargs_raw, str):
                                        try:
                                            nargs = json.loads(nargs_raw)
                                        except Exception:
                                            nargs = {}
                                    elif isinstance(nargs_raw, dict):
                                        nargs = nargs_raw
                                    else:
                                        nargs = {}
                                    if not nid or not nname:
                                        continue
                                    if debug_tools:
                                        try:
                                            self.logger.debug(
                                                "TOOL_CALL",
                                                data={
                                                    "agent": getattr(self.agent, "name", "unknown"),
                                                    "call_id": nid,
                                                    "name": nname,
                                                    "nested": True,
                                                    "args_preview": _args_preview(nargs),
                                                },
                                            )
                                        except Exception:
                                            pass
                                    # If this nested call is a fetch for a PDF, directly convert to markdown
                                    try:
                                        url_val = None
                                        if isinstance(nargs, dict):
                                            for k in ("url", "uri", "href"):
                                                if k in nargs:
                                                    url_val = nargs[k]
                                                    break
                                        if (
                                            isinstance(nname, str)
                                            and ("fetch" in nname.lower())
                                            and isinstance(url_val, str)
                                        ):
                                            low = url_val.lower()
                                            if any(
                                                s in low
                                                for s in (
                                                    ".pdf",
                                                    "content=pdf",
                                                    "format=pdf",
                                                    "download=pdf",
                                                )
                                            ):
                                                md = await _pdf_to_markdown(url_val)
                                                if md:
                                                    payload = {
                                                        "text": md,
                                                        "isError": False,
                                                        "source": "pdf-markdown",
                                                        "truncated": len(md) >= max_pdf_chars,
                                                    }
                                                    fn_outputs.append(
                                                        {
                                                            "type": "function_call_output",
                                                            "call_id": nid,
                                                            "output": json.dumps(
                                                                payload, ensure_ascii=False
                                                            ),
                                                        }
                                                    )
                                                    if debug_tools:
                                                        try:
                                                            self.logger.debug(
                                                                "TOOL_RESULT",
                                                                data={
                                                                    "call_id": nid,
                                                                    "name": nname,
                                                                    "short_circuit": True,
                                                                    "isError": False,
                                                                    "text_len": len(
                                                                        payload.get("text") or ""
                                                                    ),
                                                                },
                                                            )
                                                        except Exception:
                                                            pass
                                                    tool_calls_total_local += 1
                                                    # Also cache result
                                                    try:
                                                        if cache_enabled:
                                                            # Build a local cache key specific to nested call
                                                            nkey = f"{nname}:{json.dumps(nargs, sort_keys=True, ensure_ascii=False)}"
                                                            ttl_value = self._tool_cache_ttl(
                                                                nname,
                                                                nargs
                                                                if isinstance(nargs, dict)
                                                                else None,
                                                            )
                                                            if (
                                                                getattr(self, "_redis_client", None)
                                                                is not None
                                                            ):
                                                                rkey = (
                                                                    f"sentiment:tool_cache:{nkey}"
                                                                )
                                                                await self._redis_client.setex(
                                                                    rkey,
                                                                    ttl_value,
                                                                    json.dumps(
                                                                        payload, ensure_ascii=False
                                                                    ),
                                                                )
                                                            # in-memory
                                                            try:
                                                                self._mcp_tool_cache[nkey] = {
                                                                    "payload": payload,
                                                                    "expires": time.time()
                                                                    + float(ttl_value),
                                                                }
                                                            except Exception:
                                                                pass
                                                    except Exception:
                                                        pass
                                                    tool_calls_total_local += 1
                                                    continue
                                    except Exception:
                                        pass
                                    # Ensure reasonable fetch length by default
                                    try:
                                        if isinstance(nname, str) and isinstance(nargs, dict):
                                            nargs = _augment_fetch_args(nname, nargs)
                                    except Exception:
                                        pass
                                    # Execute the MCP tool for this nested call
                                    req = CallToolRequest(
                                        method="tools/call",
                                        params=CallToolRequestParams(
                                            name=nname, arguments=nargs or {}
                                        ),
                                    )
                                    try:
                                        res = await self.call_tool(
                                            request=req, tool_call_id=str(nid)
                                        )
                                    except Exception as exc:
                                        _log_tool_failure(nid, nname, nargs, exc, nested=True)
                                        raise
                                    try:
                                        self.record_tool_use(
                                            getattr(self.agent, "name", "unknown"), str(nname)
                                        )
                                    except Exception:
                                        pass
                                    out_lines: list[str] = []
                                    for c in getattr(res, "content", []) or []:
                                        try:
                                            out_lines.append(getattr(c, "text", None) or str(c))
                                        except Exception:
                                            pass
                                    payload = {
                                        "text": "\n".join(out_lines),
                                        "isError": getattr(res, "isError", False),
                                    }
                                    try:
                                        if bool(payload.get("isError")):
                                            self.record_tool_error(
                                                getattr(self.agent, "name", "unknown"), str(nname)
                                            )
                                    except Exception:
                                        pass
                                    # Normalize JSON for fetch and record price metrics if applicable
                                    try:
                                        nlow = str(nname or "").lower()
                                        url_val2 = None
                                        if isinstance(nargs, dict):
                                            for k in ("url", "uri", "href"):
                                                if k in nargs:
                                                    url_val2 = nargs[k]
                                                    break
                                        if isinstance(nname, str) and ("fetch" in nlow):
                                            raw_text2 = payload.get("text") or ""
                                            j2 = _extract_json_obj(raw_text2)
                                            if j2 is None:
                                                idx2 = raw_text2.find("\n")
                                                tail2 = (
                                                    raw_text2[idx2 + 1 :].strip()
                                                    if idx2 != -1
                                                    else raw_text2
                                                )
                                                j2 = _extract_json_obj(tail2)
                                            if isinstance(j2, dict):
                                                payload["text"] = json.dumps(j2, ensure_ascii=False)
                                                payload["json"] = j2
                                            if _is_price_api_url(str(url_val2)):
                                                # consider success if items exists and length>0
                                                ok = False
                                                try:
                                                    items = (
                                                        (j2 or {}).get("items")
                                                        if isinstance(j2, dict)
                                                        else None
                                                    )
                                                    ok = bool(
                                                        isinstance(items, list) and len(items) > 0
                                                    )
                                                except Exception:
                                                    ok = not bool(payload.get("isError"))
                                                # Remember base success/failure
                                                try:
                                                    parts_b = urlsplit(str(url_val2))
                                                    base_b = (
                                                        f"{parts_b.scheme}://{parts_b.netloc}"
                                                        if parts_b.scheme and parts_b.netloc
                                                        else None
                                                    )
                                                    if base_b:
                                                        if ok:
                                                            type(self)._API_BASE_WORKING = (
                                                                type(self)._API_BASE_WORKING
                                                                or base_b
                                                            )
                                                            # remove from failed if previously marked
                                                            try:
                                                                type(self)._API_BASE_FAILED.discard(
                                                                    base_b
                                                                )
                                                            except Exception:
                                                                pass
                                                        else:
                                                            try:
                                                                type(self)._API_BASE_FAILED.add(
                                                                    base_b
                                                                )
                                                            except Exception:
                                                                pass
                                                except Exception:
                                                    pass
                                                type(self)._price_mark("api", bool(ok))
                                        elif isinstance(nname, str) and ("yfinance" in nlow):
                                            # treat non-error as success; server schemas vary
                                            type(self)._price_mark(
                                                "yf", not bool(payload.get("isError"))
                                            )
                                    except Exception:
                                        pass
                                    fn_outputs.append(
                                        {
                                            "type": "function_call_output",
                                            "call_id": nid,
                                            "output": json.dumps(payload, ensure_ascii=False),
                                        }
                                    )
                                    if debug_tools:
                                        try:
                                            self.logger.debug(
                                                "TOOL_RESULT",
                                                data={
                                                    "call_id": nid,
                                                    "name": nname,
                                                    "isError": payload.get("isError"),
                                                    "text_len": len(payload.get("text") or ""),
                                                },
                                            )
                                        except Exception:
                                            pass
                                    tool_calls_total_local += 1
                                except Exception:
                                    continue
                            # Aggregator handled; skip normal single-tool path
                            continue
                    except Exception:
                        # Fallback to normal handling if aggregator parsing fails
                        pass
                    # Compute a canonical cache key (ignore purely runtime knobs)
                    cache_enabled = bool(getattr(self._settings(), "sentiment_tool_cache", True))
                    cache_key = None
                    if cache_enabled:
                        try:
                            # Remove non-result-affecting keys
                            args_for_key = dict(args)
                            for k in list(args_for_key.keys()):
                                if k in {"timeout", "debug"}:
                                    args_for_key.pop(k, None)
                            cache_key = f"{name}:{json.dumps(args_for_key, sort_keys=True, ensure_ascii=False)}"
                        except Exception:
                            cache_key = None
                    # Ensure reasonable fetch length and PDF hints
                    try:
                        # If this call is a fetch for PDF, try to convert to markdown directly
                        if isinstance(name, str):
                            url_val = None
                            if isinstance(args, dict):
                                for k in ("url", "uri", "href"):
                                    if k in args:
                                        url_val = args[k]
                                        break
                            if ("fetch" in name.lower()) and isinstance(url_val, str):
                                low = url_val.lower()
                                if any(
                                    s in low
                                    for s in (".pdf", "content=pdf", "format=pdf", "download=pdf")
                                ):
                                    md = await _pdf_to_markdown(url_val)
                                    if md:
                                        payload = {
                                            "text": md,
                                            "isError": False,
                                            "source": "pdf-markdown",
                                            "truncated": len(md) >= max_pdf_chars,
                                        }
                                        # respond immediately without calling the MCP tool
                                        fn_outputs.append(
                                            {
                                                "type": "function_call_output",
                                                "call_id": call_id,
                                                "output": json.dumps(payload, ensure_ascii=False),
                                            }
                                        )
                                        if debug_tools:
                                            try:
                                                self.logger.debug(
                                                    "TOOL_RESULT",
                                                    data={
                                                        "call_id": call_id,
                                                        "name": name,
                                                        "short_circuit": True,
                                                        "isError": False,
                                                        "text_len": len(payload.get("text") or ""),
                                                    },
                                                )
                                            except Exception:
                                                pass
                                        tool_calls_total_local += 1
                                        # Cache result
                                        if cache_enabled and cache_key:
                                            try:
                                                ttl_value = self._tool_cache_ttl(
                                                    name, args if isinstance(args, dict) else None
                                                )
                                                if getattr(self, "_redis_client", None) is not None:
                                                    rkey = f"sentiment:tool_cache:{cache_key}"
                                                    await self._redis_client.setex(
                                                        rkey,
                                                        ttl_value,
                                                        json.dumps(payload, ensure_ascii=False),
                                                    )
                                                self._mcp_tool_cache[cache_key] = {
                                                    "payload": payload,
                                                    "expires": time.time() + float(ttl_value),
                                                }
                                            except Exception:
                                                pass
                                        # Skip the standard tool execution for this call
                                        tool_calls_total_local += 1
                                        continue
                            # otherwise normal augmentation
                            args = _augment_fetch_args(name, args)
                    except Exception:
                        pass
                    cached_payload: Optional[dict[str, Any]] = None
                    # Prefer Redis cache if available
                    if cache_key and getattr(self, "_redis_client", None) is not None:
                        try:
                            rkey = f"sentiment:tool_cache:{cache_key}"
                            val = await self._redis_client.get(rkey)
                            if val:
                                cached_payload = json.loads(val)
                        except Exception:
                            cached_payload = None
                    # Fallback to in-memory cache
                    if (
                        cache_key
                        and cached_payload is None
                        and getattr(self, "_mcp_tool_cache", None) is not None
                    ):
                        entry = self._mcp_tool_cache.get(cache_key)
                        now = time.time()
                        if entry and isinstance(entry, dict):
                            try:
                                if float(entry.get("expires", 0)) >= now:
                                    cached_payload = entry.get("payload")
                                else:
                                    self._mcp_tool_cache.pop(cache_key, None)
                            except Exception:
                                pass
                    if cached_payload is None:
                        # Execute MCP tool
                        req = CallToolRequest(
                            method="tools/call",
                            params=CallToolRequestParams(name=name, arguments=args),
                        )
                        try:
                            res = await self.call_tool(request=req, tool_call_id=str(call_id))
                        except Exception as exc:
                            _log_tool_failure(call_id, name, args, exc, nested=False)
                            raise
                        try:
                            self.record_tool_use(getattr(self.agent, "name", "unknown"), str(name))
                        except Exception:
                            pass
                        out_lines: list[str] = []
                        for c in getattr(res, "content", []) or []:
                            try:
                                out_lines.append(getattr(c, "text", None) or str(c))
                            except Exception:
                                pass
                        payload = {
                            "text": "\n".join(out_lines),
                            "isError": getattr(res, "isError", False),
                        }
                        try:
                            if bool(payload.get("isError")):
                                self.record_tool_error(
                                    getattr(self.agent, "name", "unknown"), str(name)
                                )
                        except Exception:
                            pass
                        # If this was a fetch call that returned JSON, strip helper prefaces and keep pure JSON
                        try:
                            if isinstance(name, str) and "fetch" in name.lower():
                                raw_text = payload.get("text") or ""
                                # Common preface emitted by some fetch MCP servers; extract JSON body
                                # Use the same JSON extractor used elsewhere
                                j = _extract_json_obj(raw_text)
                                if j is None:
                                    # Heuristic: try substring after first '\n' following a colon
                                    idx = raw_text.find("\n")
                                    tail = raw_text[idx + 1 :].strip() if idx != -1 else raw_text
                                    j = _extract_json_obj(tail)
                                if isinstance(j, dict):
                                    payload["text"] = json.dumps(j, ensure_ascii=False)
                                    payload["json"] = j
                                # Record price metrics if this was a prices endpoint
                                try:
                                    url_val3 = None
                                    if isinstance(args, dict):
                                        for k in ("url", "uri", "href"):
                                            if k in args:
                                                url_val3 = args[k]
                                                break
                                    if _is_price_api_url(str(url_val3)):
                                        items = (
                                            (j or {}).get("items") if isinstance(j, dict) else None
                                        )
                                        ok = bool(isinstance(items, list) and len(items) > 0)
                                        # Remember base success/failure
                                        try:
                                            parts_b2 = urlsplit(str(url_val3))
                                            base_b2 = (
                                                f"{parts_b2.scheme}://{parts_b2.netloc}"
                                                if parts_b2.scheme and parts_b2.netloc
                                                else None
                                            )
                                            if base_b2:
                                                if ok:
                                                    type(self)._API_BASE_WORKING = (
                                                        type(self)._API_BASE_WORKING or base_b2
                                                    )
                                                    try:
                                                        type(self)._API_BASE_FAILED.discard(base_b2)
                                                    except Exception:
                                                        pass
                                                else:
                                                    try:
                                                        type(self)._API_BASE_FAILED.add(base_b2)
                                                    except Exception:
                                                        pass
                                        except Exception:
                                            pass
                                        type(self)._price_mark("api", ok)
                                except Exception:
                                    pass
                            elif isinstance(name, str) and ("yfinance" in name.lower()):
                                type(self)._price_mark("yf", not bool(payload.get("isError")))
                        except Exception:
                            pass
                        if debug_tools:
                            try:
                                self.logger.debug(
                                    "TOOL_RESULT",
                                    data={
                                        "call_id": call_id,
                                        "name": name,
                                        "isError": payload.get("isError"),
                                        "text_len": len(payload.get("text") or ""),
                                    },
                                )
                            except Exception:
                                pass
                        if cache_key and cache_enabled:
                            ttl_value = self._tool_cache_ttl(
                                name, args if isinstance(args, dict) else None
                            )
                            # Store in Redis (preferred)
                            try:
                                if getattr(self, "_redis_client", None) is not None:
                                    rkey = f"sentiment:tool_cache:{cache_key}"
                                    await self._redis_client.setex(
                                        rkey, ttl_value, json.dumps(payload, ensure_ascii=False)
                                    )
                            except Exception:
                                pass
                            # Always back up in local memory in case Redis is unavailable later
                            try:
                                self._mcp_tool_cache[cache_key] = {
                                    "payload": payload,
                                    "expires": time.time() + float(ttl_value),
                                }
                            except Exception:
                                pass
                    else:
                        payload = cached_payload
                        if debug_tools:
                            try:
                                self.logger.debug(
                                    "TOOL_RESULT",
                                    data={
                                        "call_id": call_id,
                                        "name": name,
                                        "cache_hit": True,
                                        "isError": payload.get("isError")
                                        if isinstance(payload, dict)
                                        else None,
                                        "text_len": len(
                                            (
                                                payload.get("text")
                                                if isinstance(payload, dict)
                                                else ""
                                            )
                                            or ""
                                        ),
                                    },
                                )
                            except Exception:
                                pass
                    fn_outputs.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": json.dumps(payload, ensure_ascii=False),
                        }
                    )
                if not fn_outputs:
                    break
                if debug_tools:
                    try:
                        self.logger.debug(
                            "TOOL_OUTPUT_POST",
                            data={
                                "agent": getattr(self.agent, "name", "unknown"),
                                "call_ids": [
                                    o.get("call_id") if isinstance(o, dict) else None
                                    for o in fn_outputs
                                ],
                            },
                        )
                    except Exception:
                        pass
                # Preflight not repeated here: a conversation continuation is still a new request; reserve again conservatively
                try:
                    ledger.reserve_request()
                except Exception:
                    pass
                resp = await client.responses.create(
                    model=model,
                    previous_response_id=getattr(resp, "id", None),
                    input=fn_outputs,
                )
        except Exception:
            # If function-call bridging fails, fall through and try to extract text
            pass

        # Extract text output and reconcile usage/cost
        try:
            # Preferred accessor
            text = resp.output_text  # type: ignore[attr-defined]
            # Reconcile cost with usage
            try:
                usage = getattr(resp, "usage", None)
                usage_dict = {}
                if usage is not None:
                    usage_dict = {
                        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    }
                ti, to, actual = reconcile_cost(
                    str(kwargs.get("model", "")),
                    {"usage": usage_dict, "text": text or ""},
                    fallback_in=est_in,
                )
                ledger.commit(ti, to, actual, reservation=reservation)
            except Exception:
                pass
            # Log response metadata and a preview of output
            try:
                preview = (
                    (str(text)[:500] + "…")
                    if text and len(str(text)) > 500
                    else (str(text) if text else "")
                )
                usage = getattr(resp, "usage", None)
                self.logger.debug(
                    "END OAI Responses.create",
                    data={
                        "agent": getattr(self.agent, "name", "unknown"),
                        "id": getattr(resp, "id", None),
                        "status": getattr(resp, "status", None),
                        "usage": getattr(usage, "model_dump", lambda: None)(),
                        "output_preview": preview,
                    },
                )
                if log_prompts:
                    # Attempt to serialize the full response
                    try:
                        if hasattr(resp, "model_dump_json"):
                            full_json = resp.model_dump_json()
                        elif hasattr(resp, "model_dump"):
                            full_json = json.dumps(resp.model_dump(), ensure_ascii=False)
                        else:
                            # Best-effort stringify
                            full_json = str(resp)
                    except Exception:
                        full_json = str(resp)
                    self.logger.debug(
                        "RESPONSE full",
                        data={
                            "agent": getattr(self.agent, "name", "unknown"),
                            "response_json": full_json,
                        },
                    )
                    # Also write full response via standard logger
                    try:
                        prompt_logger.debug(
                            "[RESPONSE] agent=%s id=%s status=%s json=%s",
                            getattr(self.agent, "name", "unknown"),
                            getattr(resp, "id", None),
                            getattr(resp, "status", None),
                            full_json,
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            if text:
                rid = None
                try:
                    rid = getattr(resp, "id", None)
                except Exception:
                    rid = None
                return str(text), rid
        except Exception:
            pass

        # Fallback extraction
        try:
            parts = []
            for item in getattr(resp, "output", []) or []:
                role = getattr(item, "role", None)
                for c in getattr(item, "content", []) or []:
                    ctype = getattr(c, "type", None)
                    # Only keep assistant output_text; drop reasoning or other types
                    if ctype == "output_text" and (role in (None, "assistant")):
                        t = getattr(getattr(c, "text", None), "value", None)
                        if t:
                            parts.append(t)
            try:
                joined = "\n".join(parts)
                preview = (joined[:500] + "…") if len(joined) > 500 else joined
                self.logger.debug(
                    "END OAI Responses.create (assembled)",
                    data={
                        "agent": getattr(self.agent, "name", "unknown"),
                        "output_preview": preview,
                    },
                )
                rid = None
                try:
                    rid = getattr(resp, "id", None)
                except Exception:
                    rid = None
                return joined, rid
            except Exception:
                rid = None
                try:
                    rid = getattr(resp, "id", None)
                except Exception:
                    rid = None
                return "\n".join(parts), rid
            self._last_tool_calls = tool_calls_total_local
        except Exception:
            return "", None

    async def generate(
        self,
        message: MessageLike,
        request_params: RequestParams | None = None,
    ) -> List[str]:
        params = self.get_request_params(request_params)

        # Conversation messages
        conv: List[dict[str, Any]] = []
        if self.instruction:
            conv.append(
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": self.instruction}],
                }
            )

        # Keep user message focused on the task; tool availability is provided via Responses tools
        conv.append({"role": "user", "content": [{"type": "input_text", "text": str(message)}]})

        max_iters = getattr(params, "max_iterations", 10) or 10
        final_text: Optional[str] = None
        tool_calls_total: int = 0
        wrote_file_path: Optional[str] = None
        last_response_id: Optional[str] = None
        for iter_idx in range(max_iters):
            # Call model
            kwargs_params = RequestParams(
                model=params.model,
                maxTokens=params.maxTokens,
                temperature=getattr(params, "temperature", 0.2),
            )
            try:
                self.logger.debug(
                    "LLM iteration start",
                    data={
                        "agent": getattr(self.agent, "name", "unknown"),
                        "iteration": iter_idx + 1,
                        "messages_in_conv": len(conv),
                    },
                )
            except Exception:
                pass
            response_text, rid = await self._call_openai(
                conv,
                kwargs_params,
                previous_response_id=last_response_id,
            )
            last_response_id = rid or last_response_id
            try:
                preview = (
                    (response_text[:1000] + "…")
                    if response_text and len(response_text) > 1000
                    else response_text
                )
                self.logger.debug(
                    "LLM raw response",
                    data={
                        "agent": getattr(self.agent, "name", "unknown"),
                        "iteration": iter_idx + 1,
                        "length": len(response_text or ""),
                        "preview": preview,
                    },
                )
            except Exception:
                pass

            # Treat model's response as final; function-call bridging occurs inside _call_openai
            if response_text and response_text.strip():
                final_text = response_text.strip()
                break

        # Best-effort: if this is the report_writer and no tool write occurred, try to write a valid JSON report.
        # Guardrail: never write terminal tokens (e.g., "SAVED: ...") as file contents.
        if (
            final_text
            and isinstance(final_text, str)
            and getattr(self, "agent", None)
            and getattr(self.agent, "name", "") == "report_writer"
        ):
            # Attempt to extract OUTPUT_PATH from prior user message
            try:
                ft = final_text.strip()
                if ft.startswith("SAVED:") or ft.startswith("ERROR:"):
                    # The writer prompt asks to emit only a terminal token; no fallback write needed.
                    ft = ""
                # Only attempt fallback write when we have something that looks like JSON.
                should_write = False
                if ft:
                    if ("```json" in ft) or ("'''json" in ft):
                        should_write = True
                    else:
                        try:
                            if isinstance(_extract_json_obj(ft), dict):
                                should_write = True
                        except Exception:
                            should_write = False
                if not should_write:
                    raise RuntimeError("skip_fallback_write: report_writer response not JSON")

                path_match = None
                # Search both developer and user messages for an absolute .md path
                for msg in conv:
                    txt = " ".join(
                        [
                            p.get("text", "")
                            for p in msg.get("content", [])
                            if p.get("type") == "input_text"
                        ]
                    )
                    m = re.search(r"(/[^\s\"']+\.md)", txt)
                    if m:
                        path_match = m.group(1)
                        break
                # If still not found, fall back to SENTIMENT_OUTPUT_DIR and a timestamped filename
                if not path_match:
                    try:
                        base_dir = (
                            getattr(self._settings(), "sentiment_output_dir", None)
                            or "/data/company_reports"
                        )
                        os.makedirs(base_dir, exist_ok=True)
                        from datetime import datetime as _dt

                        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
                        safe_agent = re.sub(
                            r"[^a-z0-9_\-]",
                            "_",
                            getattr(self.agent, "name", "report_writer").lower(),
                        )
                        path_match = os.path.join(base_dir, f"auto_report_{safe_agent}_{ts}.md")
                    except Exception:
                        pass
                if path_match:
                    # Discover a write-capable filesystem tool
                    tools_resp = await self.agent.list_tools()
                    write_tool = None
                    content_key = None
                    for t in tools_resp.tools:
                        schema = getattr(t, "inputSchema", {}) or {}
                        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
                        keys = {k.lower() for k in props.keys()}
                        if "path" in keys and (
                            "content" in keys
                            or "text" in keys
                            or "data" in keys
                            or "contents" in keys
                        ):
                            write_tool = t
                            if "content" in keys:
                                content_key = "content"
                            elif "text" in keys:
                                content_key = "text"
                            elif "contents" in keys:
                                content_key = "contents"
                            else:
                                content_key = "data"
                            break
                    if write_tool and content_key:
                        args = {"path": path_match, content_key: ft}
                        req = CallToolRequest(
                            method="tools/call",
                            params=CallToolRequestParams(name=write_tool.name, arguments=args),
                        )
                        try:
                            save_res = await self.call_tool(
                                request=req, tool_call_id="resp_tool_save"
                            )
                        except Exception:
                            try:
                                self.logger.error(
                                    "MCP tool call failed",
                                    exc_info=True,
                                    data={
                                        "agent": getattr(self.agent, "name", "unknown"),
                                        "call_id": "resp_tool_save",
                                        "name": getattr(write_tool, "name", None),
                                        "nested": False,
                                    },
                                )
                            except Exception:
                                pass
                            raise
                        try:
                            self.record_tool_use(
                                getattr(self.agent, "name", "unknown"), str(write_tool.name)
                            )
                        except Exception:
                            pass
                        try:
                            self.logger.debug(
                                "Fallback save attempted",
                                data={
                                    "tool": write_tool.name,
                                    "path": path_match,
                                    "isError": getattr(save_res, "isError", False),
                                },
                            )
                        except Exception:
                            pass
                        if not getattr(save_res, "isError", False):
                            wrote_file_path = path_match
                            try:
                                self.logger.debug(
                                    "Report saved via filesystem tool",
                                    data={
                                        "agent": getattr(self.agent, "name", "unknown"),
                                        "path": wrote_file_path,
                                    },
                                )
                            except Exception:
                                pass
                        else:
                            try:
                                self.logger.warning(
                                    "Filesystem write failed",
                                    data={
                                        "tool": getattr(write_tool, "name", None),
                                        "path": path_match,
                                    },
                                )
                            except Exception:
                                pass
            except Exception:
                pass
        # Summary line for observability
        tool_calls_total = getattr(self, "_last_tool_calls", 0)
        try:
            agent_name = getattr(self.agent, "name", "unknown")
            summary = {
                "agent": agent_name,
                "tool_calls": tool_calls_total,
                "wrote_file": bool(wrote_file_path),
            }
            if wrote_file_path:
                summary["path"] = wrote_file_path
            self.logger.info("Agent summary", data=summary)
        except Exception:
            pass
        return [final_text or ""]

    @staticmethod
    def _disallow_additional_props(schema: dict) -> None:
        if not isinstance(schema, dict):
            return
        t = schema.get("type")
        if t == "object":
            schema.setdefault("additionalProperties", False)
            props = schema.get("properties", {}) or {}
            for v in props.values():
                Gpt5ResponsesPlannerLLM._disallow_additional_props(v)
            # Ensure "required" is populated if missing
            if "required" not in schema and props:
                schema["required"] = list(props.keys())
        elif t == "array":
            items = schema.get("items")
            if isinstance(items, dict):
                Gpt5ResponsesPlannerLLM._disallow_additional_props(items)

    async def generate_str(
        self,
        message: MessageLike,
        request_params: RequestParams | None = None,
    ) -> str:
        params = self.get_request_params(request_params)
        result = await self.generate(message, params)
        return result[0] if result else ""

    async def generate_structured(
        self,
        message: MessageLike,
        response_model: Type[ModelT],
        request_params: RequestParams | None = None,
    ) -> ModelT:
        params = self.get_request_params(request_params)
        # Ensure prompt logger is wired for file capture
        prompt_logger = logging.getLogger("sentiment.prompts")
        try:
            log_path = getattr(self._settings(), "sentiment_log_file", None)
            if log_path:
                prompt_logger.setLevel(logging.DEBUG)
                # Attach if missing for this logger
                has_handler = any(
                    isinstance(h, RotatingFileHandler)
                    and getattr(h, "baseFilename", None) == log_path
                    for h in prompt_logger.handlers
                )
                if not has_handler:
                    fh = RotatingFileHandler(
                        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
                    )
                    fh.setLevel(logging.DEBUG)
                    fh.setFormatter(
                        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                    )
                    prompt_logger.addHandler(fh)
                    prompt_logger.propagate = False
        except Exception:
            pass
        # First attempt with enforced JSON response_format
        text, _rid = await self._call_openai(message, params, response_model=response_model)
        # Log raw text preview to the prompt logger for visibility
        try:
            prev = (text[:1000] + "…") if isinstance(text, str) and len(text) > 1000 else text
            prompt_logger.debug(
                "[PLANNER_FIRST_TEXT] agent=%s preview=%s",
                getattr(self.agent, "name", "unknown"),
                prev,
            )
        except Exception:
            pass
        model_fields = getattr(response_model, "model_fields", {}) or {}
        data = _extract_json_obj(text) or {}
        if isinstance(data, dict):
            try:
                if ("steps" in model_fields) and ("is_complete" in model_fields):
                    data = self._normalize_plan_data(data)
                if {"rating", "needs_improvement"}.issubset(set(model_fields.keys())):
                    data = self._normalize_evaluation_data(data)
                return response_model.model_validate(data)  # type: ignore[attr-defined]
            except Exception as e:
                try:
                    prompt_logger.debug(
                        "[STRUCT_VALIDATE_FAIL_FIRST] agent=%s error=%s keys=%s",
                        getattr(self.agent, "name", "unknown"),
                        str(e),
                        list(data.keys()),
                    )
                except Exception:
                    pass
        # If evaluator-like model expected, coerce from free text
        if isinstance(model_fields, dict) and {"rating", "feedback", "needs_improvement"}.issubset(
            set(model_fields.keys())
        ):
            minimal_example = (
                '{"rating": "2", "feedback": "short rationale", "needs_improvement": true}'
            )
            retry_prompt = (
                f"{str(message)}\n\nReturn ONLY a valid JSON object with exactly these keys: "
                f'\'rating\' ("0"|"1"|"2"|"3"), \'feedback\' (string), \'needs_improvement\' (boolean). '
                f"Map: 0=POOR, 1=FAIR, 2=GOOD, 3=EXCELLENT. "
                f"No markdown, no code fences, no extra text. Example: {minimal_example}"
            )
        else:
            # planner fallback (current behavior)
            minimal_example = (
                '{"steps": [{"description": "step description", '
                '"tasks": [{"description": "task", "agent": "financial_analyst"}]}], '
                '"is_complete": true}'
            )
            retry_prompt = (
                f"{str(message)}\n\nReturn ONLY a valid JSON object with exactly these keys: "
                f"'steps' (array) and 'is_complete' (boolean). "
                "If the context shows that 'research_quality_controller', 'financial_analyst', and "
                "'report_writer' have already run and the report was produced/saved, return steps=[] "
                "and is_complete=true. Otherwise list only remaining steps and set is_complete=false. "
                "No markdown, no code fences. Example: " + minimal_example
            )
        # Bump tokens and lower temperature for retry
        retry_params = RequestParams(
            model=params.model,
            maxTokens=max(params.maxTokens or 0, 3072),
            temperature=0.1,
        )
        text2, _rid2 = await self._call_openai(
            retry_prompt, retry_params, response_model=response_model
        )
        try:
            prev2 = (text2[:1000] + "…") if isinstance(text2, str) and len(text2) > 1000 else text2
            prompt_logger.debug(
                "[PLANNER_RETRY_TEXT] agent=%s preview=%s",
                getattr(self.agent, "name", "unknown"),
                prev2,
            )
        except Exception:
            pass
        data2 = _extract_json_obj(text2) or {}
        if isinstance(data2, dict):
            try:
                if ("steps" in model_fields) and ("is_complete" in model_fields):
                    data2 = self._normalize_plan_data(data2)
                if {"rating", "needs_improvement"}.issubset(set(model_fields.keys())):
                    data2 = self._normalize_evaluation_data(data2)
                return response_model.model_validate(data2)  # type: ignore[attr-defined]
            except Exception as e:
                try:
                    prompt_logger.debug(
                        "[STRUCT_VALIDATE_FAIL_RETRY] agent=%s error=%s keys=%s",
                        getattr(self.agent, "name", "unknown"),
                        str(e),
                        list(data2.keys()),
                    )
                except Exception:
                    pass
        if isinstance(model_fields, dict) and {"rating", "needs_improvement"}.issubset(
            set(model_fields.keys())
        ):
            coerced2 = self._coerce_evaluation_from_text(text2)
            if coerced2:
                try:
                    return response_model.model_validate(coerced2)  # type: ignore[attr-defined]
                except Exception:
                    pass
        # Last resort: synthesize a minimal object for known schemas
        if ("steps" in model_fields) and ("is_complete" in model_fields):
            fallback = {
                "steps": [
                    {
                        "description": "Collect high-quality research via research_quality_controller",
                        "tasks": [
                            {"description": "Gather data", "agent": "research_quality_controller"}
                        ],
                    },
                    {
                        "description": "Analyze research data",
                        "tasks": [{"description": "Analyze", "agent": "financial_analyst"}],
                    },
                    {
                        "description": "Write and save report",
                        "tasks": [{"description": "Write and save", "agent": "report_writer"}],
                    },
                ],
                "is_complete": False,
            }
        elif {"rating", "needs_improvement"}.issubset(set(model_fields.keys())):
            fallback = {
                "rating": "1",
                "feedback": "Auto-coerced from unstructured evaluator text.",
                "needs_improvement": True,
            }
        else:
            fallback = {}
        try:
            prompt_logger.debug("[STRUCT_FALLBACK] using synthesized object")
            return response_model.model_validate(fallback)  # type: ignore[attr-defined]
        except Exception:
            # Last resort: raise with context
            raise ValueError(
                "Failed to parse structured planner output: validation failed after retry"
            )
