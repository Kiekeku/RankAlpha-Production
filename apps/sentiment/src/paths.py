from __future__ import annotations

import os
from pathlib import Path

from apps.sentiment.src.settings import Settings as Settings

DEFAULT_DATA_DIR = "/data"
DEFAULT_OUTPUT_DIR = os.path.join(DEFAULT_DATA_DIR, "company_reports")
DEFAULT_SCHEDULE_FILE = Path(
    os.path.join(DEFAULT_DATA_DIR, "analysis_schedule", "analysis_schedule.json")
)

# Mutable module-level paths configured at runtime via configure_paths.
OUTPUT_DIR = DEFAULT_OUTPUT_DIR
SCHEDULE_FILE = DEFAULT_SCHEDULE_FILE


def configure_paths(settings: Settings) -> str:
    """Configure sentiment data paths from Settings and return the resolved data dir."""
    global OUTPUT_DIR, SCHEDULE_FILE

    data_dir = settings.sentiment_data_dir or DEFAULT_DATA_DIR
    OUTPUT_DIR = settings.sentiment_output_dir or os.path.join(data_dir, "company_reports")
    SCHEDULE_FILE = Path(
        settings.sentiment_schedule_file
        or os.path.join(data_dir, "analysis_schedule", "analysis_schedule.json")
    )
    return data_dir


__all__ = [
    "DEFAULT_DATA_DIR",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_SCHEDULE_FILE",
    "OUTPUT_DIR",
    "SCHEDULE_FILE",
    "configure_paths",
]
