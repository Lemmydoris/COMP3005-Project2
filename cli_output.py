def format_table(table):
    headers = [column.display_name() for column in table.columns]
    lines = [" | ".join(headers), "-" * max(1, len(" | ".join(headers)))]
    lines.extend(" | ".join(str(value) for value in row) for row in table.rows)
    if not table.rows:
        lines.append("(empty)")
    return "\n".join(lines)
