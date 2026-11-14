from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from consilium.api.schemas.common import APIModel  # pragma: allowlist secret
from consilium.api.schemas.pathologist import PathologistRef  # pragma: allowlist secret


class RectGeometry(APIModel):
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PointGeometry(APIModel):
    x: int
    y: int


class Annotation(APIModel):
    id: UUID
    slide_id: str
    case_id: str
    author: PathologistRef
    can_edit: bool
    kind: Literal["rect", "point"]
    geometry: RectGeometry | PointGeometry
    label: str = Field(min_length=1, max_length=80)
    note: str | None
    created_at: datetime
    updated_at: datetime


class AnnotationCreate(APIModel):
    kind: Literal["rect", "point"]
    geometry: RectGeometry | PointGeometry
    label: str = Field(min_length=1, max_length=80)
    note: str | None = None

    @model_validator(mode="after")
    def kind_matches_geometry(self) -> Self:
        _geometry_matches(self.kind, self.geometry)
        return self


class AnnotationUpdate(APIModel):
    geometry: RectGeometry | PointGeometry | None = None
    label: str | None = Field(default=None, min_length=1, max_length=80)
    note: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> Self:
        if self.geometry is None and self.label is None and "note" not in self.model_fields_set:
            raise ValueError("provide geometry, label or note")
        return self


def _geometry_matches(kind: str, geometry: RectGeometry | PointGeometry) -> None:
    if kind == "rect" and not isinstance(geometry, RectGeometry):
        raise ValueError("a rectangle needs width and height")
    if kind == "point" and isinstance(geometry, RectGeometry):
        raise ValueError("a point has no width or height")
