"""Small integer-interval helpers shared by planners."""

from __future__ import annotations

from collections.abc import Iterable

LabeledBlock = tuple[int, int, str]


def overlap(start: int, end: int, block_start: int, block_end: int) -> int:
    """Minutes that ``[start, end)`` overlaps ``[block_start, block_end)``."""
    return max(0, min(end, block_end) - max(start, block_start))


def shift(start: int, blocks: Iterable[tuple[int, int]], duration: int) -> int:
    """Move ``start`` forward until ``[start, start+duration)`` fits the gaps."""
    moved = True
    while moved:
        moved = False
        for block_start, block_end in blocks:
            if start < block_end and start + duration > block_start:
                start = block_end
                moved = True
    return start


def gap_around(blocks: Iterable[tuple[int, int]], minute: int) -> tuple[int, int] | None:
    """Free gap between two blocks that contains ``minute``."""
    ordered = sorted(blocks)
    for (_, gap_start), (gap_end, _) in zip(ordered, ordered[1:]):
        if gap_start <= minute < gap_end:
            return gap_start, gap_end
    return None


def subtract_blocks(blocks: Iterable[LabeledBlock], start: int, end: int) -> list[LabeledBlock]:
    """Cut ``[start, end)`` out of labelled blocks."""
    result: list[LabeledBlock] = []
    for block_start, block_end, label in blocks:
        if end <= block_start or start >= block_end:
            result.append((block_start, block_end, label))
        else:
            if block_start < start:
                result.append((block_start, start, label))
            if end < block_end:
                result.append((end, block_end, label))
    return result


def split_blocks(
    blocks: Iterable[LabeledBlock], breaks: Iterable[LabeledBlock]
) -> list[LabeledBlock]:
    """Split blocks at breaks; each break only cuts blocks with its label."""
    result = list(blocks)
    for start, end, label in breaks:
        updated: list[LabeledBlock] = []
        for block_start, block_end, current in result:
            if current != label or end <= block_start or start >= block_end:
                updated.append((block_start, block_end, current))
                continue
            if block_start < start:
                updated.append((block_start, start, current))
            if end < block_end:
                updated.append((end, block_end, current))
        result = updated
    return result
