import csv
from pathlib import Path

from storage.buffer import BufferPool
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.record import encode_record

class TableLoader:
    """
    Loads a no-header CSV file into an existing table.
    """

    def __init__(
        self,
        catalog,
        frames=8,
        policy="lru"
    ):
        self.catalog = catalog
        self.frames = frames
        self.policy = policy

    # Convert one CSV row
    def _convert_row(
        self,
        schema,
        row,
        line_number
    ):

        if len(row) != len(schema):
            raise ValueError(
                f"Line {line_number}: expected "
                f"{len(schema)} fields but found "
                f"{len(row)}."
            )

        values = []

        for column, raw_value in zip(
            schema,
            row
        ):

            column_name = column[0]
            column_type = column[1]

            # INT
            if column_type == "INT":

                try:
                    value = int(raw_value)

                except ValueError:
                    raise ValueError(
                        f"Line {line_number}: "
                        f"{column_name} must be an INT."
                    )

                values.append(value)

            # VARCHAR
            elif column_type == "VARCHAR":

                max_length = column[2]

                byte_length = len(
                    raw_value.encode("utf-8")
                )

                if byte_length > max_length:
                    raise ValueError(
                        f"Line {line_number}: "
                        f"{column_name} exceeds "
                        f"VARCHAR({max_length})."
                    )

                values.append(raw_value)

            else:
                raise ValueError(
                    f"Line {line_number}: unsupported "
                    f"type {column_type}."
                )

        return tuple(values)

    # Load
    def load(
        self,
        table_name,
        csv_file
    ):

        metadata = self.catalog.get_table(
            table_name
        )

        schema = metadata["schema"]

        table_path = (
            self.catalog.db_dir
            / metadata["file"]
        )

        csv_path = Path(csv_file)

        if not csv_path.exists():
            raise FileNotFoundError(
                f"CSV file not found: {csv_path}"
            )

        disk = DiskManager(
            table_path
        )

        buffer = BufferPool(
            disk,
            frames=self.frames,
            policy=self.policy
        )

        heap = HeapFile(
            table_name,
            disk,
            buffer
        )

        inserted = 0
        starting_tuple_count = (
            metadata["num_tuples"]
        )

        try:

            with csv_path.open(
                "r",
                newline="",
                encoding="utf-8"
            ) as file:

                reader = csv.reader(file)

                for line_number, row in enumerate(
                    reader,
                    start=1
                ):

                    values = self._convert_row(
                        schema,
                        row,
                        line_number
                    )

                    try:
                        encoded = encode_record(
                            schema,
                            values
                        )

                    except (
                        ValueError,
                        TypeError
                    ) as error:
                        raise ValueError(
                            f"Line {line_number}: "
                            f"{error}"
                        )

                    if len(encoded) > 4088:
                        raise ValueError(
                            f"Line {line_number}: "
                            f"table {table_name}, "
                            f"row {line_number}: "
                            "record is larger than "
                            "4088 bytes."
                        )

                    heap.insert(encoded)

                    inserted += 1

        except csv.Error as error:
            # Keep successful rows before the bad line consistent on disk and in the catalog.
            buffer.flush_all()

            self.catalog.update_table(
                table_name,
                num_pages=disk.num_pages(),
                num_tuples=(
                    starting_tuple_count
                    + inserted
                )
            )

            self.catalog.flush()

            raise ValueError(
                f"CSV error near line "
                f"{reader.line_num}: {error}"
            )

        except Exception:
            # The specification says loading stops on an invalid row. Rows successfully inserted before that row remain stored.
            buffer.flush_all()

            self.catalog.update_table(
                table_name,
                num_pages=disk.num_pages(),
                num_tuples=(
                    starting_tuple_count
                    + inserted
                )
            )

            self.catalog.flush()

            raise

        # Successful load
        buffer.flush_all()

        updated = self.catalog.update_table(
            table_name,
            num_pages=disk.num_pages(),
            num_tuples=(
                starting_tuple_count
                + inserted
            )
        )
        self.catalog.flush()

        return {
            "table": table_name,
            "rows_loaded": inserted,
            "num_pages": updated["num_pages"],
            "num_tuples": updated["num_tuples"]
        }