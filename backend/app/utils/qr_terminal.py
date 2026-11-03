"""Local QR rendering. No network requests."""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def render_qr(data: str, *, ascii_mode: bool = False) -> str:
    code = qrcode.QRCode(error_correction=ERROR_CORRECT_M, border=1, box_size=1)
    code.add_data(data)
    code.make(fit=True)
    if ascii_mode:
        buffer = io.StringIO()
        code.print_ascii(out=buffer, tty=False)
        return buffer.getvalue().rstrip("\n")
    return _unicode(code.get_matrix())


def _unicode(matrix: list[list[bool]]) -> str:
    rows = matrix
    if len(rows) % 2 == 1:
        width = len(rows[0]) if rows else 0
        rows = [*rows, [False] * width]
    lines: list[str] = []
    for top_index in range(0, len(rows), 2):
        pieces: list[str] = []
        for column in range(len(rows[0])):
            top = rows[top_index][column]
            bottom = rows[top_index + 1][column]
            if top and bottom:
                pieces.append("█")
            elif top:
                pieces.append("▀")
            elif bottom:
                pieces.append("▄")
            else:
                pieces.append(" ")
        lines.append("".join(pieces).rstrip())
    return "\n".join(lines)
