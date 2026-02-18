-- V1__initial_schema.sql
-- 1️⃣ Extensions & base schema + tables

-- extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- namespace
CREATE SCHEMA IF NOT EXISTS rankalpha;
SET search_path = rankalpha, public;

-- dimension tables
CREATE TABLE IF NOT EXISTS dim_stock (
    stock_key      SERIAL PRIMARY KEY,
    symbol         VARCHAR(20)  NOT NULL UNIQUE,
    company_name   TEXT,
    sector         TEXT,
    exchange       TEXT
);

CREATE TABLE IF NOT EXISTS dim_source (
    source_key     SERIAL PRIMARY KEY,
    source_name    VARCHAR(50) NOT NULL UNIQUE,
    version        VARCHAR(20) NOT NULL DEFAULT '1'
);

CREATE TABLE IF NOT EXISTS dim_style (
    style_key      SERIAL PRIMARY KEY,
    style_name     VARCHAR(50) NOT NULL UNIQUE
);

-- date dimension
CREATE TABLE IF NOT EXISTS dim_date (
    date_key       INTEGER     PRIMARY KEY,          -- YYYYMMDD
    full_date      DATE        NOT NULL UNIQUE,
    day_of_week    SMALLINT    NOT NULL,             -- 0 = Sun
    month_num      SMALLINT    NOT NULL,
    month_name     VARCHAR(10) NOT NULL,
    quarter        SMALLINT    NOT NULL,
    calendar_year  SMALLINT    NOT NULL,
    is_trading_day BOOLEAN     NOT NULL DEFAULT TRUE
);

-- fact table (partitioned by calendar month)
CREATE TABLE IF NOT EXISTS fact_screener_rank (
    date_key        INT  NOT NULL REFERENCES dim_date(date_key),
    fact_id         UUID NOT NULL DEFAULT uuid_generate_v4(),

    stock_key       INT  NOT NULL REFERENCES dim_stock(stock_key),
    source_key      INT  NOT NULL REFERENCES dim_source(source_key),
    style_key       INT           REFERENCES dim_style(style_key),

    rank_value      INT  NOT NULL,
    screening_runid UUID NOT NULL,
    load_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (date_key, fact_id)
) PARTITION BY RANGE (date_key);
