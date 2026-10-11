"""Pruebas de la vista diff: conteos, números de línea, binarios y conflictos."""
from __future__ import annotations

from nexo.editor.diff import compute_diff, diff_line_count, find_similar_block


def test_no_changes():
    d = compute_diff("a\nb\n", "a\nb\n", "f.txt")
    assert not d.changed
    assert d.added == 0 and d.removed == 0


def test_added_and_removed_counts():
    old = "uno\ndos\ntres\n"
    new = "uno\nDOS\ntres\ncuatro\n"
    d = compute_diff(old, new, "f.txt")
    assert d.removed == 1   # "dos"
    assert d.added == 2     # "DOS" y "cuatro"
    assert d.changed


def test_line_numbers_present():
    old = "a\nb\nc\nd\ne\nf\ng\n"
    new = "a\nb\nX\nd\ne\nf\ng\n"
    d = compute_diff(old, new, "f.txt", context=1)
    minus = [l for l in d.lines if l.tag == "-"]
    plus = [l for l in d.lines if l.tag == "+"]
    assert minus[0].text == "c" and minus[0].old_no == 3
    assert plus[0].text == "X" and plus[0].new_no == 3


def test_new_file_all_green():
    d = compute_diff(None, "nueva línea\n", "nuevo.txt")
    assert d.is_new and d.added == 1 and d.removed == 0
    assert all(l.tag == "+" for l in d.lines if l.text)


def test_deleted_file_all_red():
    d = compute_diff("vieja\n", None, "viejo.txt")
    assert d.is_delete and d.removed == 1
    assert all(l.tag == "-" for l in d.lines if l.text)


def test_binary_diff_has_no_text_lines():
    d = compute_diff(None, None, "img.png", is_binary=True)
    assert d.is_binary and d.lines == []
    assert "binario" in d.plain_text()


def test_plain_text_contains_marker_and_summary():
    d = compute_diff("a\n", "b\n", "f.txt")
    text = d.plain_text()
    assert "-" in text and "+" in text
    assert "@@ f.txt: +1 -1" in text


def test_conflict_note_surfaced():
    d = compute_diff("a\n", "b\n", "f.txt", conflict_note="bloque no encontrado")
    assert d.conflict_note
    assert d.plain_text().startswith("! ")


def test_context_limiting_for_far_changes():
    # Tokens con relleno para que cada línea sea única (sin subcadenas solapadas).
    old = "\n".join(f"línea{i:03d}" for i in range(100))
    new = old.replace("línea002", "LÍNEA002").replace("línea097", "LÍNEA097")
    d = compute_diff(old, new, "grande.txt", context=3)
    # Con contexto recortado, el diff es mucho menor que el archivo.
    assert diff_line_count(d) < 40
    assert d.added == 2 and d.removed == 2


def test_find_similar_block_detects_near_match():
    old_text = "def suma(a, b):\n    return a + b\n\nx = suma(1, 2)\n"
    missing = "def suma(a, b):\n    return a - b\n"   # bloque desactualizado
    suggestion = find_similar_block(old_text, missing)
    assert suggestion is not None
    assert "return a + b" in suggestion


def test_find_similar_block_returns_none_for_noise():
    old_text = "aaa\nbbb\nccc\n"
    assert find_similar_block(old_text, "zzz\nyyy\nxxx\nwww\nvvv\nuuu\nttt\n") is None
