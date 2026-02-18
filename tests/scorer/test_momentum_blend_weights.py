import importlib.util
import sys
import types
from pathlib import Path


def _install_minimal_stubs():
    """Install minimal module stubs so we can import scorer main without heavy deps.

    We only exercise `_blend_momentum_series`, which doesn't touch pandas/DB.
    """
    # pandas stub with minimal names used in type hints
    if 'pandas' not in sys.modules:
        pandas_stub = types.ModuleType('pandas')
        class _DF: ...
        class _Series(list):
            def __mul__(self, other):
                return _Series([x * other for x in self])
            __rmul__ = __mul__
            def __add__(self, other):
                return _Series([x + y for x, y in zip(self, other)])
        pandas_stub.DataFrame = _DF
        pandas_stub.Series = _Series
        sys.modules['pandas'] = pandas_stub

    # psycopg2 + sqlalchemy stubs
    if 'psycopg2' not in sys.modules:
        sys.modules['psycopg2'] = types.ModuleType('psycopg2')
    if 'sqlalchemy' not in sys.modules:
        sa = types.ModuleType('sqlalchemy')
        sa.create_engine = lambda *a, **k: None
        sys.modules['sqlalchemy'] = sa

    # apps.common.src.logging stub
    for name in ['apps', 'apps.common', 'apps.common.src']:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    log_mod = types.ModuleType('apps.common.src.logging')
    def _get_logger(_):
        class _L:
            def info(self, *a, **k):
                return None
        return _L()
    log_mod.get_logger = _get_logger
    sys.modules['apps.common.src.logging'] = log_mod

    # apps.common.src.settings stub
    settings_mod = types.ModuleType('apps.common.src.settings')
    class _Settings:  # minimal placeholder
        pass
    settings_mod.Settings = _Settings
    sys.modules['apps.common.src.settings'] = settings_mod


def _import_scorer_main():
    repo_root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        'scorer_main_for_test', repo_root / 'apps/scorer/src/main.py'
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


class _Obj:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_zero_weight_raw_blend_honored():
    _install_minimal_stubs()
    m = _import_scorer_main()

    P = sys.modules['pandas']
    raw = P.Series([1.0, 2.0, 3.0])
    resid = P.Series([10.0, 20.0, 30.0])
    settings = _Obj(
        scoring_momentum_composite_mode='blend',
        scoring_momentum_residual_weight=0.0,
        scoring_momentum_raw_weight=1.0,
    )
    comp, mode, w_resid, w_raw = m._blend_momentum_series(raw, resid, settings)
    assert mode == 'blend'
    assert w_resid == 0.0 and w_raw == 1.0
    assert list(comp) == list(raw)


def test_zero_weight_residual_blend_honored():
    _install_minimal_stubs()
    m = _import_scorer_main()

    P = sys.modules['pandas']
    raw = P.Series([1.0, 2.0, 3.0])
    resid = P.Series([10.0, 20.0, 30.0])
    settings = _Obj(
        scoring_momentum_composite_mode='blend',
        scoring_momentum_residual_weight=1.0,
        scoring_momentum_raw_weight=0.0,
    )
    comp, mode, w_resid, w_raw = m._blend_momentum_series(raw, resid, settings)
    assert mode == 'blend'
    assert w_resid == 1.0 and w_raw == 0.0
    assert list(comp) == list(resid)


def test_string_weights_and_empty_defaulting():
    _install_minimal_stubs()
    m = _import_scorer_main()

    P = sys.modules['pandas']
    raw = P.Series([0.0, 0.0])
    resid = P.Series([2.0, 2.0])
    # Strings should parse; empty string should default to 0.3 for raw
    settings = _Obj(
        scoring_momentum_composite_mode='blend',
        scoring_momentum_residual_weight='0.7',
        scoring_momentum_raw_weight='',  # default -> 0.3
    )
    comp, mode, w_resid, w_raw = m._blend_momentum_series(raw, resid, settings)
    assert mode == 'blend'
    assert abs(w_resid - 0.7) < 1e-9 and abs(w_raw - 0.3) < 1e-9
    # With raw zeros, composite equals residual scaled by 0.7/(0.7+0.3)=0.7
    assert list(comp) == [v * 0.7 for v in resid]
