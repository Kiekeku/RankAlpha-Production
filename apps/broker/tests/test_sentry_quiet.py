from tradeexec.utils.sentry_quiet import is_ibkr_maintenance_error


def test_is_ibkr_maintenance_error_max_retry_tickle() -> None:
    exc = Exception(
        "MaxRetryError: HTTPSConnectionPool(host='api.ibkr.com', port=443): "
        "Max retries exceeded with url: /v1/api/tickle (Caused by ..."
    )
    assert is_ibkr_maintenance_error(exc)


def test_is_ibkr_maintenance_error_remote_end_closed_connection() -> None:
    exc = Exception(
        "ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection'))"
    )
    assert is_ibkr_maintenance_error(exc)


def test_is_ibkr_maintenance_error_ssodh_gone() -> None:
    exc = Exception(
        "HTTPError: 410 Client Error: Gone for url: https://api.ibkr.com/v1/api/iserver/auth/ssodh/init"
    )
    assert is_ibkr_maintenance_error(exc)


def test_is_ibkr_maintenance_error_snapshot_price_failed() -> None:
    exc = Exception("Snapshot price request failed")
    assert is_ibkr_maintenance_error(exc)


def test_is_ibkr_maintenance_error_live_session_token_dns() -> None:
    exc = Exception(
        "IbkrClient: request error: HTTPSConnectionPool(host='api.ibkr.com', port=443): "
        "Max retries exceeded with url: /v1/api/oauth/live_session_token "
        '(Caused by NameResolutionError("<urllib3.connection.HTTPSConnection object at 0x7b81a1fc5f70>: '
        "Failed to resolve 'api.ibkr.com'\"))"
    )
    assert is_ibkr_maintenance_error(exc)
