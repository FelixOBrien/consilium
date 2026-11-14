from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from consilium.api.errors import fail  # pragma: allowlist secret
from consilium.api.schemas.pathologist import Pathologist  # pragma: allowlist secret
from consilium.api.store import Store  # pragma: allowlist secret


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_acting_pathologist(
    request: Request,
    x_user_id: Annotated[
        str | None,
        Header(
            alias="X-User-Id",
            description="Acting pathologist id. Omit to act as the demo user.",
        ),
    ] = None,
) -> Pathologist:
    """Resolve the acting pathologist. Missing header uses the demo user (F-01.7)."""
    store = get_store(request)
    raw = (x_user_id or "").strip()
    if not raw:
        return store.demo_user()
    found = store.pathologists.get(raw)
    if found is None:
        fail(404, "unknown_user", "No pathologist matches X-User-Id.")
    return found


StoreDep = Annotated[Store, Depends(get_store)]
Acting = Annotated[Pathologist, Depends(get_acting_pathologist)]
