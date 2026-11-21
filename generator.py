import random

def generate_relations(n, m=None, match_rate=1):
    if m is None:
        m = n

    r_rows = []
    s_rows = []

    # R(a, b)
    for i in range(n):
        b_value = i // max(1, match_rate)

        r_rows.append(
            (i, b_value)
        )

    # S(b, c)
    for i in range(m):
        b_value = i // max(1, match_rate)

        s_rows.append(
            (b_value, i)
        )

    return r_rows, s_rows

def write_relation_file(
    filename,
    n,
    m=None,
    match_rate=1
):
    if m is None:
        m = n

    r_rows, s_rows = generate_relations(
        n,
        m,
        match_rate
    )

    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as file:

        file.write("R (a, b) = {\n")

        for a, b in r_rows:
            file.write(
                f"    {a}, {b}\n"
            )

        file.write("}\n\n")

        file.write("S (b, c) = {\n")

        for b, c in s_rows:
            file.write(
                f"    {b}, {c}\n"
            )

        file.write("}\n")

if __name__ == "__main__":
    write_relation_file(
        "generated.ra",
        n=10,
        m=10,
        match_rate=1
    )
    print(
        "Created generated.ra "
        "with 10 tuples per relation."
    )