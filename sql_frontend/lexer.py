from dataclasses import dataclass


KEYWORDS = {
    "CREATE",
    "TABLE",
    "INSERT",
    "INTO",
    "VALUES",
    "SELECT",
    "DISTINCT",
    "FROM",
    "WHERE",
    "GROUP",
    "BY",
    "HAVING",
    "ORDER",
    "ASC",
    "DESC",
    "LIMIT",
    "UNION",
    "ALL",
    "INTERSECT",
    "EXCEPT",
    "AS",
    "JOIN",
    "ON",
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "INT",
    "VARCHAR",
    "AND",
    "OR",
    "NOT",
}


@dataclass(frozen=True)
class SQLToken:
    kind: str
    value: object
    line: int
    column: int

    def __repr__(self):
        return (
            f"SQLToken("
            f"{self.kind!r}, "
            f"{self.value!r}, "
            f"line={self.line}, "
            f"column={self.column}"
            f")"
        )


class SQLLexError(ValueError):

    def __init__(
        self,
        message,
        line,
        column,
    ):
        super().__init__(message)

        self.message = message
        self.line = line
        self.column = column

    def __str__(self):
        return (
            f"error: lexical: "
            f"{self.message} "
            f"at line {self.line}, "
            f"column {self.column}"
        )


class SQLLexer:

    def __init__(self, text):
        self.text = text
        self.length = len(text)

        self.position = 0
        self.line = 1
        self.column = 1

    def _current(self):

        if self.position >= self.length:
            return None

        return self.text[
            self.position
        ]

    def _peek(self, amount=1):

        index = (
            self.position
            + amount
        )

        if index >= self.length:
            return None

        return self.text[index]

    def _advance(self):

        char = self._current()

        if char is None:
            return None

        self.position += 1

        if char == "\n":
            self.line += 1
            self.column = 1

        else:
            self.column += 1

        return char

    def _skip_whitespace_and_comments(self):

        while True:

            char = self._current()

            if char is None:
                return

            if char.isspace():
                self._advance()
                continue

            # SQL line comment.
            if (
                char == "-"
                and self._peek() == "-"
            ):
                self._advance()
                self._advance()

                while (
                    self._current()
                    is not None
                    and self._current()
                    != "\n"
                ):
                    self._advance()

                continue

            return

    def _identifier_or_keyword(self):

        start_line = self.line
        start_column = self.column

        characters = []

        while True:

            char = self._current()

            if char is None:
                break

            if not (
                char.isalpha()
                or char.isdigit()
                or char == "_"
            ):
                break

            characters.append(
                self._advance()
            )

        value = "".join(
            characters
        )

        upper = value.upper()

        if upper in KEYWORDS:
            return SQLToken(
                upper,
                upper,
                start_line,
                start_column,
            )

        return SQLToken(
            "IDENT",
            value,
            start_line,
            start_column,
        )

    def _number(self):

        start_line = self.line
        start_column = self.column

        characters = []

        if self._current() in {
            "+",
            "-",
        }:
            characters.append(
                self._advance()
            )

        while (
            self._current()
            is not None
            and self._current().isdigit()
        ):
            characters.append(
                self._advance()
            )

        value = int(
            "".join(
                characters
            )
        )

        return SQLToken(
            "INTEGER",
            value,
            start_line,
            start_column,
        )

    def _string(self):

        start_line = self.line
        start_column = self.column

        # Opening single quote.
        self._advance()

        characters = []

        while True:

            char = self._current()

            if char is None:
                raise SQLLexError(
                    "Unterminated string literal.",
                    start_line,
                    start_column,
                )

            if char == "'":

                # SQL escaping:
                # '' means one literal '
                if self._peek() == "'":
                    self._advance()
                    self._advance()

                    characters.append(
                        "'"
                    )

                    continue

                # Closing quote.
                self._advance()

                break

            characters.append(
                self._advance()
            )

        return SQLToken(
            "STRING",
            "".join(characters),
            start_line,
            start_column,
        )

    def _comparison_operator(self):

        start_line = self.line
        start_column = self.column

        first = self._advance()

        second = self._current()

        if (
            first == "<"
            and second in {
                "=",
                ">",
            }
        ):
            value = (
                first
                + self._advance()
            )

        elif (
            first == ">"
            and second == "="
        ):
            value = (
                first
                + self._advance()
            )

        else:
            value = first

        return SQLToken(
            "OP",
            value,
            start_line,
            start_column,
        )

    def next_token(self):

        self._skip_whitespace_and_comments()

        char = self._current()

        if char is None:
            return SQLToken(
                "EOF",
                None,
                self.line,
                self.column,
            )

        start_line = self.line
        start_column = self.column

        # Identifier / keyword.
        if (
            char.isalpha()
            or char == "_"
        ):
            return (
                self._identifier_or_keyword()
            )

        # Integer.
        if char.isdigit():
            return self._number()

        # Signed integer.
        if (
            char in {
                "+",
                "-",
            }
            and self._peek()
            is not None
            and self._peek().isdigit()
        ):
            return self._number()

        # String.
        if char == "'":
            return self._string()

        # Comparison operators.
        if char in {
            "=",
            "<",
            ">",
        }:
            return (
                self._comparison_operator()
            )

        punctuation = {
            "(": "LPAREN",
            ")": "RPAREN",
            ",": "COMMA",
            ".": "DOT",
            "*": "STAR",
            ";": "SEMICOLON",
        }

        if char in punctuation:

            self._advance()

            return SQLToken(
                punctuation[char],
                char,
                start_line,
                start_column,
            )

        raise SQLLexError(
            (
                "Unexpected character "
                f"{char!r}."
            ),
            start_line,
            start_column,
        )

    def tokenize(self):

        tokens = []

        while True:

            token = self.next_token()

            tokens.append(
                token
            )

            if token.kind == "EOF":
                break

        return tokens


def tokenize_sql(text):
    return SQLLexer(
        text
    ).tokenize()