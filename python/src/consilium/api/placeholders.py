"""Tiny stand-ins for tile bytes. Not a real slide."""

from __future__ import annotations

# 1x1 JPEG. Magic bytes are checked in tests; it is not clinical imagery.
PLACEHOLDER_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300030202020202030202020303"
    "030304060404040404080606050609080a0a090809090a0c0f0c0a0b0e0b09090d110d0e0f"
    "101011100a0c12131210130f101010ffc0000b080001000101011100ffc400141000000000"
    "00000000000000000000000008ffc400141001000000000000000000000000000000000000"
    "ffda0008010100003f0054ffd9"
)


def dzi_document(width: int, height: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Image xmlns="http://schemas.microsoft.com/deepzoom/2008" '
        'Format="jpeg" Overlap="0" TileSize="256">'
        f'<Size Width="{width}" Height="{height}"/>'
        "</Image>"
    )
