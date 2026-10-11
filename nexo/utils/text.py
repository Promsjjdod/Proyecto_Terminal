"""Utilidades de texto: envoltura, truncado y normalización para pantallas estrechas."""
from __future__ import annotations

import re
import unicodedata


def visible_len(text: str) -> int:
    """Longitud visible ignorando secuencias ANSI y caracteres de ancho cero."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    total = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def truncate(text: str, width: int, suffix: str = "…") -> str:
    """Trunca `text` a `width` columnas visibles."""
    if width <= 0:
        return ""
    if visible_len(text) <= width:
        return text
    out: list[str] = []
    used = 0
    limit = max(width - visible_len(suffix), 1)
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > limit:
            break
        out.append(ch)
        used += w
    return "".join(out) + suffix


def wrap_lines(text: str, width: int) -> list[str]:
    """Divide texto en líneas que caben en `width` columnas (sin cortar palabras si es posible)."""
    width = max(width, 10)
    result: list[str] = []
    for raw in text.splitlines() or [""]:
        line = raw.rstrip()
        if visible_len(line) <= width:
            result.append(line)
            continue
        current = ""
        for word in line.split(" "):
            candidate = word if not current else current + " " + word
            if visible_len(candidate) <= width:
                current = candidate
            else:
                if current:
                    result.append(current)
                # Palabra más larga que el ancho: trocearla.
                while visible_len(word) > width:
                    piece, word = word[: width - 1], word[width - 1 :]
                    result.append(piece)
                current = word
        if current:
            result.append(current)
    return result


def normalize_eol(text: str, eol: str) -> str:
    """Normaliza finales de línea a `eol` ('\n' o '\r\n')."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if eol == "\r\n":
        text = text.replace("\n", "\r\n")
    return text


def detect_eol(raw: bytes) -> str:
    """Detecta el EOL dominante de un contenido binario."""
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def looks_binary(raw: bytes, sample: int = 8192) -> bool:
    """Heurística de binario: bytes NUL o alta proporción de no-texto."""
    chunk = raw[:sample]
    if b"\x00" in chunk:
        return True
    if not chunk:
        return False
    text_chars = bytes(range(7, 14)) + bytes(range(32, 127)) + b"\n\r\t\f\x1b"
    non_text = sum(1 for b in chunk if b not in text_chars and b < 0x80)
    return non_text / len(chunk) > 0.30
