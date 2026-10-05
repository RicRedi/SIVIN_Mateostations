"""The central secret redactor (WP-1.7 review, round 3)."""

from __future__ import annotations

import json
from urllib.parse import quote, quote_plus

from sivin.redaction import MIN_SECRET_LENGTH, REDACTED, SecretRedactor, secret_forms


def test_values_shorter_than_the_minimum_are_named_not_redacted() -> None:
    short = "x" * (MIN_SECRET_LENGTH - 1)
    redactor = SecretRedactor.of({"SIVIN_USER": short, "SIVIN_PASSWORD": "long-secret"})
    assert redactor.secrets == secret_forms("long-secret")
    assert redactor.unredactable == ("SIVIN_USER",)
    assert redactor.redact(f"{short} long-secret") == f"{short} {REDACTED}"


def test_minimum_length_is_redacted_and_empty_values_are_ignored() -> None:
    exact = "a" * MIN_SECRET_LENGTH
    redactor = SecretRedactor.of({"SIVIN_USER": exact, "SIVIN_PASSWORD": ""})
    assert redactor.secrets == secret_forms(exact)
    assert redactor.unredactable == ()


def test_from_environment_reads_the_credential_variables() -> None:
    environ = {"SIVIN_USER": "operator-x", "SIVIN_PASSWORD": "pw!", "OTHER": "ignored-value"}
    redactor = SecretRedactor.from_environment(environ)
    assert redactor.secrets == secret_forms("operator-x")
    assert redactor.unredactable == ("SIVIN_PASSWORD",)


def test_longer_secrets_are_replaced_first() -> None:
    redactor = SecretRedactor.of({"SIVIN_USER": "abcd", "SIVIN_PASSWORD": "abcdef"})
    assert redactor.redact("abcdef") == REDACTED


def test_including_combines_secrets_and_short_names() -> None:
    base = SecretRedactor.of({"SIVIN_USER": "env-user", "SIVIN_PASSWORD": "ab"})
    combined = base.including({"SIVIN_PASSWORD": "used-password", "SIVIN_USER": "env-user"})
    assert set(combined.secrets) == {*secret_forms("env-user"), *secret_forms("used-password")}
    assert combined.unredactable == ("SIVIN_PASSWORD",)


def test_redact_data_walks_keys_values_and_sequences() -> None:
    redactor = SecretRedactor.of({"SIVIN_PASSWORD": "hunter22"})
    data = {"hunter22": ["x hunter22", ("hunter22", 3)], "n": 1.5, "flag": None}
    assert redactor.redact_data(data) == {
        REDACTED: [f"x {REDACTED}", [REDACTED, 3]],
        "n": 1.5,
        "flag": None,
    }


def test_redact_data_without_secrets_returns_the_input() -> None:
    data = {"a": ("b",)}
    assert SecretRedactor().redact_data(data) is data


TRICKY = "pw\\\"q'é€ x-42"
"""SYNTHETIC password with a backslash, both quote kinds, non-ASCII characters and a space."""


def test_secret_forms_cover_the_escaped_forms() -> None:
    forms = set(secret_forms(TRICKY))
    assert {
        TRICKY,
        repr(TRICKY)[1:-1],
        ascii(TRICKY)[1:-1],
        json.dumps(TRICKY)[1:-1],
        json.dumps(TRICKY, ensure_ascii=False)[1:-1],
        json.dumps(repr(TRICKY)[1:-1])[1:-1],
        TRICKY.encode("unicode_escape").decode("ascii"),
        str(list(TRICKY))[1:-1],
        json.dumps(list(TRICKY))[1:-1],
        quote(TRICKY, safe=""),
        quote_plus(TRICKY, safe=""),
    } <= forms
    assert list(secret_forms(TRICKY)) == sorted(forms, key=lambda f: (-len(f), f))


def test_every_form_is_redacted_in_text() -> None:
    redactor = SecretRedactor.of({"SIVIN_PASSWORD": TRICKY})
    for text in (
        repr(TRICKY),
        json.dumps({"failure": TRICKY}),
        str({"value": list(TRICKY)}),
        f"https://host/login?pw={quote_plus(TRICKY)}",
        "x " + TRICKY.replace("\\", "\\\\").replace("'", "\\'"),
    ):
        redacted = redactor.redact(text)
        assert REDACTED in redacted, text
        for form in secret_forms(TRICKY):
            assert form not in redacted


def test_a_plain_secret_has_few_forms() -> None:
    assert secret_forms("abcd") == (
        json.dumps(list("abcd"))[1:-1],
        str(list("abcd"))[1:-1],
        "abcd",
    )
