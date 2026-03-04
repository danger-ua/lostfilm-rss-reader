"""Tests for custom exception classes."""

import pytest

from lostfilm.exceptions import (
    AuthenticationError,
    LostFilmError,
    ParseError,
    RateLimitError,
    ServerError,
)


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestInheritance:
    @pytest.mark.parametrize(
        "exc_class",
        [
            AuthenticationError,
            ServerError,
            RateLimitError,
            ParseError,
        ],
    )
    def test_is_lostfilm_error_subclass(self, exc_class):
        assert issubclass(exc_class, LostFilmError)

    @pytest.mark.parametrize(
        "exc_class",
        [
            AuthenticationError,
            ServerError,
            RateLimitError,
            ParseError,
        ],
    )
    def test_is_exception_subclass(self, exc_class):
        assert issubclass(exc_class, Exception)


# ---------------------------------------------------------------------------
# Default messages
# ---------------------------------------------------------------------------


class TestDefaultMessages:
    def test_authentication_error_default_message(self):
        exc = AuthenticationError()
        assert "Authentication failed" in exc.message
        assert "Session tokens" in exc.message

    def test_server_error_default_message(self):
        exc = ServerError()
        assert "Server error" in exc.message

    def test_rate_limit_error_default_message(self):
        exc = RateLimitError()
        assert "Rate limit" in exc.message
        assert "15 minutes" in exc.message

    def test_parse_error_default_message(self):
        exc = ParseError()
        assert "parse" in exc.message.lower()


# ---------------------------------------------------------------------------
# Custom messages
# ---------------------------------------------------------------------------


class TestCustomMessages:
    def test_authentication_error_custom_message(self):
        exc = AuthenticationError("custom auth message")
        assert exc.message == "custom auth message"
        assert str(exc) == "custom auth message"

    def test_server_error_custom_message(self):
        exc = ServerError("custom server message")
        assert exc.message == "custom server message"

    def test_rate_limit_error_custom_message(self):
        exc = RateLimitError("custom rate message")
        assert exc.message == "custom rate message"

    def test_parse_error_custom_message(self):
        exc = ParseError("custom parse message")
        assert exc.message == "custom parse message"


# ---------------------------------------------------------------------------
# Raisability
# ---------------------------------------------------------------------------


class TestRaising:
    @pytest.mark.parametrize(
        "exc_class",
        [
            LostFilmError,
            AuthenticationError,
            ServerError,
            RateLimitError,
            ParseError,
        ],
    )
    def test_can_be_raised_and_caught(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("triggered")

    def test_subclass_caught_as_base(self):
        with pytest.raises(LostFilmError):
            raise AuthenticationError("caught as base")
