"""Small subset of bitstruct used by the vendored Bumble A2DP helpers.

The upstream ``bitstruct`` package is not present in the minimal rootfs. Bumble's
``a2dp.py`` only needs unsigned integer fields (``uN``) and padding fields
(``pN``), packed most-significant-bit first.
"""


def _parse_format(fmt):
    fields = []
    index = 0
    while index < len(fmt):
        kind = fmt[index]
        index += 1
        start = index
        while index < len(fmt) and fmt[index].isdigit():
            index += 1
        if kind not in ("u", "p") or start == index:
            raise ValueError(f"unsupported bitstruct field near {fmt[start - 1:]!r}")
        fields.append((kind, int(fmt[start:index])))
    return fields


def unpack(fmt, data):
    fields = _parse_format(fmt)
    total_bits = sum(width for _, width in fields)
    value = int.from_bytes(data[: (total_bits + 7) // 8], "big")
    shift = ((total_bits + 7) // 8) * 8 - total_bits
    value >>= shift

    values = []
    remaining = total_bits
    for kind, width in fields:
        remaining -= width
        field = (value >> remaining) & ((1 << width) - 1)
        if kind == "u":
            values.append(field)
    return tuple(values)


def pack(fmt, *values):
    fields = _parse_format(fmt)
    expected = sum(1 for kind, _ in fields if kind == "u")
    if len(values) != expected:
        raise ValueError(f"expected {expected} values, got {len(values)}")

    value = 0
    cursor = iter(values)
    total_bits = 0
    for kind, width in fields:
        total_bits += width
        value <<= width
        if kind == "u":
            field = next(cursor)
            if field < 0 or field >= (1 << width):
                raise ValueError(f"value {field} does not fit in u{width}")
            value |= field

    byte_count = (total_bits + 7) // 8
    value <<= byte_count * 8 - total_bits
    return value.to_bytes(byte_count, "big")
