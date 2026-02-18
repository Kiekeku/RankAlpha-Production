from datetime import date, timedelta

import pytest

from apps.ingestion.src.hy_stress import compute_hy_stress


def test_compute_hy_stress_ma_and_z():
    start = date(2024, 1, 1)
    rows = [(start + timedelta(days=i), float(i + 1)) for i in range(6)]  # 1..6

    result = compute_hy_stress(rows, ma_window=3, z_window=4)

    # First two entries have no MA/Z
    assert result[0].ma_10 is None
    assert result[1].ma_10 is None

    # Third entry should have first MA
    assert result[2].ma_10 == 2.0
    assert result[2].z_750 is None

    # Sixth entry reaches z-window; verify z-score
    last = result[-1]
    assert last.ma_10 == 5.0
    # Mean of MAs [2,3,4,5] = 3.5; std ~1.1180; z ~1.3416
    assert last.z_750 == pytest.approx(1.3416, rel=1e-4)
