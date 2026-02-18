import pytest

np = pytest.importorskip('numpy')


def pc1_share(X: np.ndarray) -> float:
    # Center per-series (stocks) so the common mode is preserved across days.
    if X.shape[0] < X.shape[1]:
        # Expect rows=T, cols=N; if not, transpose
        X = X
    # center per stock across time
    X = X - np.nanmean(X, axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(X, full_matrices=False)
    s2 = s * s
    return float(s2[0] / np.sum(s2))


def test_pc1_share_detects_common_mode():
    rng = np.random.default_rng(0)
    T, N = 20, 200
    market = rng.normal(0, 0.01, size=T)
    noise = rng.normal(0, 0.005, size=(T, N))
    X = market.reshape(T, 1) @ np.ones((1, N)) + noise
    share = pc1_share(X)
    # With strong common mode, PC1 should dominate
    assert share > 0.5
