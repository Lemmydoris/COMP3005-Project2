import base64
import json
from pathlib import Path

from storage.buffer import BufferPool
from storage.disk import DiskManager
from storage.heap import HeapFile


# A catalog record itself must fit on one 4096-byte page.
#
# Statistics may be much larger than one record because
# Module 4 stores histograms for every column.
#
# Statistics are therefore serialized and split into
# catalog-internal chunk records.
#
# 2400 raw bytes becomes about 3200 base64 bytes, leaving
# comfortable room for the JSON envelope.
STATISTICS_CHUNK_BYTES = 2400


class Catalog:
    """
    Persistent database catalog stored in catalog.db.

    Table metadata remains append-only: the newest metadata
    record for a table is authoritative.

    Module 4 statistics are also stored inside catalog.db,
    but may span several internal statistics-chunk records.

    get_table() reconstructs those chunks so callers still see:

        entry["statistics"]

    as one ordinary dictionary.
    """

    def __init__(
        self,
        db_dir,
        frames=8,
        policy="lru",
    ):

        self.db_dir = Path(
            db_dir
        )

        self.db_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        catalog_path = (
            self.db_dir
            / "catalog.db"
        )

        self.disk = DiskManager(
            catalog_path
        )

        self.buffer = BufferPool(
            self.disk,
            frames=frames,
            policy=policy,
        )

        self.heap = HeapFile(
            "__catalog__",
            self.disk,
            self.buffer,
        )

    # ========================================================
    # Encoding
    # ========================================================

    def _encode_entry(
        self,
        entry,
    ):

        raw = json.dumps(
            entry,
            separators=(",", ":"),
            sort_keys=True,
        ).encode(
            "utf-8"
        )

        if len(raw) > 4088:
            raise ValueError(
                "Catalog entry is too large "
                "for one page."
            )

        return raw

    def _decode_entry(
        self,
        raw,
    ):

        try:

            return json.loads(
                raw.decode(
                    "utf-8"
                )
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):

            raise ValueError(
                "Invalid catalog record."
            )

    # ========================================================
    # Schema validation
    # ========================================================

    def _normalize_schema(
        self,
        schema,
    ):

        if not schema:

            raise ValueError(
                "A table must have at "
                "least one column."
            )

        normalized = []
        names = set()

        for column in schema:

            if len(column) < 2:

                raise ValueError(
                    "Invalid column "
                    "definition."
                )

            name = column[0]

            column_type = (
                column[1].upper()
            )

            if not name:

                raise ValueError(
                    "Column name cannot "
                    "be empty."
                )

            if name in names:

                raise ValueError(
                    f"Duplicate column: "
                    f"{name}"
                )

            names.add(
                name
            )

            # ----------------------------------------------
            # INT
            # ----------------------------------------------

            if column_type == "INT":

                if len(column) != 2:

                    raise ValueError(
                        f"{name}: INT does "
                        "not take a length."
                    )

                normalized.append(
                    [
                        name,
                        "INT",
                    ]
                )

            # ----------------------------------------------
            # VARCHAR
            # ----------------------------------------------

            elif (
                column_type
                == "VARCHAR"
            ):

                if len(column) != 3:

                    raise ValueError(
                        f"{name}: VARCHAR "
                        "requires a length."
                    )

                length = column[2]

                if (
                    not isinstance(
                        length,
                        int,
                    )
                    or length < 1
                    or length > 255
                ):

                    raise ValueError(
                        f"{name}: VARCHAR "
                        "length must be "
                        "between 1 and 255."
                    )

                normalized.append(
                    [
                        name,
                        "VARCHAR",
                        length,
                    ]
                )

            else:

                raise ValueError(
                    f"{name}: unsupported "
                    f"type {column_type}."
                )

        return normalized

    # ========================================================
    # Statistics chunk helpers
    # ========================================================

    def _decode_statistics_version(
        self,
        version_info,
    ):

        count = (
            version_info[
                "count"
            ]
        )

        parts = (
            version_info[
                "parts"
            ]
        )

        if len(parts) != count:
            return None

        try:

            encoded_parts = [
                parts[index]
                for index
                in range(count)
            ]

        except KeyError:

            return None

        try:

            raw = b"".join(
                base64.b64decode(
                    part.encode(
                        "ascii"
                    )
                )
                for part
                in encoded_parts
            )

            return json.loads(
                raw.decode(
                    "utf-8"
                )
            )

        except (
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):

            raise ValueError(
                "Invalid statistics "
                "records in catalog."
            )

    def _latest_statistics_versions(
        self,
    ):
        """
        Return:

            {
                table_name: {
                    version: {
                        "count": N,
                        "parts": {
                            index: base64_text
                        }
                    }
                }
            }
        """

        versions = {}

        for _, raw_record in (
            self.heap.scan()
        ):

            entry = (
                self._decode_entry(
                    raw_record
                )
            )

            if (
                entry.get(
                    "_kind"
                )
                !=
                "statistics_chunk"
            ):
                continue

            name = entry[
                "name"
            ]

            version = entry[
                "version"
            ]

            count = entry[
                "count"
            ]

            index = entry[
                "index"
            ]

            table_versions = (
                versions.setdefault(
                    name,
                    {},
                )
            )

            version_info = (
                table_versions
                .setdefault(
                    version,
                    {
                        "count": count,
                        "parts": {},
                    },
                )
            )

            if (
                version_info[
                    "count"
                ]
                != count
            ):

                raise ValueError(
                    "Inconsistent "
                    "statistics chunk "
                    "count."
                )

            version_info[
                "parts"
            ][
                index
            ] = entry[
                "data"
            ]

        return versions

    def _next_statistics_version(
        self,
        name,
    ):

        versions = (
            self._latest_statistics_versions()
        )

        table_versions = (
            versions.get(
                name,
                {},
            )
        )

        if not table_versions:
            return 1

        return (
            max(
                table_versions
            )
            + 1
        )

    def _write_statistics_chunks(
        self,
        name,
        statistics,
    ):

        raw = json.dumps(
            statistics,
            separators=(",", ":"),
            sort_keys=True,
        ).encode(
            "utf-8"
        )

        version = (
            self._next_statistics_version(
                name
            )
        )

        chunks = [
            raw[
                start:
                start
                + STATISTICS_CHUNK_BYTES
            ]
            for start in range(
                0,
                len(raw),
                STATISTICS_CHUNK_BYTES,
            )
        ]

        # Even {} must create one version.
        if not chunks:
            chunks = [
                b"{}"
            ]

        count = len(
            chunks
        )

        for index, chunk in enumerate(
            chunks
        ):

            entry = {
                "_kind":
                    "statistics_chunk",
                "name":
                    name,
                "version":
                    version,
                "index":
                    index,
                "count":
                    count,
                "data":
                    base64.b64encode(
                        chunk
                    ).decode(
                        "ascii"
                    ),
            }

            self.heap.insert(
                self._encode_entry(
                    entry
                )
            )

        return version

    # ========================================================
    # Reading catalog state
    # ========================================================

    def _current_entries(
        self,
    ):
        """
        Read all table metadata records.

        If a table has several metadata versions,
        the newest metadata record wins.

        Statistics chunk records are collected separately and
        merged into the resulting table dictionary afterward.
        """

        entries = {}
        order = []

        statistics_versions = {}

        for _, raw_record in (
            self.heap.scan()
        ):

            entry = (
                self._decode_entry(
                    raw_record
                )
            )

            # ----------------------------------------------
            # Statistics chunk
            # ----------------------------------------------

            if (
                entry.get(
                    "_kind"
                )
                ==
                "statistics_chunk"
            ):

                name = entry[
                    "name"
                ]

                version = entry[
                    "version"
                ]

                count = entry[
                    "count"
                ]

                index = entry[
                    "index"
                ]

                table_versions = (
                    statistics_versions
                    .setdefault(
                        name,
                        {},
                    )
                )

                version_info = (
                    table_versions
                    .setdefault(
                        version,
                        {
                            "count":
                                count,
                            "parts":
                                {},
                        },
                    )
                )

                if (
                    version_info[
                        "count"
                    ]
                    != count
                ):

                    raise ValueError(
                        "Inconsistent "
                        "statistics chunk "
                        "count."
                    )

                version_info[
                    "parts"
                ][
                    index
                ] = entry[
                    "data"
                ]

                continue

            # ----------------------------------------------
            # Ordinary table metadata
            # ----------------------------------------------

            name = entry[
                "name"
            ]

            if name not in entries:
                order.append(
                    name
                )

            entries[
                name
            ] = entry

        # ----------------------------------------------
        # Overlay latest complete statistics version.
        # ----------------------------------------------

        for (
            name,
            table_versions,
        ) in (
            statistics_versions.items()
        ):

            if name not in entries:
                continue

            for version in sorted(
                table_versions,
                reverse=True,
            ):

                decoded = (
                    self
                    ._decode_statistics_version(
                        table_versions[
                            version
                        ]
                    )
                )

                if decoded is None:
                    continue

                entries[
                    name
                ][
                    "statistics"
                ] = decoded

                break

        return (
            entries,
            order,
        )

    # ========================================================
    # Create table
    # ========================================================

    def create_table(
        self,
        name,
        schema,
    ):

        if not name:

            raise ValueError(
                "Table name cannot "
                "be empty."
            )

        if (
            "/" in name
            or "\\" in name
        ):

            raise ValueError(
                "Invalid table name."
            )

        (
            entries,
            _,
        ) = self._current_entries()

        if name in entries:

            raise ValueError(
                f"Table already "
                f"exists: {name}"
            )

        normalized_schema = (
            self._normalize_schema(
                schema
            )
        )

        table_file_name = (
            f"{name}.db"
        )

        table_path = (
            self.db_dir
            / table_file_name
        )

        if table_path.exists():

            raise ValueError(
                "Data file already "
                "exists: "
                f"{table_file_name}"
            )

        table_disk = DiskManager(
            table_path
        )

        table_buffer = BufferPool(
            table_disk,
            frames=(
                self.buffer.capacity
            ),
            policy=(
                self.buffer.policy
            ),
        )

        HeapFile(
            name,
            table_disk,
            table_buffer,
        )

        table_buffer.flush_all()

        entry = {
            "name":
                name,
            "schema":
                normalized_schema,
            "file":
                table_file_name,
            "num_pages":
                table_disk.num_pages(),
            "num_tuples":
                0,

            # Logical statistics field. Large statistics are
            # later reconstructed from chunk records.
            "statistics":
                {},
        }

        self.heap.insert(
            self._encode_entry(
                entry
            )
        )

        return entry

    # ========================================================
    # Get/list
    # ========================================================

    def get_table(
        self,
        name,
    ):

        (
            entries,
            _,
        ) = self._current_entries()

        if name not in entries:

            raise KeyError(
                f"Unknown table: "
                f"{name}"
            )

        return entries[
            name
        ]

    def list_tables(
        self,
    ):

        (
            entries,
            order,
        ) = self._current_entries()

        return [
            entries[name]
            for name in order
        ]

    # ========================================================
    # Statistics update
    # ========================================================

    def update_statistics(
        self,
        name,
        statistics,
    ):
        """
        Append a new statistics version.

        The statistics are physically stored as one or more
        chunk records inside catalog.db.
        """

        # Verify table exists first.
        self.get_table(
            name
        )

        self._write_statistics_chunks(
            name,
            statistics,
        )

        return self.get_table(
            name
        )

    # ========================================================
    # Metadata update
    # ========================================================

    def update_table(
        self,
        name,
        **changes,
    ):
        """
        Append a newer table metadata version.

        Module 4 statistics are handled specially so large
        histogram state is never forced into one 4088-byte
        catalog record.
        """

        entry = dict(
            self.get_table(
                name
            )
        )

        allowed = {
            "schema",
            "file",
            "num_pages",
            "num_tuples",
            "statistics",
        }

        for key in changes:

            if key not in allowed:

                raise ValueError(
                    "Catalog field "
                    "cannot be updated: "
                    f"{key}"
                )

        marker = object()

        statistics = (
            changes.pop(
                "statistics",
                marker,
            )
        )

        # Do not copy reconstructed large statistics into the
        # ordinary metadata record.
        entry[
            "statistics"
        ] = {}

        if changes:

            entry.update(
                changes
            )

            self.heap.insert(
                self._encode_entry(
                    entry
                )
            )

        if statistics is not marker:

            self._write_statistics_chunks(
                name,
                statistics,
            )

        return self.get_table(
            name
        )

    # ========================================================
    # Flush
    # ========================================================

    def flush(
        self,
    ):

        self.buffer.flush_all()