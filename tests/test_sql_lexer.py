import unittest

from sql_frontend.lexer import (
    SQLLexError,
    tokenize_sql,
)


class SQLLexerTests(unittest.TestCase):

    def without_eof(
        self,
        text,
    ):
        return tokenize_sql(
            text
        )[:-1]

    def test_keywords_are_case_insensitive_but_identifiers_keep_case(
        self,
    ):

        tokens = self.without_eof(
            "SeLeCt Name FROM Emp"
        )

        self.assertEqual(
            [
                token.kind
                for token in tokens
            ],
            [
                "SELECT",
                "IDENT",
                "FROM",
                "IDENT",
            ],
        )

        self.assertEqual(
            tokens[1].value,
            "Name",
        )

        self.assertEqual(
            tokens[3].value,
            "Emp",
        )

    def test_punctuation_and_qualified_columns(
        self,
    ):

        tokens = self.without_eof(
            "SELECT e.*, d.title "
            "FROM Emp AS e;"
        )

        self.assertEqual(
            [
                token.kind
                for token in tokens
            ],
            [
                "SELECT",
                "IDENT",
                "DOT",
                "STAR",
                "COMMA",
                "IDENT",
                "DOT",
                "IDENT",
                "FROM",
                "IDENT",
                "AS",
                "IDENT",
                "SEMICOLON",
            ],
        )

    def test_string_escaping(
        self,
    ):

        tokens = self.without_eof(
            "SELECT name FROM Emp "
            "WHERE name = 'O''Brien'"
        )

        string_token = [
            token
            for token in tokens
            if token.kind == "STRING"
        ][0]

        self.assertEqual(
            string_token.value,
            "O'Brien",
        )

    def test_signed_integers(
        self,
    ):

        tokens = self.without_eof(
            "INSERT INTO T "
            "VALUES (-10, +20, 30)"
        )

        values = [
            token.value
            for token in tokens
            if token.kind == "INTEGER"
        ]

        self.assertEqual(
            values,
            [
                -10,
                20,
                30,
            ],
        )

    def test_comparison_operators_use_maximal_munch(
        self,
    ):

        tokens = self.without_eof(
            "a<=1 AND b>=2 AND "
            "c<>3 AND d<4 AND "
            "e>5 AND f=6"
        )

        operators = [
            token.value
            for token in tokens
            if token.kind == "OP"
        ]

        self.assertEqual(
            operators,
            [
                "<=",
                ">=",
                "<>",
                "<",
                ">",
                "=",
            ],
        )

    def test_comments_are_skipped_and_line_numbers_advance(
        self,
    ):

        tokens = self.without_eof(
            "SELECT a -- ignore this\n"
            "FROM Emp"
        )

        self.assertEqual(
            [
                token.kind
                for token in tokens
            ],
            [
                "SELECT",
                "IDENT",
                "FROM",
                "IDENT",
            ],
        )

        self.assertEqual(
            tokens[2].line,
            2,
        )

        self.assertEqual(
            tokens[2].column,
            1,
        )

    def test_semicolon_separates_multiple_statements(
        self,
    ):

        tokens = self.without_eof(
            "SELECT a FROM R;"
            "SELECT b FROM S;"
        )

        semicolons = [
            token
            for token in tokens
            if (
                token.kind
                == "SEMICOLON"
            )
        ]

        self.assertEqual(
            len(semicolons),
            2,
        )

    def test_unterminated_string_is_lexical_error(
        self,
    ):

        with self.assertRaisesRegex(
            SQLLexError,
            "Unterminated string",
        ):
            tokenize_sql(
                "SELECT * FROM Emp "
                "WHERE name = 'Bob"
            )

    def test_unexpected_character_is_lexical_error(
        self,
    ):

        with self.assertRaisesRegex(
            SQLLexError,
            "Unexpected character",
        ):
            tokenize_sql(
                "SELECT @ FROM Emp"
            )


if __name__ == "__main__":
    unittest.main()