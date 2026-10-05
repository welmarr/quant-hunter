"""Preflight actual Parquet page allocations before Arrow decodes compressed data.

This bounded reader accepts only the compact-protocol scalar/struct fields used
by Parquet PageHeader. Unsupported additions fail closed. It does not interpret
observations; Arrow remains the data decoder after these allocation checks.

Contracts: apache/parquet-format parquet.thrift PageHeader and ColumnMetaData;
apache/thrift doc/specs/thrift-compact-protocol.md.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any, cast


class PageLimitError(ValueError):
    """The physical pages cannot be verified within the bounded contract."""


class _Header:
    def __init__(self, payload: bytes, start: int, end: int) -> None:
        self.payload, self.position = payload, start
        self.end = min(end, start + 16_384)

    def take(self, length: int) -> bytes:
        if length < 0 or self.position + length > self.end:
            raise PageLimitError("PARQUET_PAGE_HEADER_LIMIT")
        value = self.payload[self.position : self.position + length]
        self.position += length
        return value

    def byte(self) -> int:
        return self.take(1)[0]

    def unsigned(self) -> int:
        result = 0
        for shift in range(0, 70, 7):
            value = self.byte()
            result |= (value & 127) << shift
            if value < 128:
                return result
        raise PageLimitError("PARQUET_PAGE_HEADER_INTEGER_LIMIT")

    def signed(self) -> int:
        value = self.unsigned()
        return (value >> 1) ^ -(value & 1)

    def fields(self, depth: int = 0) -> dict[int, object]:
        if depth > 4:
            raise PageLimitError("PARQUET_PAGE_HEADER_DEPTH_LIMIT")
        result: dict[int, object] = {}
        previous = 0
        for _index in range(64):
            header = self.byte()
            if header == 0:
                return result
            kind, delta = header & 15, header >> 4
            field_id = previous + delta if delta else self.signed()
            if field_id <= 0 or field_id in result:
                raise PageLimitError("PARQUET_PAGE_HEADER_FIELDS")
            previous = field_id
            if kind in (1, 2):
                value: object = kind == 1
            elif kind == 3:
                value = self.byte()
            elif kind in (4, 5, 6):
                value = self.signed()
            elif kind == 7:
                value = self.take(8)
            elif kind == 8:
                value = self.take(self.unsigned())
            elif kind == 12:
                value = self.fields(depth + 1)
            else:
                raise PageLimitError("PARQUET_PAGE_HEADER_UNSUPPORTED_TYPE")
            result[field_id] = value
        raise PageLimitError("PARQUET_PAGE_HEADER_FIELD_LIMIT")


def verify_pages(payload: bytes, metadata: Any, *, maximum: int) -> None:
    """Bound page headers/body sizes independently of the footer's size claims."""
    footer_start = len(payload) - 8 - int.from_bytes(payload[-8:-4], "little")
    ranges: list[tuple[int, int]] = []
    expanded = page_count = 0
    for group_index in range(metadata.num_row_groups):
        group = metadata.row_group(group_index)
        for column_index in range(group.num_columns):
            column = group.column(column_index)
            offsets = [column.data_page_offset]
            if column.has_dictionary_page:
                offsets.append(column.dictionary_page_offset)
            start = min(offsets)
            end = start + column.total_compressed_size
            if start < 4 or end <= start or end > footer_start:
                raise PageLimitError("PARQUET_COLUMN_RANGE")
            ranges.append((start, end))
            position, column_expanded, value_count = start, 0, 0
            while position < end:
                page_count += 1
                if page_count > 10_000:
                    raise PageLimitError("PARQUET_PAGE_COUNT_LIMIT")
                reader = _Header(payload, position, end)
                fields = reader.fields()
                page_type, size, compressed = (fields.get(index) for index in (1, 2, 3))
                if any(
                    type(value) is not int for value in (page_type, size, compressed)
                ):
                    raise PageLimitError("PARQUET_PAGE_REQUIRED_FIELDS")
                page_type, size, compressed = (
                    cast(int, value) for value in (page_type, size, compressed)
                )
                if page_type not in (0, 2, 3) or size < 0 or compressed < 0:
                    raise PageLimitError("PARQUET_PAGE_INVALID_SIZE_OR_TYPE")
                if size > maximum or size > max(65_536, compressed * 128):
                    raise PageLimitError("PARQUET_PAGE_EXPANSION_LIMIT")
                if reader.position + compressed > end:
                    raise PageLimitError("PARQUET_PAGE_BODY_RANGE")
                nested = fields.get({0: 5, 2: 7, 3: 8}[page_type])
                if not isinstance(nested, dict) or type(nested.get(1)) is not int:
                    raise PageLimitError("PARQUET_PAGE_VALUE_COUNT")
                count = nested[1]
                if count < 0 or count > group.num_rows:
                    raise PageLimitError("PARQUET_PAGE_VALUE_COUNT")
                if page_type == 3:
                    values = [nested.get(field) for field in (2, 3, 5, 6)]
                    if any(type(value) is not int for value in values):
                        raise PageLimitError("PARQUET_V2_REQUIRED_FIELDS")
                    nulls, page_rows, definitions, repetitions = (
                        cast(int, value) for value in values
                    )
                    # This importer accepts flat columns only: one value per row
                    # and no repeated fields. Level sections are never compressed.
                    if (
                        nulls < 0
                        or nulls > count
                        or page_rows != count
                        or definitions < 0
                        or repetitions != 0
                        or definitions > min(size, compressed)
                        or (7 in nested and type(nested[7]) is not bool)
                    ):
                        raise PageLimitError("PARQUET_V2_LEVEL_OR_ROW_LIMIT")
                if page_type != 2:
                    value_count += count
                header_size = reader.position - position
                expanded += header_size + size
                column_expanded += header_size + size
                if expanded > maximum:
                    raise PageLimitError("PARQUET_PAGE_EXPANSION_LIMIT")
                position = reader.position + compressed
            if (
                column_expanded != column.total_uncompressed_size
                or value_count != group.num_rows
            ):
                raise PageLimitError("PARQUET_PAGE_FOOTER_MISMATCH")
    ordered = sorted(ranges)
    if any(right[0] < left[1] for left, right in pairwise(ordered)):
        raise PageLimitError("PARQUET_OVERLAPPING_COLUMNS")
