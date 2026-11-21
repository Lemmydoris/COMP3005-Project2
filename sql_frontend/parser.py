from sql_frontend.ast import (
    AggregateCall,
    ColumnDef,
    ColumnRef,
    Comparison,
    CreateTable,
    FromCross,
    FromJoin,
    InsertStatement,
    Literal,
    LogicalCondition,
    NotCondition,
    Program,
    SelectItem,
    SelectQuery,
    SetQuery,
    SortItem,
    TableRef,
)
from sql_frontend.lexer import (
    SQLLexError,
    SQLToken,
    tokenize_sql,
)


class SQLSyntaxError(ValueError):

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
            "error: syntax: "
            f"{self.message} "
            f"at line {self.line}, "
            f"column {self.column}"
        )


class SQLParser:

    def __init__(self, text):

        self.tokens = tokenize_sql(
            text
        )

        self.position = 0

    # -------------------------------------------------
    # Token helpers
    # -------------------------------------------------

    def current(self):
        return self.tokens[
            self.position
        ]

    def previous(self):

        if self.position == 0:
            return self.tokens[0]

        return self.tokens[
            self.position - 1
        ]

    def advance(self):

        token = self.current()

        if token.kind != "EOF":
            self.position += 1

        return token

    def check(self, kind):
        return (
            self.current().kind
            == kind
        )

    def match(self, *kinds):

        if self.current().kind in kinds:
            return self.advance()

        return None

    def expect(
        self,
        kind,
        message=None,
    ):

        if self.check(kind):
            return self.advance()

        token = self.current()

        if message is None:
            message = (
                f"Expected {kind}, "
                f"found {token.kind}."
            )

        raise SQLSyntaxError(
            message,
            token.line,
            token.column,
        )

    # -------------------------------------------------
    # Program / statements
    # -------------------------------------------------

    def parse_program(self):

        statements = []

        while not self.check("EOF"):

            statements.append(
                self.parse_statement()
            )

            if self.match(
                "SEMICOLON"
            ):

                # Allow harmless additional
                # semicolons between statements.
                while self.match(
                    "SEMICOLON"
                ):
                    pass

            elif not self.check("EOF"):

                token = self.current()

                raise SQLSyntaxError(
                    (
                        "Expected ';' between "
                        "SQL statements."
                    ),
                    token.line,
                    token.column,
                )

        return Program(
            statements=statements
        )

    def parse_statement(self):

        if self.check("CREATE"):
            return (
                self.parse_create_table()
            )

        if self.check("INSERT"):
            return (
                self.parse_insert()
            )

        if (
            self.check("SELECT")
            or self.check("LPAREN")
        ):
            return self.parse_query()

        token = self.current()

        raise SQLSyntaxError(
            (
                "Expected CREATE, INSERT, "
                "or SELECT statement."
            ),
            token.line,
            token.column,
        )

    # -------------------------------------------------
    # CREATE TABLE
    # -------------------------------------------------

    def parse_create_table(self):

        start = self.expect(
            "CREATE"
        )

        self.expect(
            "TABLE",
            "Expected TABLE after CREATE.",
        )

        name = self.expect(
            "IDENT",
            "Expected table name.",
        )

        self.expect(
            "LPAREN",
            (
                "Expected '(' after "
                "table name."
            ),
        )

        columns = [
            self.parse_column_def()
        ]

        while self.match("COMMA"):
            columns.append(
                self.parse_column_def()
            )

        self.expect(
            "RPAREN",
            (
                "Expected ')' after "
                "column definitions."
            ),
        )

        return CreateTable(
            name=name.value,
            columns=columns,
            line=start.line,
            column=start.column,
        )

    def parse_column_def(self):

        name = self.expect(
            "IDENT",
            "Expected column name.",
        )

        if self.match("INT"):

            return ColumnDef(
                name=name.value,
                type_name="INT",
                line=name.line,
                column=name.column,
            )

        if self.match("VARCHAR"):

            self.expect(
                "LPAREN",
                (
                    "Expected '(' after "
                    "VARCHAR."
                ),
            )

            length = self.expect(
                "INTEGER",
                (
                    "Expected VARCHAR "
                    "length."
                ),
            )

            self.expect(
                "RPAREN",
                (
                    "Expected ')' after "
                    "VARCHAR length."
                ),
            )

            return ColumnDef(
                name=name.value,
                type_name="VARCHAR",
                length=length.value,
                line=name.line,
                column=name.column,
            )

        token = self.current()

        raise SQLSyntaxError(
            (
                "Expected INT or VARCHAR "
                "in column definition."
            ),
            token.line,
            token.column,
        )

    # -------------------------------------------------
    # INSERT
    # -------------------------------------------------

    def parse_insert(self):

        start = self.expect(
            "INSERT"
        )

        self.expect(
            "INTO",
            "Expected INTO after INSERT.",
        )

        table = self.expect(
            "IDENT",
            "Expected table name.",
        )

        self.expect(
            "VALUES",
            (
                "Expected VALUES after "
                "table name."
            ),
        )

        self.expect(
            "LPAREN",
            (
                "Expected '(' after "
                "VALUES."
            ),
        )

        values = [
            self.parse_literal()
        ]

        while self.match("COMMA"):
            values.append(
                self.parse_literal()
            )

        self.expect(
            "RPAREN",
            (
                "Expected ')' after "
                "VALUES list."
            ),
        )

        return InsertStatement(
            table=table.value,
            values=values,
            line=start.line,
            column=start.column,
        )

    def parse_literal(self):

        token = self.current()

        if token.kind == "INTEGER":

            self.advance()

            return Literal(
                value=token.value,
                kind="INT",
                line=token.line,
                column=token.column,
            )

        if token.kind == "STRING":

            self.advance()

            return Literal(
                value=token.value,
                kind="VARCHAR",
                line=token.line,
                column=token.column,
            )

        raise SQLSyntaxError(
            "Expected literal value.",
            token.line,
            token.column,
        )

    # -------------------------------------------------
    # Queries / set operations
    # -------------------------------------------------

    def parse_query(self):

        left = self.parse_select_block()

        # All set operators have the same
        # precedence and are left associative.
        while self.current().kind in {
            "UNION",
            "INTERSECT",
            "EXCEPT",
        }:

            operator_token = (
                self.advance()
            )

            if (
                operator_token.kind
                == "UNION"
            ):

                if self.match("ALL"):
                    operator = "union_all"
                else:
                    operator = "union"

            elif (
                operator_token.kind
                == "INTERSECT"
            ):
                operator = "intersect"

            else:
                operator = "except"

            right = (
                self.parse_select_block()
            )

            left = SetQuery(
                left=left,
                operator=operator,
                right=right,
                line=operator_token.line,
                column=(
                    operator_token.column
                ),
            )

        return left

    def parse_select_block(self):

        # Parenthesized query.
        if self.match("LPAREN"):

            query = self.parse_query()

            self.expect(
                "RPAREN",
                (
                    "Expected ')' after "
                    "parenthesized query."
                ),
            )

            return query

        start = self.expect(
            "SELECT",
            "Expected SELECT.",
        )

        distinct = (
            self.match("DISTINCT")
            is not None
        )

        select_all = False
        items = []

        if self.match("STAR"):

            select_all = True

        else:

            items.append(
                self.parse_select_item()
            )

            while self.match("COMMA"):
                items.append(
                    self.parse_select_item()
                )

        self.expect(
            "FROM",
            (
                "Expected FROM after "
                "SELECT list."
            ),
        )

        from_source = (
            self.parse_from_source()
        )

        where = None
        group_by = []
        having = None
        order_by = []
        limit = None

        if self.match("WHERE"):

            where = (
                self.parse_condition()
            )

        if self.match("GROUP"):

            self.expect(
                "BY",
                (
                    "Expected BY after "
                    "GROUP."
                ),
            )

            group_by.append(
                self.parse_column_ref()
            )

            while self.match("COMMA"):
                group_by.append(
                    self.parse_column_ref()
                )

            if self.match("HAVING"):
                having = (
                    self.parse_condition()
                )

        elif self.check("HAVING"):

            token = self.current()

            raise SQLSyntaxError(
                (
                    "HAVING requires "
                    "GROUP BY."
                ),
                token.line,
                token.column,
            )

        if self.match("ORDER"):

            self.expect(
                "BY",
                (
                    "Expected BY after "
                    "ORDER."
                ),
            )

            order_by.append(
                self.parse_sort_item()
            )

            while self.match("COMMA"):
                order_by.append(
                    self.parse_sort_item()
                )

        if self.match("LIMIT"):

            value = self.expect(
                "INTEGER",
                (
                    "Expected integer "
                    "after LIMIT."
                ),
            )

            limit = value.value

        return SelectQuery(
            distinct=distinct,
            select_all=select_all,
            items=items,
            from_source=from_source,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            line=start.line,
            column=start.column,
        )

    # -------------------------------------------------
    # SELECT list
    # -------------------------------------------------

    def parse_select_item(self):

        token = self.current()

        if token.kind in {
            "COUNT",
            "SUM",
            "AVG",
            "MIN",
            "MAX",
        }:
            expression = (
                self.parse_aggregate()
            )

        else:
            expression = (
                self.parse_column_ref()
            )

        alias = None

        if self.match("AS"):

            alias_token = self.expect(
                "IDENT",
                (
                    "Expected alias "
                    "after AS."
                ),
            )

            alias = (
                alias_token.value
            )

        return SelectItem(
            expression=expression,
            alias=alias,
            line=token.line,
            column=token.column,
        )

    def parse_aggregate(self):

        function_token = (
            self.advance()
        )

        self.expect(
            "LPAREN",
            (
                "Expected '(' after "
                "aggregate name."
            ),
        )

        if self.match("STAR"):

            argument = None

        else:
            argument = (
                self.parse_column_ref()
            )

        self.expect(
            "RPAREN",
            (
                "Expected ')' after "
                "aggregate argument."
            ),
        )

        return AggregateCall(
            function=(
                function_token.kind.lower()
            ),
            argument=argument,
            line=function_token.line,
            column=function_token.column,
        )

    # -------------------------------------------------
    # FROM
    # -------------------------------------------------

    def parse_from_source(self):

        left = self.parse_table_ref()

        while True:

            comma = self.match(
                "COMMA"
            )

            if comma is not None:

                right = (
                    self.parse_table_ref()
                )

                left = FromCross(
                    left=left,
                    right=right,
                    line=comma.line,
                    column=comma.column,
                )

                continue

            join = self.match(
                "JOIN"
            )

            if join is not None:

                right = (
                    self.parse_table_ref()
                )

                self.expect(
                    "ON",
                    (
                        "Expected ON after "
                        "JOIN table."
                    ),
                )

                condition = (
                    self.parse_condition()
                )

                left = FromJoin(
                    left=left,
                    right=right,
                    condition=condition,
                    line=join.line,
                    column=join.column,
                )

                continue

            break

        return left

    def parse_table_ref(self):

        token = self.current()

        # FROM subquery.
        if self.match("LPAREN"):

            query = self.parse_query()

            self.expect(
                "RPAREN",
                (
                    "Expected ')' after "
                    "FROM subquery."
                ),
            )

            self.expect(
                "AS",
                (
                    "A subquery in FROM "
                    "requires AS and an alias."
                ),
            )

            alias = self.expect(
                "IDENT",
                (
                    "Expected alias for "
                    "FROM subquery."
                ),
            )

            return TableRef(
                name=None,
                alias=alias.value,
                subquery=query,
                line=token.line,
                column=token.column,
            )

        name = self.expect(
            "IDENT",
            (
                "Expected table name "
                "or subquery."
            ),
        )

        alias = None

        if self.match("AS"):

            alias_token = self.expect(
                "IDENT",
                (
                    "Expected alias "
                    "after AS."
                ),
            )

            alias = (
                alias_token.value
            )

        # Required examples use:
        #
        #     FROM Emp e
        #
        # even though the grammar sketch
        # writes [AS ident]. Accept both.
        elif self.check("IDENT"):

            alias = (
                self.advance().value
            )

        return TableRef(
            name=name.value,
            alias=alias,
            subquery=None,
            line=name.line,
            column=name.column,
        )

    # -------------------------------------------------
    # ORDER BY
    # -------------------------------------------------

    def parse_sort_item(self):

        column_ref = (
            self.parse_column_ref()
        )

        direction = "asc"

        if self.match("ASC"):
            direction = "asc"

        elif self.match("DESC"):
            direction = "desc"

        return SortItem(
            column_ref=column_ref,
            direction=direction,
            line=column_ref.line,
            column=column_ref.column,
        )

    # -------------------------------------------------
    # Conditions
    #
    # Precedence:
    #     NOT
    #     AND
    #     OR
    # -------------------------------------------------

    def parse_condition(self):
        return self.parse_or()

    def parse_or(self):

        left = self.parse_and()

        while True:

            operator = self.match(
                "OR"
            )

            if operator is None:
                break

            right = self.parse_and()

            left = LogicalCondition(
                operator="or",
                left=left,
                right=right,
                line=operator.line,
                column=operator.column,
            )

        return left

    def parse_and(self):

        left = self.parse_not()

        while True:

            operator = self.match(
                "AND"
            )

            if operator is None:
                break

            right = self.parse_not()

            left = LogicalCondition(
                operator="and",
                left=left,
                right=right,
                line=operator.line,
                column=operator.column,
            )

        return left

    def parse_not(self):

        token = self.match("NOT")

        if token is not None:

            return NotCondition(
                child=self.parse_not(),
                line=token.line,
                column=token.column,
            )

        return (
            self.parse_condition_primary()
        )

    def parse_condition_primary(self):

        if self.match("LPAREN"):

            condition = (
                self.parse_condition()
            )

            self.expect(
                "RPAREN",
                (
                    "Expected ')' after "
                    "condition."
                ),
            )

            return condition

        return self.parse_comparison()

    def parse_comparison(self):

        left = self.parse_operand()

        operator = self.expect(
            "OP",
            (
                "Expected comparison "
                "operator."
            ),
        )

        right = self.parse_operand()

        return Comparison(
            left=left,
            operator=operator.value,
            right=right,
            line=operator.line,
            column=operator.column,
        )

    def parse_operand(self):

        token = self.current()

        if token.kind == "INTEGER":

            self.advance()

            return Literal(
                value=token.value,
                kind="INT",
                line=token.line,
                column=token.column,
            )

        if token.kind == "STRING":

            self.advance()

            return Literal(
                value=token.value,
                kind="VARCHAR",
                line=token.line,
                column=token.column,
            )

        if token.kind in {
            "COUNT",
            "SUM",
            "AVG",
            "MIN",
            "MAX",
        }:
            return (
                self.parse_aggregate()
            )

        if token.kind == "IDENT":
            return (
                self.parse_column_ref()
            )

        raise SQLSyntaxError(
            (
                "Expected column, "
                "aggregate, integer, "
                "or string."
            ),
            token.line,
            token.column,
        )

    # -------------------------------------------------
    # Columns
    # -------------------------------------------------

    def parse_column_ref(self):

        first = self.expect(
            "IDENT",
            "Expected column name.",
        )

        if self.match("DOT"):

            second = self.expect(
                "IDENT",
                (
                    "Expected column name "
                    "after '.'."
                ),
            )

            return ColumnRef(
                name=second.value,
                qualifier=first.value,
                line=first.line,
                column=first.column,
            )

        return ColumnRef(
            name=first.value,
            qualifier=None,
            line=first.line,
            column=first.column,
        )


def parse_sql(text):
    return SQLParser(
        text
    ).parse_program()