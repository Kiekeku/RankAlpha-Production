"""
TradeExec Settings Configuration

Centralized configuration management using Pydantic BaseSettings.
Supports environment variables, .env files, and explicit configuration.
"""

import os
from datetime import time
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import AliasChoices, BaseModel, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.common.src.settings_base import ENV_DIR as _ENV_DIR

# Shared settings for cross-app configuration (DB, Gmail, Telegram, etc.)
from apps.common.src.settings_base import BaseAppSettings as CommonSettings


class TradingSystem(BaseModel):
    """Configuration for a single trading system."""

    name: str = Field(description="System name")
    position_allocation_percent: float = Field(description="Position allocation percentage (0-1)")
    trading_fund: str = Field(default="BuyingPower", description="Trading fund type")


class AccountConfig(BaseModel):
    """Configuration for a single trading account."""

    # Account identification
    account_number: str = Field(description="IB account number")

    @computed_field(return_type=str)
    def program_name(self):
        return f"BrokerExecution{self.account_number}"

    # OAuth configuration for broker connection (orders)
    broker_oauth_consumer_key: str = Field(description="OAuth consumer key for broker connection")
    broker_oauth_access_token: str = Field(description="OAuth access token for broker connection")
    broker_oauth_access_token_secret: str = Field(
        description="OAuth access token secret for broker connection"
    )
    broker_oauth_encryption_key_fp: str = Field(
        default="private_encryption.pem", description="Encryption key file for broker"
    )
    broker_oauth_signature_key_fp: str = Field(
        default="private_signature.pem", description="Signature key file for broker"
    )
    broker_oauth_dh_prime: Optional[str] = Field(None, description="DH prime for broker connection")

    # OAuth configuration for market data connection
    market_oauth_consumer_key: Optional[str] = Field(
        None, description="OAuth consumer key for market data (if different from broker)"
    )
    market_oauth_access_token: Optional[str] = Field(
        None, description="OAuth access token for market data"
    )
    market_oauth_access_token_secret: Optional[str] = Field(
        None, description="OAuth access token secret for market data"
    )
    market_oauth_encryption_key_fp: Optional[str] = Field(
        None, description="Encryption key file for market data"
    )
    market_oauth_signature_key_fp: Optional[str] = Field(
        None, description="Signature key file for market data"
    )
    market_oauth_dh_prime: Optional[str] = Field(
        None, description="DH prime for market data connection"
    )

    # Trading configuration
    trading_systems: List[TradingSystem] = Field(
        default_factory=list, description="List of trading systems"
    )
    execute_order: bool = Field(True, description="Whether to execute orders")
    use_snapshot: bool = Field(False, description="Use snapshot quotes")
    close_unaccounted_positions: bool = Field(True, description="Close positions not in database")
    wait_for_confirmation: bool = Field(
        False, description="Wait for user confirmation before orders"
    )
    optimize_price: bool = Field(False, description="Optimize order prices")
    hedge_threshold: float = Field(0.95, description="Hedge threshold (0-1)")

    def _resolve_key_file(self, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
        p = Path(v)
        if p.exists():
            return str(p)
        project_root = Path(__file__).parent.parent
        candidate = project_root / v
        if candidate.exists():
            return str(candidate)
        # Try env/{ENV}/broker and env/{ENV}
        try:
            from apps.common.src.settings_base import ENV_DIR as _ENV_DIR  # local import

            for c in [(_ENV_DIR / "broker" / v), (_ENV_DIR / v)]:
                if c.exists():
                    return str(c)
        except Exception:
            pass
        raise ValueError(f"Key file not found: {v}")

    def get_broker_oauth_params(self) -> dict:
        """Get OAuth parameters for broker connection."""
        return {
            "consumer_key": self.broker_oauth_consumer_key,
            "access_token": self.broker_oauth_access_token,
            "access_token_secret": self.broker_oauth_access_token_secret,
            "encryption_key_fp": self._resolve_key_file(self.broker_oauth_encryption_key_fp),
            "signature_key_fp": self._resolve_key_file(self.broker_oauth_signature_key_fp),
            "dh_prime": self.broker_oauth_dh_prime,
        }

    def get_market_oauth_params(self) -> dict:
        """Get OAuth parameters for market data connection."""
        # If market OAuth not specified, use broker OAuth
        if not self.market_oauth_consumer_key:
            return self.get_broker_oauth_params()

        return {
            "consumer_key": self.market_oauth_consumer_key,
            "access_token": self.market_oauth_access_token,
            "access_token_secret": self.market_oauth_access_token_secret,
            "encryption_key_fp": self._resolve_key_file(self.market_oauth_encryption_key_fp)
            if self.market_oauth_encryption_key_fp
            else self._resolve_key_file(self.broker_oauth_encryption_key_fp),
            "signature_key_fp": self._resolve_key_file(self.market_oauth_signature_key_fp)
            if self.market_oauth_signature_key_fp
            else self._resolve_key_file(self.broker_oauth_signature_key_fp),
            "dh_prime": self.market_oauth_dh_prime,
        }


class TradeExecSettings(BaseSettings):
    """
    TradeExec application settings with environment variable support.

    Environment variables are loaded automatically with the IB_ and TELEGRAM_ prefixes.
    Can also load from .env file in the project root.
    """

    # Prefer env/{ENV}/shared.env + broker.env for config; fall back to package .env for local
    _env_file_path = Path(__file__).parent.parent / ".env"

    model_config = SettingsConfigDict(
        env_file=[
            _ENV_DIR / "shared.env",
            _ENV_DIR / "broker.env",
            Path(__file__).parent.parent / ".env",
        ],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Multiple account support
    accounts: List[AccountConfig] = Field(
        default_factory=list, description="List of trading accounts"
    )

    ib_cacert_path: Optional[str] = Field(
        None, alias="IBIND_CACERT", description="Path to custom CA certificate bundle"
    )

    # Market hours configuration
    market_open_time: time = Field(
        default=time(9, 30),
        alias="MARKET_OPEN_TIME",
        description="Market open time (default 9:30 AM)",
    )
    market_close_time: time = Field(
        default=time(16, 0),
        alias="MARKET_CLOSE_TIME",
        description="Market close time (default 4:00 PM)",
    )

    # Market timezone (IANA, e.g., America/New_York). Runner converts UTC→this TZ
    # and evaluates MARKET_OPEN_TIME / MARKET_CLOSE_TIME in this timezone with DST.
    market_timezone: str = Field(
        "America/New_York", alias="MARKET_TIMEZONE", description="IANA timezone for market hours"
    )

    # Real-time signal handling toggles
    allow_realtime_without_system: bool = Field(
        False,
        alias="BROKER_ALLOW_REALTIME_WITHOUT_SYSTEM",
        description="Allow real-time signals without a system tag or not in the whitelist",
    )
    realtime_system_name: str = Field(
        "real-time",
        alias="BROKER_REALTIME_SYSTEM_NAME",
        description="Preferred system tag for live signals (use with whitelist)",
    )

    # Service API authentication (protects all routes except /health)
    service_token: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("BROKER_SERVICE_TOKEN", "AUTH_SERVICE_TOKEN"),
        description="Bearer/service token required for broker HTTP endpoints (except /health).",
    )

    # Test Configuration
    test_symbol: str = Field("AAPL", alias="TEST_SYMBOL", description="Symbol for testing")
    test_quantity: int = Field(1, alias="TEST_QUANTITY", description="Quantity for testing")
    test_telegram_bot_token: Optional[str] = Field(
        None, alias="TEST_TELEGRAM_BOT_TOKEN", description="Test Telegram bot token"
    )
    test_telegram_chat_id: Optional[str] = Field(
        None, alias="TEST_TELEGRAM_CHAT_ID", description="Test Telegram chat ID"
    )

    # Database configuration is now sourced from the shared CommonSettings (PostgreSQL)
    # Keep placeholders for backward compatibility but do not use them.
    database_url: Optional[str] = None
    database_server: Optional[str] = None
    database_name: Optional[str] = None
    database_username: Optional[str] = None
    database_password: Optional[str] = None
    database_driver: str = ""
    database_echo: bool = False

    @field_validator("ib_cacert_path")
    def validate_cacert_exists(cls, v):
        """Validate that CA certificate file exists if specified."""
        if v and not Path(v).exists():
            raise ValueError(f"CA certificate file not found: {v}")
        return v

    def get_ib_oauth_params(self) -> dict:
        """
        Get Interactive Brokers OAuth parameters as a dictionary.
        This method is for backward compatibility with single account setup.

        Returns:
            dict: OAuth parameters suitable for IBInterfacing oauth_params
        """
        if not all(
            [
                self.ib_oauth_consumer_key,
                self.ib_oauth_access_token,
                self.ib_oauth_access_token_secret,
            ]
        ):
            return {}

        params = {
            "consumer_key": self.ib_oauth_consumer_key,
            "access_token": self.ib_oauth_access_token,
            "access_token_secret": self.ib_oauth_access_token_secret,
            "encryption_key_fp": self.ib_oauth_encryption_key_fp,
            "signature_key_fp": self.ib_oauth_signature_key_fp,
        }

        if self.ib_oauth_dh_prime:
            params["dh_prime"] = self.ib_oauth_dh_prime

        return params

    def get_account_config(self, account_number: str) -> Optional[AccountConfig]:
        """
        Get configuration for a specific account.

        Args:
            account_number: The IB account number

        Returns:
            AccountConfig if found, None otherwise
        """
        for account in self.accounts:
            if account.account_number == account_number:
                return account
        return None

    def load_accounts_from_env(self) -> None:
        """
        Load multiple account configurations from environment variables or the .env file.
        Supports the pattern: ACCOUNT1_*, ACCOUNT2_*, etc.

        Note: We cannot rely on os.getenv alone because BaseSettings reads from
        the .env file without exporting values into os.environ. To be robust,
        read from os.environ first, then fall back to parsing the .env file.
        """
        # Build an env map from configured env files for fallback lookups.
        # This matters because pydantic env_file loading does not export values
        # into os.environ, and we need ACCOUNT{N}_* keys for multi-account config.
        env_map: Dict[str, str] = {}
        try:
            env_files: list[Path] = []
            cfg = getattr(type(self), "model_config", {}) or {}
            configured = cfg.get("env_file") or []
            if isinstance(configured, (str, Path)):
                configured = [configured]
            for p in configured:
                if p:
                    env_files.append(Path(p))
            # Explicit local fallback (apps/broker/.env)
            if getattr(self, "_env_file_path", None):
                env_files.append(Path(self._env_file_path))

            seen: set[str] = set()
            for env_path in env_files:
                sp = str(env_path)
                if sp in seen:
                    continue
                seen.add(sp)
                if not env_path.exists():
                    continue
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    env_map[key.strip()] = val.strip().strip('"').strip("'")
        except Exception:
            # Ignore env file parsing errors – we'll rely on os.environ only
            env_map = {}

        def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
            val = os.getenv(key)
            if val is not None and val != "":
                return val
            return env_map.get(key, default)

        accounts: List[AccountConfig] = []
        account_index = 1

        while True:
            prefix = f"ACCOUNT{account_index}_"
            account_number = get_env(f"{prefix}ACCOUNT_NUMBER")

            if not account_number:
                break

            # Load trading systems for this account
            systems: List[TradingSystem] = []
            system_index = 1
            while True:
                system_name = get_env(f"{prefix}SYSTEM_NAME{system_index}")
                if not system_name:
                    break

                alloc_str = get_env(f"{prefix}POSITION_ALLOCATION_PERCENT{system_index}", "0.25")
                trading_fund = (
                    get_env(f"{prefix}TRADING_FUND{system_index}", "BuyingPower") or "BuyingPower"
                )

                systems.append(
                    TradingSystem(
                        name=system_name,
                        position_allocation_percent=float(alloc_str or "0.25"),
                        trading_fund=trading_fund,
                    )
                )
                system_index += 1

            # Create account config
            account = AccountConfig(
                account_number=account_number,
                broker_oauth_consumer_key=get_env(f"{prefix}BROKER_OAUTH_CONSUMER_KEY", "") or "",
                broker_oauth_access_token=get_env(f"{prefix}BROKER_OAUTH_ACCESS_TOKEN", "") or "",
                broker_oauth_access_token_secret=get_env(
                    f"{prefix}BROKER_OAUTH_ACCESS_TOKEN_SECRET", ""
                )
                or "",
                broker_oauth_encryption_key_fp=get_env(
                    f"{prefix}BROKER_OAUTH_ENCRYPTION_KEY_FP", "private_encryption.pem"
                )
                or "private_encryption.pem",
                broker_oauth_signature_key_fp=get_env(
                    f"{prefix}BROKER_OAUTH_SIGNATURE_KEY_FP", "private_signature.pem"
                )
                or "private_signature.pem",
                broker_oauth_dh_prime=get_env(f"{prefix}BROKER_OAUTH_DH_PRIME"),
                market_oauth_consumer_key=get_env(f"{prefix}MARKET_OAUTH_CONSUMER_KEY"),
                market_oauth_access_token=get_env(f"{prefix}MARKET_OAUTH_ACCESS_TOKEN"),
                market_oauth_access_token_secret=get_env(
                    f"{prefix}MARKET_OAUTH_ACCESS_TOKEN_SECRET"
                ),
                market_oauth_encryption_key_fp=get_env(f"{prefix}MARKET_OAUTH_ENCRYPTION_KEY_FP"),
                market_oauth_signature_key_fp=get_env(f"{prefix}MARKET_OAUTH_SIGNATURE_KEY_FP"),
                market_oauth_dh_prime=get_env(f"{prefix}MARKET_OAUTH_DH_PRIME"),
                trading_systems=systems,
                execute_order=(get_env(f"{prefix}EXECUTE_ORDER", "True") or "True").lower()
                == "true",
                use_snapshot=(get_env(f"{prefix}USE_SNAPSHOT", "False") or "False").lower()
                == "true",
                close_unaccounted_positions=(
                    get_env(f"{prefix}CLOSE_UNACCOUNTED_POSITIONS", "True") or "True"
                ).lower()
                == "true",
                wait_for_confirmation=(
                    get_env(f"{prefix}WAIT_FOR_CONFIRMATION", "False") or "False"
                ).lower()
                == "true",
                optimize_price=(get_env(f"{prefix}OPTIMIZE_PRICE", "False") or "False").lower()
                == "true",
                hedge_threshold=float(get_env(f"{prefix}HEDGE_THRESHOLD", "0.95") or "0.95"),
            )

            accounts.append(account)
            account_index += 1

        if accounts:
            self.accounts = accounts

    # --- Bridge to shared (common) settings for cross‑app config ---------
    # Defer instantiation to avoid import‑time validation failures when
    # the shared env (DB, API) is not present. Cache the instance if loaded.
    def _get_common(self) -> Optional[CommonSettings]:
        try:
            cached = getattr(self, "_common_cached", None)
            if cached is not None:
                return cached
            inst = CommonSettings()
            setattr(self, "_common_cached", inst)
            return inst
        except Exception:
            setattr(self, "_common_cached", None)
            return None

    @property
    def telegram_bot_token(self) -> Optional[str]:
        c = self._get_common()
        return c.telegram_bot_token if c else None

    @property
    def telegram_chat_id(self) -> Optional[str]:
        c = self._get_common()
        return c.telegram_chat_id if c else None

    @property
    def gmail_sender(self) -> Optional[str]:
        c = self._get_common()
        return c.gmail_sender if c else None

    @property
    def gmail_recipient(self) -> Optional[str]:
        c = self._get_common()
        return c.gmail_recipient if c else None

    def get_telegram_config(self) -> dict:
        """
        Get Telegram configuration as a dictionary.

        Returns:
            dict: Telegram configuration with bot_token and chat_id
        """
        return {
            "bot_token": self.telegram_bot_token,
            "chat_id": self.telegram_chat_id,
        }

    def get_test_telegram_config(self) -> dict:
        """
        Get test Telegram configuration as a dictionary.

        Returns:
            dict: Test Telegram configuration with bot_token and chat_id
        """
        return {
            "bot_token": self.test_telegram_bot_token,
            "chat_id": self.test_telegram_chat_id,
        }

    def get_database_config(self) -> dict:
        """
        Get database configuration as a dictionary.

        Returns:
            dict: Database configuration parameters
        """
        # Build a SQLAlchemy URL for PostgreSQL using the shared CommonSettings
        # Fall back to DATABASE_URL if provided.
        from urllib.parse import quote

        # Prefer explicit DATABASE_URL if provided
        if self.database_url:
            return {"url": self.database_url, "echo": False}

        # Attempt to build from common settings; return minimal dict if unavailable
        c = self._get_common()
        if c is None:
            return {"url": None, "echo": False}

        user = c.db_username
        pwd = c.password
        host = c.host
        port = c.port
        db = c.database_name
        url = f"postgresql+psycopg2://{quote(user)}:{quote(pwd)}@{host}:{port}/{db}"
        return {"url": url, "echo": bool(c.db_echo)}


# Global settings instance
settings = TradeExecSettings()
settings.load_accounts_from_env()
