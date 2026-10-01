"""Source-level regions used to associate compiler diagnostics with loops."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LoopRegion:
    start_offset: int
    end_offset: int
    header_line: int
    header_col: int


_LOOP_TOKEN = re.compile(r"\b(for|while|do)\b")


def _mask_non_code(source: str) -> str:
    """Replace comments and literals with spaces while preserving newlines."""
    chars = list(source)
    i = 0
    n = len(chars)
    state = "code"

    while i < n:
        if state == "code":
            if source.startswith("//", i):
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "line_comment"
            elif source.startswith("/*", i):
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "block_comment"
            elif source[i] == '"':
                chars[i] = " "
                i += 1
                state = "string"
            elif source[i] == "'":
                chars[i] = " "
                i += 1
                state = "character"
            else:
                i += 1
        elif state == "line_comment":
            if source[i] == "\n":
                state = "code"
            else:
                chars[i] = " "
            i += 1
        elif state == "block_comment":
            if source.startswith("*/", i):
                chars[i] = chars[i + 1] = " "
                i += 2
                state = "code"
            else:
                if source[i] != "\n":
                    chars[i] = " "
                i += 1
        else:
            if source[i] == "\\" and i + 1 < n:
                chars[i] = " "
                if source[i + 1] != "\n":
                    chars[i + 1] = " "
                i += 2
            elif (state == "string" and source[i] == '"') or (
                state == "character" and source[i] == "'"
            ):
                chars[i] = " "
                i += 1
                state = "code"
            else:
                if source[i] != "\n":
                    chars[i] = " "
                i += 1

    return "".join(chars)


def _matching_delimiter(source: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    for i in range(start, len(source)):
        if source[i] == opening:
            depth += 1
        elif source[i] == closing:
            depth -= 1
            if depth == 0:
                return i
    return None


def _statement_end(source: str, start: int) -> int:
    parens = 0
    brackets = 0
    for i in range(start, len(source)):
        if source[i] == "(":
            parens += 1
        elif source[i] == ")":
            parens = max(0, parens - 1)
        elif source[i] == "[":
            brackets += 1
        elif source[i] == "]":
            brackets = max(0, brackets - 1)
        elif source[i] == ";" and parens == 0 and brackets == 0:
            return i
    return len(source) - 1


def _line_col(source: str, offset: int) -> tuple[int, int]:
    line_start = source.rfind("\n", 0, offset) + 1
    return source.count("\n", 0, offset) + 1, offset - line_start + 1


def find_loop_regions(source: str) -> list[LoopRegion]:
    """Find C/C++ loop regions without requiring a compiler or libclang."""
    masked = _mask_non_code(source)
    regions: list[LoopRegion] = []
    do_while_tails: list[tuple[int, int]] = []

    for match in _LOOP_TOKEN.finditer(masked):
        keyword = match.group(1)
        header_start = match.start()

        if keyword == "while" and any(
            start <= header_start <= end for start, end in do_while_tails
        ):
            continue

        body_start = match.end()
        if keyword in {"for", "while"}:
            open_paren = masked.find("(", body_start)
            if open_paren == -1:
                continue
            close_paren = _matching_delimiter(masked, open_paren, "(", ")")
            if close_paren is None:
                continue
            body_start = close_paren + 1

        while body_start < len(masked) and masked[body_start].isspace():
            body_start += 1
        if body_start >= len(masked):
            continue

        if masked[body_start] == "{":
            body_end = _matching_delimiter(masked, body_start, "{", "}")
            if body_end is None:
                body_end = len(masked) - 1
        else:
            body_end = _statement_end(masked, body_start)

        if keyword == "do":
            tail = re.match(r"\s*while\b", masked[body_end + 1:])
            if tail:
                tail_start = body_end + 1 + tail.start() + tail.group(0).find("while")
                semicolon = masked.find(";", tail_start)
                if semicolon != -1:
                    do_while_tails.append((tail_start, semicolon))
                    body_end = semicolon

        header_line, header_col = _line_col(source, header_start)
        regions.append(LoopRegion(
            start_offset=header_start,
            end_offset=body_end,
            header_line=header_line,
            header_col=header_col,
        ))

    return regions