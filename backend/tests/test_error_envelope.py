"""Error envelopes must be readable by a person.

The dashboard shows the envelope's ``message`` verbatim in an error
banner, and the dashboard's users are clinic staff, not programmers. DRF
hands back a nested structure like::

    {"slug": [ErrorDetail(string='Enter a valid "slug"...', code='invalid')]}

Rendering that directly puts a Python repr in front of the user. This
module pins down that the message reads like a sentence instead.
"""
from __future__ import annotations

import pytest
from rest_framework import serializers


class SampleSerializer(serializers.Serializer):
    slug = serializers.SlugField()
    name = serializers.CharField(max_length=5)


def _envelope(exc, request=None):
    """Run the API exception handler and return the error envelope."""
    from rest_framework.exceptions import ValidationError
    from rest_framework.views import APIView

    from apps.core.exceptions import api_exception_handler

    if exc is None:
        exc = ValidationError(
            {"slug": ['Enter a valid "slug" consisting of letters, numbers, underscores or hyphens.']}
        )

    view = APIView()
    view.request = request
    return api_exception_handler(exc, {"request": request, "view": view})


def test_a_field_error_is_not_rendered_as_a_python_repr():
    """The message must not contain ``ErrorDetail(``."""
    response = _envelope(None)
    message = response.data["error"]["message"]

    assert "ErrorDetail" not in message
    assert "code='invalid'" not in message
    assert message == (
        'slug: Enter a valid "slug" consisting of letters, numbers, underscores or hyphens.'
    )


def test_several_field_errors_are_joined_readably():
    from rest_framework.exceptions import ValidationError

    response = _envelope(
        ValidationError({"slug": ["Not a slug."], "name": ["Too long."]})
    )
    message = response.data["error"]["message"]

    assert message == "slug: Not a slug.; name: Too long."


def test_non_field_errors_are_not_prefixed_with_a_key():
    from rest_framework.exceptions import ValidationError

    response = _envelope(ValidationError({"non_field_errors": ["Those details are wrong."]}))
    message = response.data["error"]["message"]

    assert message == "Those details are wrong."


def test_the_original_structure_is_kept_in_details():
    """The structured form is still available for programmatic callers."""
    response = _envelope(None)
    details = response.data["error"]["details"]

    assert "fields" in details
    assert "slug" in details["fields"]


def test_a_real_serializer_produces_a_readable_message():
    """The same holds for a genuine serializer validation failure."""
    from rest_framework.exceptions import ValidationError

    serializer = SampleSerializer(data={"slug": "not a slug!", "name": "far too long"})
    assert not serializer.is_valid()

    response = _envelope(ValidationError(serializer.errors))
    message = response.data["error"]["message"]

    assert "ErrorDetail" not in message
    assert "slug:" in message
    assert "name:" in message
