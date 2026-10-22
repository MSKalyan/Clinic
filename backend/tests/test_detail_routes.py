"""Every detail route must actually be reachable.

DRF passes the detail-route identifier as ``pk``. A view that declares its
own name for it (``def availability(self, request, doctor_id=None)``) raises
``TypeError: got an unexpected keyword argument 'pk'`` and the endpoint
answers 500.

That is exactly what happened to every ``@action(detail=True)`` in this
project, and no test caught it because the suite exercised the collection
routes but never the detail routes. This module walks the router and calls
each detail route, so the next one fails loudly in CI instead of quietly in
production.
"""
from __future__ import annotations

import re

import pytest
from django.urls import Resolver404, resolve

from apps.api.v1.urls import router

#: The prefix the router is mounted under.
API_PREFIX = "/api/v1"

#: A stand-in for any identifier in a route.
PLACEHOLDER = "00000000-0000-0000-0000-000000000000"

#: Matches the named group of a URL pattern, e.g. ``(?P<key>[^/]+)``.
_NAMED_GROUP = re.compile(r"\(\?P<\w+>[^)]+\)")


def _detail_routes() -> list[tuple[str, str, str]]:
    """``(basename, url_path, action_name)`` for every detail route."""
    routes = []
    for prefix, viewset, basename in router.registry:
        for route in viewset.get_extra_actions():
            if not route.detail:
                continue
            suffix = route.url_path or route.name
            routes.append((basename, f"{API_PREFIX}/{prefix}/<pk>/{suffix}/", route.__name__))
    return routes


DETAIL_ROUTES = _detail_routes()


def test_router_exposes_detail_routes():
    """Sanity check: the list we are about to walk is not empty."""
    assert DETAIL_ROUTES, "the router exposes no detail routes at all"


@pytest.mark.parametrize(
    "basename,path,action_name",
    DETAIL_ROUTES,
    ids=[f"{basename}:{action_name}" for basename, _path, action_name in DETAIL_ROUTES],
)
def test_detail_route_is_routed(basename, path, action_name):
    """Every detail route resolves to a view, and the view accepts ``pk``.

    The identifier is passed to detail routes as ``pk``. If the action
    declares a different name for it, DRF raises a ``TypeError`` before the
    handler body ever runs -- a 500 for every caller.
    """
    import inspect

    # Fill in every identifier: the router's ``<pk>`` and any named group
    # the action's own ``url_path`` adds.
    resolved_path = path.replace("<pk>", PLACEHOLDER)
    resolved_path = _NAMED_GROUP.sub(PLACEHOLDER, resolved_path)

    try:
        match = resolve(resolved_path)
    except Resolver404 as error:  # pragma: no cover - configuration error
        pytest.fail(f"{path} is not routed: {error}")

    view_class = match.func.cls
    action = next(
        (
            candidate
            for candidate in view_class.get_extra_actions()
            if candidate.__name__ == action_name
        ),
        None,
    )
    assert action is not None, f"{view_class.__name__} has no action named {action_name}"

    signature = inspect.signature(action)
    assert "pk" in signature.parameters, (
        f"{view_class.__name__}.{action_name} does not accept the 'pk' keyword "
        "argument that DRF passes to detail routes"
    )


@pytest.mark.parametrize(
    "basename,path,action_name",
    DETAIL_ROUTES,
    ids=[f"{basename}:{action_name}" for basename, _path, action_name in DETAIL_ROUTES],
)
def test_detail_route_never_answers_500(
    basename, path, action_name, admin_client, clinic, doctor, patient
):
    """Calling a detail route must never produce a 500.

    Some routes legitimately answer 403 or 404 for the fixture used here --
    a receptionist cannot read a clinic's provider connections, and a
    nonexistent identifier is a 404 by design. What must never happen is a
    500, because that is what a signature mismatch looks like from the
    outside.
    """
    identifiers = {
        "doctor": doctor.id,
        "patient": patient.id,
        "clinic": clinic.id,
        "appointment": "00000000-0000-0000-0000-000000000000",
        "follow-up": "00000000-0000-0000-0000-000000000000",
    }
    identifier = identifiers.get(basename, "00000000-0000-0000-0000-000000000000")
    url = path.replace("<pk>", str(identifier))

    response = admin_client.get(url)

    assert response.status_code != 500, (
        f"{url} answered 500. The response body is: {response.content[:400]!r}"
    )
