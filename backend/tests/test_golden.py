"""Today's rendered prompts, byte for byte (PLAN-brief I0). With no brief, nothing may change.

Regenerate by hand only, on purpose: python -m backend.tests.golden.make
"""

import pytest

from backend.tests.golden.make import GOLDEN_DIR, render_all

RENDERED = render_all()


def test_every_golden_file_is_rendered():
    on_disk = {p.name for p in GOLDEN_DIR.iterdir() if p.suffix in (".txt", ".json")}
    assert on_disk == set(RENDERED)


@pytest.mark.parametrize("name", sorted(RENDERED))
def test_golden(name):
    expected = (GOLDEN_DIR / name).read_text(encoding="utf-8")
    assert RENDERED[name] == expected, f"{name} changed; regenerate only if that was intended"
