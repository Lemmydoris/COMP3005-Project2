import struct

def encode_record(schema, values):
    """
    Convert a tuple of Python values into the exact byte format
    required by Module 1.

    Schema examples:
        [
            ("a", "INT"),
            ("b", "VARCHAR", 5),
            ("c", "INT")
        ]
    """

    if len(schema) != len(values):
        raise ValueError(
            "Number of values does not match the schema."
        )
    encoded = bytearray()

    for column, value in zip(schema, values):
        column_name = column[0]
        column_type = column[1]

        # INT
        if column_type == "INT":
            if value is None:
                raise ValueError(
                    f"{column_name}: NULL values are not allowed."
                )

            if not isinstance(value, int):
                raise TypeError(
                    f"{column_name}: expected INT."
                )

            try:
                encoded.extend(
                    struct.pack("<i", value)
                )
            except struct.error:
                raise ValueError(
                    f"{column_name}: INT value is out of range."
                )

        # VARCHAR(n)
        elif column_type == "VARCHAR":
            if len(column) != 3:
                raise ValueError(
                    f"{column_name}: VARCHAR requires a maximum length."
                )

            max_length = column[2]

            if value is None:
                raise ValueError(
                    f"{column_name}: NULL values are not allowed."
                )

            if not isinstance(value, str):
                raise TypeError(
                    f"{column_name}: expected VARCHAR."
                )

            raw_string = value.encode("utf-8")
            length = len(raw_string)

            if length > max_length:
                raise ValueError(
                    f"{column_name}: VARCHAR value exceeds "
                    f"maximum length {max_length}."
                )

            #Two-byte unsigned length.
            encoded.extend(
                struct.pack("<H", length)
            )

            # hen the UTF-8 bytes.
            encoded.extend(raw_string)

        else:
            raise ValueError(
                f"{column_name}: unsupported type {column_type}."
            )

    return bytes(encoded)

def decode_record(schema, record):
    """
    Convert raw record bytes back into Python values.
    """

    values = []
    position = 0

    for column in schema:
        column_name = column[0]
        column_type = column[1]

        # INT
        if column_type == "INT":
            if position + 4 > len(record):
                raise ValueError(
                    f"{column_name}: record ended unexpectedly."
                )

            value = struct.unpack_from(
                "<i",
                record,
                position
            )[0]

            values.append(value)
            position += 4

        # VARCHAR(n)
        elif column_type == "VARCHAR":
            max_length = column[2]

            if position + 2 > len(record):
                raise ValueError(
                    f"{column_name}: record ended unexpectedly."
                )

            length = struct.unpack_from(
                "<H",
                record,
                position
            )[0]

            position += 2

            if length > max_length:
                raise ValueError(
                    f"{column_name}: stored VARCHAR length "
                    f"exceeds schema maximum."
                )

            if position + length > len(record):
                raise ValueError(
                    f"{column_name}: record ended unexpectedly."
                )

            raw_string = record[
                position:position + length
            ]

            try:
                value = raw_string.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError(
                    f"{column_name}: invalid UTF-8 data."
                )

            values.append(value)
            position += length

        else:
            raise ValueError(
                f"{column_name}: unsupported type {column_type}."
            )

    if position != len(record):
        raise ValueError(
            "Record contains extra bytes."
        )

    return tuple(values)