# RankAlpha Schema (Core)

This ERD is a **high-level** view of the core tables used by ingestion, scoring,
news/sentiment, and trading. It is not exhaustive; refer to `docs/schemas.md`
for the full list of tables and views.

```mermaid
erDiagram
    dim_date {
        INT date_key PK
        DATE full_date
        BOOLEAN is_trading_day
    }
    dim_asset_type {
        INT asset_type_key PK
        VARCHAR asset_type_name
    }
    dim_stock {
        INT stock_key PK
        VARCHAR symbol
        CHAR currency_code
        BOOLEAN is_active
        INT asset_type_key FK
    }
    dim_source {
        INT source_key PK
        VARCHAR source_name
    }
    dim_style {
        INT style_key PK
        VARCHAR style_name
    }
    dim_score_type {
        INT score_type_key PK
        VARCHAR score_type_name
    }
    dim_fin_metric {
        INT metric_key PK
        VARCHAR metric_code
    }
    dim_confidence {
        INT confidence_key PK
        VARCHAR confidence_label
    }
    dim_timeframe {
        INT timeframe_key PK
        VARCHAR timeframe_label
    }
    portfolio {
        UUID portfolio_id PK
        VARCHAR portfolio_name
        VARCHAR portfolio_kind
        CHAR currency_code
    }
    portfolio_cash_position {
        UUID portfolio_id FK
        CHAR currency_code
        DECIMAL cash_amount
    }
    portfolio_policy_version {
        BIGINT policy_id PK
        UUID portfolio_id FK
        DATE effective_from
        DATE effective_to
        DECIMAL target_vol
    }
    portfolio_deployment {
        UUID deployment_id PK
        UUID broker_portfolio_id FK
        UUID model_portfolio_id FK
        UUID sleeve_portfolio_id FK
        DECIMAL allocation_pct
    }
    portfolio_run {
        UUID run_id PK
        UUID portfolio_id FK
        VARCHAR run_kind
        DATE as_of_date
        INT run_seq
        VARCHAR status
    }
    portfolio_order_intent {
        UUID order_id PK
        UUID run_id FK
        INT line_no
        INT stock_key FK
        VARCHAR action
        DECIMAL qty_shares
        VARCHAR approval_status
    }
    portfolio_run_position {
        UUID position_id PK
        UUID run_id FK
        VARCHAR position_role
        VARCHAR instrument_type
        INT stock_key FK
        CHAR currency_code
        DECIMAL quantity
    }
    fact_internal_cross {
        UUID cross_id PK
        UUID broker_run_id FK
        INT stock_key FK
        UUID buy_sleeve_portfolio_id FK
        UUID sell_sleeve_portfolio_id FK
    }

    fact_security_price {
        INT date_key FK
        INT stock_key FK
    }
    fact_technical_indicator {
        INT date_key FK
        INT stock_key FK
        VARCHAR indicator_code
    }
    fact_score_history {
        INT date_key FK
        INT stock_key FK
        INT source_key FK
        INT score_type_key FK
    }
    fact_screener_rank {
        INT date_key FK
        INT stock_key FK
        INT source_key FK
        INT style_key FK
        INT rank_value
    }
    fact_screener_rank_change {
        INT change_date_key FK
        INT stock_key FK
        INT source_key FK
        INT style_key FK
    }
    fact_fin_fundamentals {
        INT date_key FK
        INT stock_key FK
        INT source_key FK
        INT metric_key FK
    }
    fact_news_articles {
        INT article_date FK
        UUID article_id PK
        INT stock_key FK
        INT source_key FK
    }
    fact_news_sentiment {
        UUID article_id PK
        DECIMAL sentiment_score
    }
    fact_trade_recommendation {
        UUID recommendation_id PK
        INT date_key FK
        INT stock_key FK
        INT source_key FK
        INT confidence_key FK
        INT timeframe_key FK
        UUID portfolio_id FK
    }
    fact_portfolio_trade {
        UUID trade_id PK
        UUID portfolio_id FK
        INT stock_key FK
    }

    dim_asset_type ||--o{ dim_stock : asset_type
    dim_date ||--o{ fact_security_price : date
    dim_stock ||--o{ fact_security_price : stock
    dim_date ||--o{ fact_technical_indicator : date
    dim_stock ||--o{ fact_technical_indicator : stock
    dim_date ||--o{ fact_score_history : date
    dim_stock ||--o{ fact_score_history : stock
    dim_source ||--o{ fact_score_history : source
    dim_score_type ||--o{ fact_score_history : score_type
    dim_date ||--o{ fact_screener_rank : date
    dim_stock ||--o{ fact_screener_rank : stock
    dim_source ||--o{ fact_screener_rank : source
    dim_style ||--o{ fact_screener_rank : style
    dim_date ||--o{ fact_screener_rank_change : change_date
    dim_stock ||--o{ fact_screener_rank_change : stock
    dim_source ||--o{ fact_screener_rank_change : source
    dim_style ||--o{ fact_screener_rank_change : style
    dim_date ||--o{ fact_fin_fundamentals : date
    dim_stock ||--o{ fact_fin_fundamentals : stock
    dim_source ||--o{ fact_fin_fundamentals : source
    dim_fin_metric ||--o{ fact_fin_fundamentals : metric
    dim_date ||--o{ fact_news_articles : article_date
    dim_stock ||--o{ fact_news_articles : stock
    dim_source ||--o{ fact_news_articles : source
    fact_news_articles ||--|| fact_news_sentiment : article
    dim_date ||--o{ fact_trade_recommendation : date
    dim_stock ||--o{ fact_trade_recommendation : stock
    dim_source ||--o{ fact_trade_recommendation : source
    dim_confidence ||--o{ fact_trade_recommendation : confidence
    dim_timeframe ||--o{ fact_trade_recommendation : timeframe
    portfolio ||--o{ fact_trade_recommendation : portfolio
    portfolio ||--o{ fact_portfolio_trade : portfolio
    dim_stock ||--o{ fact_portfolio_trade : stock

    %% Portfolio construction / deployment (high-level)
    portfolio ||--o{ portfolio_cash_position : cash
    portfolio ||--o{ portfolio_policy_version : policy_version
    portfolio ||--o{ portfolio_deployment : broker
    portfolio ||--o{ portfolio_deployment : model
    portfolio ||--o{ portfolio_deployment : sleeve
    portfolio ||--o{ portfolio_run : run
    portfolio_run ||--o{ portfolio_order_intent : order_intent
    portfolio_run ||--o{ portfolio_run_position : run_position
    dim_stock ||--o{ portfolio_order_intent : stock
    dim_stock ||--o{ portfolio_run_position : stock
    portfolio_run ||--o{ fact_internal_cross : broker_run
    dim_stock ||--o{ fact_internal_cross : stock
    portfolio ||--o{ fact_internal_cross : buy_sleeve
    portfolio ||--o{ fact_internal_cross : sell_sleeve
```
