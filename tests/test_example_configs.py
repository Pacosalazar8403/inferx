"""Every example config in the repo must load and build a valid router."""

from pathlib import Path

import pytest

from inferx.gateway_config import build_router, load_config

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
EXAMPLE_CONFIGS = sorted(CONFIG_DIR.glob("*.toml"))


def test_example_configs_were_found() -> None:
    # Without this, a broken path would make the test below run zero times
    # and still "pass".
    assert EXAMPLE_CONFIGS


@pytest.mark.parametrize("path", EXAMPLE_CONFIGS, ids=lambda path: path.name)
def test_example_config_is_valid(path: Path) -> None:
    build_router(load_config(path))