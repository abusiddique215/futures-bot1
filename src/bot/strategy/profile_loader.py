"""YAML loader for ORBProfile."""
from __future__ import annotations

from pathlib import Path

import yaml

from bot.strategy.orb import ORBProfile


def load_orb_profile(path: Path) -> ORBProfile:
    """Load an ORBProfile from a YAML file. Raises ValidationError on bad input."""
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        raw = {}
    return ORBProfile.model_validate(raw)
