# RankAlpha Architecture (Docker Compose)

The diagram below reflects the current Docker‑Compose stack, services, and data flows.

Rendered image (SVG):

![RankAlpha Architecture](images/architecture.svg)

```mermaid
flowchart TD
  %% ================= Data Sources =================
  subgraph SRC[Sources]
    YF["yfinance<br/>(OHLCV)"]
    NEWS["News + Web + Filings<br/>(EDGAR + Google)"]
    SCR["Screeners<br/>(styles/sources)"]
    IBKR["IBKR Client Portal / Web API"]
  end

  %% ================= Services =================
  subgraph SVC[Services]
    ING["Ingestion<br/>- Download prices<br/>- Canonical Parquet<br/>- Compute technicals<br/>- Sync DB + is_active"]
    SCO["Scorer<br/>- Momentum (R^2 blend)<br/>- Valuation (fundamentals)<br/>- Hybrid weights (IC + RP)<br/>- Screener deltas (MV + facts)"]
    SEN["Sentiment (multi-agent)<br/>- AI analyses & factors<br/>- Scenarios<br/>- Optional consensus batch"]
    NW["Newswire<br/>- GDELT/Serper/RSS<br/>- Dedup/cluster<br/>- Prefilter materiality<br/>- Material events + impacts"]
    AFX["Airflow DAG<br/>- Orchestrates containers<br/>- Calls API refresh<br/>- Notifies frontend"]
    REDIS["Redis cache"]
  end

  %% ================= Storage =================
  subgraph STG[Storage]
    PARQ["prices volume<br/>/data/prices"]
    PG["Postgres<br/>rankalpha schema"]
  end

  %% ================= API/UI =================
  subgraph APIUI[API & UI]
    API["FastAPI<br/>routers (non-exhaustive): grading, prices, technicals, signals, screener, ai-analysis, news, macro, rates, fx, trading, backtest, admin<br/>auto-CRUD (read-only in prod)"]
    FE["Next.js 14<br/>(App Router)"]
  end

  %% ================= Observability =================
  subgraph OBS[Observability]
    OTEL["otel-collector<br/>(OTLP fan-out)"]
    PROM["Prometheus<br/>(metrics)"]
    TEMPO["Tempo<br/>(traces)"]
    LOKI["Loki + Promtail<br/>(logs)"]
    GRAF["Grafana<br/>(dashboards/alerts)"]
  end

  %% ================= Flows =================
  YF --> ING
  ING --> PARQ
  ING --> PG
  PARQ --> SCO
  SCR --> SCO
  NEWS --> NW
  NW --> PG
  NW --> AFX
  NEWS --> SEN
  SEN --> PG
  SCO --> PG
  AFX --> ING
  AFX --> SCO
  AFX --> SEN
  PG --> API
  API --> REDIS
  API --> FE
  AFX --> API

  %% ================= Broker (Trade Execution) =================
  subgraph BRK[Broker]
    BRKAPI["Broker FastAPI<br/>(signals, health)"]
    BRKRUN["Per-account runner<br/>- Order placement (IBKR)<br/>- Fills ingest -> fact_portfolio_trade<br/>- Idempotence via fact_trade_recommendation"]
  end
  API --> BRKAPI
  BRKAPI --> BRKRUN
  BRKRUN --> PG
  BRKRUN --> IBKR
  IBKR --> BRKRUN

  %% ================= Observability flows =================
  ING --> OTEL
  SCO --> OTEL
  SEN --> OTEL
  NW --> OTEL
  API --> OTEL
  BRKAPI --> OTEL
  OTEL --> PROM
  OTEL --> TEMPO
  PROM --> GRAF
  TEMPO --> GRAF
  LOKI --> GRAF

  %% ================= Notable DB objects =================
  classDef dim fill:#eef5ff,stroke:#2f5597,stroke-width:1px
  classDef fact fill:#f7f0ff,stroke:#6b2fb3,stroke-width:1px
  classDef mv fill:#fff7e6,stroke:#b37f00,stroke-width:1px
  classDef view fill:#e8fff3,stroke:#228b22,stroke-width:1px

  %% Legends (textual)
  %% dims: dim_stock, dim_date, dim_score_type
  %% facts: fact_security_price, fact_technical_indicator, fact_score_history, fact_screener_rank_change, (optional) fact_news_sentiment, fact_ai_stock_analysis
  %% mvs: mv_latest_grades, mv_screener_changes, mv_screener_breadth, mv_ai_scenario_proximity, mv_latest_material_news
  %% views: vw_stock_price_history, vw_latest_adj_close, vw_latest_technicals, vw_ai_analysis_full, vw_ai_analysis_latest, vw_news_by_symbol
```

## Regenerating the diagram

The rendered image is generated from `docs/diagrams/architecture.mmd` via Kroki:

```bash
make diagrams
```

This writes fresh renders to `docs/images/architecture.{svg,png}` and copies `docs/images/architecture.svg` to `apps/frontend/public/images/architecture.svg` for the About page.

## Notes

- Ingestion canonicalizes Parquet (`Open, High, Low, Close, Adj Close, Volume`), computes daily technicals, and syncs Adj Close/price history to Postgres.
- Scorer writes momentum/value metrics to `fact_score_history`, computes hybrid weights (IC + RP) into `dim_model_weight` (+ versioned tables), and persists screener deltas.
- Sentiment persists AI analyses/factors and scenarios (primary store: `fact_ai_stock_analysis` and related views like `vw_ai_analysis_latest`); sentiment is optional in the grading composite.
- Newswire collects and de‑dups news (GDELT/Serper/RSS), runs a cheap first‑pass materiality filter, and writes raw/cluster/event/impact tables powering `mv_latest_material_news` and `vw_news_by_symbol`.
- API serves DB-backed reads; Redis wraps GET responses. Airflow triggers refresh endpoints after batch runs and can notify the frontend (`/api/refresh-data`) when enabled.

## Observability & Telemetry

- Application traces and metrics are emitted via OpenTelemetry exporters configured in `apps/common/src/observability.py`.
- The default Docker stack deploys `otel-collector` (OTLP fan-out), `prometheus` (metrics store), `tempo` (trace store), `grafana` (dashboards/alerts), `loki` + `promtail` (centralised logs), and `cadvisor` (container resource telemetry).
- Host-level port collisions between stacks are avoided by overriding telemetry ports (`PROMETHEUS_PORT`, `GRAFANA_PORT`, `INGESTION_METRICS_PORT`, etc.) via per-stack `.compose.env` files.
