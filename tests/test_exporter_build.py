"""exporter.py: ZIP / PDF / page-composition behaviour with tiny synthetic images.

Drafted on a local model (qwen3:14b), then rewritten: the draft never imported ``io``,
guessed a ZIP naming scheme with the wrong slot numbering, and asserted an empty ZIP
for the no-art case without reading the source.
"""
from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image, ImageDraw

import exporter


def _png(path, colour):
    Image.new("RGB", (30, 42), colour).save(path)
    return path


@pytest.fixture
def art(tmp_path):
    return {"a": _png(tmp_path / "a.png", "red"), "b": _png(tmp_path / "b.png", "blue")}


def _resolver(art):
    return lambda card: art.get(card.get("render_key"))


def _names(blob: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        return zf.namelist()


def test_zip_names_commander_00_and_numbers_deck_slots(art, tmp_path):
    cmd = {"render_key": "a"}
    deck = [{"render_key": "b"}]
    assert _names(exporter.build_zip(cmd, deck, tmp_path, _resolver(art))) == [
        "00_commander_a.png", "01_b.png"]


def test_zip_emits_one_copy_per_quantity(art, tmp_path):
    cmd = {"render_key": "a"}
    deck = [{"render_key": "b", "quantity": 3}]
    assert _names(exporter.build_zip(cmd, deck, tmp_path, _resolver(art))) == [
        "00_commander_a.png", "01_b_c1.png", "02_b_c2.png", "03_b_c3.png"]


def test_zip_skips_cards_with_no_art_or_render_key(art, tmp_path):
    cmd = {"render_key": "a"}
    deck = [{"render_key": "missing"}, {"render_key": "b"}, {"themed_name": "no key"}]
    assert _names(exporter.build_zip(cmd, deck, tmp_path, _resolver(art))) == [
        "00_commander_a.png", "01_b.png"]


def test_zip_with_no_art_at_all_is_an_empty_archive(tmp_path):
    blob = exporter.build_zip({"render_key": "x"}, [{"render_key": "y"}], tmp_path, lambda c: None)
    assert _names(blob) == []


def test_deck_of_one_is_named_after_the_card(art, tmp_path):
    cmd = {"render_key": "a", "themed_name": "My Card!"}
    assert _names(exporter.build_zip(cmd, [], tmp_path, _resolver(art))) == ["My Card_.png"]


def test_default_resolver_reads_cards_dir(tmp_path):
    (tmp_path / "cards").mkdir()
    _png(tmp_path / "cards" / "k.png", "green")
    assert _names(exporter.build_zip({"render_key": "k"}, [], tmp_path)) == ["card.png"]


def test_pdf_is_a_pdf(art, tmp_path):
    out = exporter.build_pdf({"render_key": "a"}, [{"render_key": "b"}], tmp_path, _resolver(art))
    assert out.startswith(b"%PDF")


def test_pdf_with_no_images_raises(tmp_path):
    with pytest.raises(ValueError):
        exporter.build_pdf({"render_key": "a"}, [], tmp_path, lambda c: None)


def test_make_page_is_letter_at_300dpi_and_marks_cuts():
    page = exporter._make_page([])
    assert page.size == (exporter.PAGE_W_PX, exporter.PAGE_H_PX) == (2550, 3300)
    # an empty page still carries the 4x4 cut-mark grid, so it is not pure white
    assert page.getextrema() != ((255, 255), (255, 255), (255, 255))


def test_make_page_places_a_card_in_the_first_slot():
    page = exporter._make_page([Image.new("RGB", (10, 14), (200, 0, 0))])
    cx = exporter.MARGIN_X + exporter.CARD_W_PX // 2
    cy = exporter.MARGIN_Y + exporter.CARD_H_PX // 2
    assert page.getpixel((cx, cy)) == (200, 0, 0)


def test_cut_mark_draws_grey_arms_and_leaves_the_centre_gap():
    img = Image.new("RGB", (60, 60), "white")
    exporter._cut_mark(ImageDraw.Draw(img), 30, 30)
    assert img.getpixel((30 - 10, 30)) == (160, 160, 160)
    assert img.getpixel((30, 30)) == (255, 255, 255)
