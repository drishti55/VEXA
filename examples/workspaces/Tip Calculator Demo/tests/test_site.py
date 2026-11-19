"""Acceptance tests for the Tip Calculator website (static files only, no browser needed)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(name: str) -> str:
    path = ROOT / name
    assert path.is_file(), f"{name} is missing"
    return path.read_text(encoding="utf-8")


def test_page_links_its_style_and_script():
    html = read("index.html")
    assert "style.css" in html
    assert "script.js" in html


def test_form_has_required_inputs():
    html = read("index.html")
    for element_id in ('id="bill"', 'id="tip"', 'id="people"', 'id="calc"', 'id="result"'):
        assert element_id in html, f"index.html needs an element with {element_id}"


def test_script_reads_inputs_and_writes_result():
    js = read("script.js")
    for element_id in ("bill", "tip", "people", "result"):
        assert element_id in js, f"script.js should use #{element_id}"
    assert "addEventListener" in js


def test_stylesheet_is_not_empty():
    assert len(read("style.css").strip()) > 40
