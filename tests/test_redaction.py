"""The central secret redactor (WP-1.7 review, round 3)."""

from __future__ import annotations

from sivin.redaction import MIN_SECRET_LENGTH, REDACTED, SecretRedactor


def test_values_shorter_than_the_minimum_are_named_not_redacted() -> None:
    short = "x" * (MIN_SECRET_LENGTH - 1)
    redactor = SecretRedactor.of({"SIVIN_USER": short, "SIVIN_PASSWORD": "long-secret"})
    assert redactor.secrets == ("long-secret",)
    assert redactor.unredactable == ("SIVIN_USER",)
    assert redactor.redact(f"{short} long-secret") == f"{short} {REDACTED}"


def test_minimum_length_is_redacted_and_empty_values_are_ignored() -> None:
    exact = "a" * MIN_SECRET_LENGTH
    redactor = SecretRedactor.of({"SIVIN_USER": exact, "SIVIN_PASSWORD": ""})
    assert redactor.secrets == (exact,)
    assert redactor.unredactable == ()


def test_from_environment_reads_the_credential_variables() -> None:
    environ = {"SIVIN_USER": "operator-x", "SIVIN_PASSWORD": "pw!", "OTHER": "ignored-value"}
    redactor = SecretRedactor.from_environment(environ)
    assert redactor.secrets == ("operator-x",)
    assert redactor.unredactable == ("SIVIN_PASSWORD",)


def test_longer_secrets_are_replaced_first() -> None:
    redactor = SecretRedactor.of({"SIVIN_USER": "abcd", "SIVIN_PASSWORD": "abcdef"})
    assert redactor.redact("abcdef") == REDACTED


def test_including_combines_secrets_and_short_names() -> None:
    base = SecretRedactor.of({"SIVIN_USER": "env-user", "SIVIN_PASSWORD": "ab"})
    combined = base.including({"SIVIN_PASSWORD": "used-password", "SIVIN_USER": "env-user"})
    assert set(combined.secrets) == {"env-user", "used-password"}
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
