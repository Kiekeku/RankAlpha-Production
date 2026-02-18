import pandas as pd


class PriceReader:
    _DATE_INDEX_CANDIDATES = ("Date", "__index_level_0__", "Datetime", "Timestamp")

    @staticmethod
    def _is_numeric_index(idx: pd.Index) -> bool:
        if isinstance(idx, pd.RangeIndex):
            return True
        try:
            return bool(pd.api.types.is_numeric_dtype(getattr(idx, "dtype", None)))
        except Exception:
            return False

    @staticmethod
    def _apply_datetime_index_from_columns(
        df: pd.DataFrame, source_df: pd.DataFrame
    ) -> pd.DataFrame | None:
        for candidate in PriceReader._DATE_INDEX_CANDIDATES:
            if candidate not in source_df.columns:
                continue
            try:
                parsed = pd.to_datetime(source_df[candidate], errors="coerce")
                if parsed.notna().any() and len(parsed) == len(df.index):
                    out = df.copy()
                    out.index = parsed
                    return out
            except Exception:
                continue
        return None

    @staticmethod
    def _coerce_datetime_index(
        df: pd.DataFrame, *, full_df: pd.DataFrame | None = None
    ) -> pd.DataFrame:
        if isinstance(df.index, pd.DatetimeIndex):
            return df
        if full_df is not None and isinstance(full_df.index, pd.DatetimeIndex):
            return full_df

        # Prefer explicit date-like columns from the same frame, then from the full frame.
        from_self = PriceReader._apply_datetime_index_from_columns(df, df)
        if from_self is not None:
            return from_self
        if full_df is not None:
            from_full = PriceReader._apply_datetime_index_from_columns(df, full_df)
            if from_full is not None:
                return from_full

        # Never coerce numeric/range indexes into epoch nanoseconds.
        if PriceReader._is_numeric_index(df.index):
            return df

        try:
            parsed = pd.to_datetime(df.index, errors="coerce")
            if parsed.notna().any():
                out = df.copy()
                out.index = parsed
                return out
        except Exception:
            pass
        return df

    @staticmethod
    def normalize_parquet_columns(df: pd.DataFrame) -> pd.DataFrame:
        cols = df.columns
        out = df.copy()
        if isinstance(cols, pd.MultiIndex):
            flat: list[str] = []
            for tup in cols:
                parts = [str(p) for p in tup if p is not None and str(p) != ""]
                name = "_".join(parts) if parts else ""
                for base in ("Open", "High", "Low", "Close", "Adj Close", "Volume"):
                    if name.startswith(base):
                        name = base
                        break
                flat.append(name or "col")
            out.columns = pd.Index(flat, dtype=object)
        else:
            out.columns = pd.Index([str(c).strip() for c in cols], dtype=object)
        if not out.columns.is_unique:
            seen = {}
            uniq = []
            for c in out.columns:
                if c in seen:
                    seen[c] += 1
                    uniq.append(f"{c}__{seen[c]}")
                else:
                    seen[c] = 0
                    uniq.append(c)
            out.columns = pd.Index(uniq, dtype=object)
        return out

    @staticmethod
    def read_price_parquet(path: str, logger, prefer_full_ohlcv: bool = False) -> pd.DataFrame:
        """Robust read with index repair and hygiene.

        By default, attempts a minimal-column read first for speed. When
        prefer_full_ohlcv is True, attempts to load canonical OHLCV columns
        first (needed for price×volume factors like money flow).
        """
        last_exc = None
        df = None
        col_sets = (
            (
                ["Adj Close", "Close", "Open", "High", "Low", "Volume"],
                ["Close", "Open", "High", "Low", "Volume"],
                ["Adj Close", "Close"],
                ["Adj Close"],
                ["Close"],
            )
            if prefer_full_ohlcv
            else (
                ["Adj Close"],
                ["Adj Close", "Close"],
                ["Adj Close", "Close", "Open", "High", "Low", "Volume"],
                ["Close"],
                ["Close", "Open", "High", "Low", "Volume"],
            )
        )
        for cols in col_sets:
            try:
                df = pd.read_parquet(path, engine="pyarrow", columns=cols)
                break
            except Exception as exc:
                last_exc = exc
                continue
        else:
            try:
                df = pd.read_parquet(path, engine="pyarrow")
            except Exception:
                raise last_exc

        # Ensure datetime index; first try restoring from a full read's metadata
        try:
            if not isinstance(df.index, pd.DatetimeIndex):
                df_full = None
                try:
                    df_full = pd.read_parquet(path, engine="pyarrow")
                except Exception:
                    df_full = None
                df = PriceReader._coerce_datetime_index(df, full_df=df_full)
        except Exception:
            pass
        # Normalize column names and index hygiene
        df = PriceReader.normalize_parquet_columns(df)
        try:
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_localize(None)
            df = df[~df.index.duplicated(keep="last")].sort_index()
        except Exception:
            pass
        return df

    @staticmethod
    def select_close(df: pd.DataFrame) -> pd.Series:
        if "Adj Close" in df.columns:
            s = pd.to_numeric(df["Adj Close"], errors="coerce")
            if not s.dropna().empty:
                return s.astype(float)
        if "Close" in df.columns:
            s = pd.to_numeric(df["Close"], errors="coerce")
            if not s.dropna().empty:
                return s.astype(float)
        return pd.Series(index=df.index, dtype=float)

    @staticmethod
    def round2(value, max_abs: float = 9_999_999_999.99):
        if value is None:
            return None
        try:
            if hasattr(value, "item") and not isinstance(value, (pd.Series, pd.DataFrame)):
                value = value.item()
            if isinstance(value, pd.Series):
                if value.empty:
                    return None
                value = value.iloc[-1]
            if isinstance(value, pd.DataFrame):
                if value.empty:
                    return None
                value = value.iloc[-1].iloc[-1]
            v = float(value)
        except Exception:
            return None
        if pd.isna(v) or abs(v) > max_abs:
            return None
        return float(f"{v:.2f}")

    @staticmethod
    def get_latest_date_key(df) -> int | None:
        try:
            idx = df.index
            if not isinstance(idx, pd.DatetimeIndex):
                idx = pd.to_datetime(idx, errors="coerce")
            last_ts = pd.to_datetime(idx, errors="coerce").max()
        except Exception:
            last_ts = None
        if last_ts is None or pd.isna(last_ts):
            return None
        try:
            y = int(last_ts.year)
            if y < 1980 or y > 2100:
                return None
            return int(last_ts.date().strftime("%Y%m%d"))
        except Exception:
            return None
