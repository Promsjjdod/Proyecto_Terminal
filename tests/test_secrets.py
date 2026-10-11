"""Pruebas del almacén de secretos y la redacción de claves."""
from __future__ import annotations

import os
import stat

from nexo.security.secrets import SecretStore, mask_secret, redact_text


def test_secret_store_roundtrip(tmp_path):
    store = SecretStore(tmp_path / "secrets.json")
    store.set("prov", "sk-test-1234567890abcdef")
    assert store.get("prov") == "sk-test-1234567890abcdef"
    # Recarga desde disco
    store2 = SecretStore(tmp_path / "secrets.json")
    assert store2.get("prov") == "sk-test-1234567890abcdef"
    assert store2.names() == ["prov"]
    assert store2.delete("prov") is True
    assert store2.get("prov") is None


def test_secret_store_file_permissions(tmp_path):
    path = tmp_path / "secrets.json"
    store = SecretStore(path)
    store.set("k", "v-secret-value")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600


def test_secret_store_corrupt_file(tmp_path):
    path = tmp_path / "secrets.json"
    path.write_text("no-json", encoding="utf-8")
    store = SecretStore(path)
    assert store.names() == []
    assert store.is_valid() is False


def test_redact_text_patterns():
    text = (
        "key OpenAI sk-abcdefghij1234567890 y anthropic sk-ant-abcdefghij1234567890 "
        "github ghp_0123456789abcdefghijABCDEF aws AKIAIOSFODNN7EXAMPLE "
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc123def456ghi"
    )
    clean = redact_text(text)
    assert "sk-abcdefghij" not in clean
    assert "sk-ant-abcdefghij" not in clean
    assert "ghp_0123456789" not in clean
    assert "AKIAIOSFODNN7EXAMPLE" not in clean
    assert "eyJhbGciOiJIUzI1NiJ9" not in clean
    assert clean.count("[REDACTADO]") >= 5


def test_redact_text_extra_secrets():
    clean = redact_text("mi clave es MICLAVEPERSONAL123 ok",
                        extra_secrets={"prov": "MICLAVEPERSONAL123"})
    assert "MICLAVEPERSONAL123" not in clean
    assert "[REDACTADO]" in clean


def test_mask_secret():
    masked = mask_secret("sk-1234567890abcdef")
    assert "1234567890abcdef" not in masked
    assert masked.startswith("sk-1") and masked.endswith(")")
    assert mask_secret("") == ""
    assert mask_secret("corta") == "*****"
