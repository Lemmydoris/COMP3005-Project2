from tokenizer import Tokenizer
from ra_tree import (
    Relation, Attr, Literal, Comparison, Logical, Not,
    Select, Project, Rename, BinaryOp,
)


class ParseError(Exception):
    pass

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        return self.tokens[self.pos]

    def peek(self, amount=1):
        index = self.pos + amount

        if index >= len(self.tokens):
            return self.tokens[-1]

        return self.tokens[index]

    def advance(self):
        token = self.current()

        if token.type != "EOF":
            self.pos += 1

        return token

    def syntax_error(self, message, token=None):
        if token is None:
            token = self.current()

        raise ParseError(
            f"Syntax error at position {token.position}: {message}"
        )

    def check_type(self, token_type):
        return self.current().type == token_type

    def check_word(self, word):
        token = self.current()

        return (
            token.type == "IDENT"
            and token.value.lower() == word.lower()
        )

    def match_word(self, word):
        if self.check_word(word):
            return self.advance()

        return None

    def expect_type(self, token_type, description=None):
        token = self.current()

        if token.type != token_type:
            if description is None:
                description = token_type

            self.syntax_error(
                f"expected {description}, found {token.value!r}",
                token
            )

        return self.advance()
    
    # Entry point
    def parse(self):
        tree = self.parse_expr()

        if not self.check_type("EOF"):
            self.syntax_error(
                f"unexpected token {self.current().value!r}"
            )

        return tree

    def parse_condition_only(self):
        condition = self.parse_condition()
        if not self.check_type("EOF"):
            self.syntax_error(
                f"unexpected token {self.current().value!r}"
            )
        return condition

    # RELATIONAL EXPRESSIONS
    # expr
    #   -> union
    #   -> intersect
    #   -> times/join
    #   -> unary
    #   -> primary
    def parse_expr(self):
        return self.parse_union()

    def parse_union(self):
        left = self.parse_intersect()

        while self.check_word("union") or self.check_word("minus"):
            op = self.advance().value.lower()
            right = self.parse_intersect()

            left = BinaryOp(op, left, right)

        return left

    def parse_intersect(self):
        left = self.parse_product()

        while self.check_word("intersect"):
            self.advance()
            right = self.parse_product()

            left = BinaryOp("intersect", left, right)

        return left

    def parse_product(self):
        left = self.parse_unary()

        while True:
            if self.check_word("times"):
                self.advance()
                right = self.parse_unary()

                left = BinaryOp("times", left, right)
                continue

            if self.check_word("join"):
                self.advance()

                self.expect_type(
                    "LBRACKET",
                    "'[' after join"
                )

                condition = self.parse_condition()

                self.expect_type(
                    "RBRACKET",
                    "']' after join condition"
                )

                right = self.parse_unary()

                left = BinaryOp(
                    "join",
                    left,
                    right,
                    condition
                )

                continue

            break

        return left

    def parse_unary(self):
        # select[condition](expr)
        if (
            self.check_word("select")
            and self.peek().type == "LBRACKET"
        ):
            self.advance()

            self.expect_type(
                "LBRACKET",
                "'[' after select"
            )

            condition = self.parse_condition()

            self.expect_type(
                "RBRACKET",
                "']' after select condition"
            )

            self.expect_type(
                "LPAREN",
                "'(' after select condition"
            )

            source = self.parse_expr()

            self.expect_type(
                "RPAREN",
                "')' after select input"
            )

            return Select(condition, source)

        # project[attr1, attr2](expr)
        if (
            self.check_word("project")
            and self.peek().type == "LBRACKET"
        ):
            self.advance()

            self.expect_type(
                "LBRACKET",
                "'[' after project"
            )

            if self.check_type("RBRACKET"):
                self.syntax_error(
                    "project requires at least one attribute"
                )

            attributes = self.parse_attribute_list()

            self.expect_type(
                "RBRACKET",
                "']' after project attributes"
            )

            self.expect_type(
                "LPAREN",
                "'(' after project attributes"
            )

            source = self.parse_expr()

            self.expect_type(
                "RPAREN",
                "')' after project input"
            )

            return Project(attributes, source)

        # rename[E2](expr)
        if (
            self.check_word("rename")
            and self.peek().type == "LBRACKET"
        ):
            self.advance()

            self.expect_type(
                "LBRACKET",
                "'[' after rename"
            )

            new_name = self.expect_type(
                "IDENT",
                "new relation name"
            ).value

            self.expect_type(
                "RBRACKET",
                "']' after rename name"
            )

            self.expect_type(
                "LPAREN",
                "'(' after rename"
            )

            source = self.parse_expr()

            self.expect_type(
                "RPAREN",
                "')' after rename input"
            )

            return Rename(new_name, source)

        return self.parse_primary()

    def parse_primary(self):
        # Explicit parentheses:
        # (A union B)
        if self.check_type("LPAREN"):
            self.advance()

            expr = self.parse_expr()

            self.expect_type(
                "RPAREN",
                "')'"
            )
            return expr

        # Relation name
        if self.check_type("IDENT"):
            name = self.advance().value
            return Relation(name)

        self.syntax_error(
            f"expected relation or expression, found "
            f"{self.current().value!r}"
        )

    # ATTRIBUTE LIST
    def parse_attribute_list(self):
        attributes = [self.parse_attribute()]

        while self.check_type("COMMA"):
            self.advance()
            attributes.append(self.parse_attribute())

        return attributes

    def parse_attribute(self):
        first = self.expect_type(
            "IDENT",
            "attribute name"
        )
        # Qualified attribute:
        # Emp.DID
        if self.check_type("DOT"):
            self.advance()

            second = self.expect_type(
                "IDENT",
                "attribute name after '.'"
            )

            return Attr(
                name=second.value,
                relation=first.value
            )

        return Attr(name=first.value)

    # CONDITIONS
    # not > and > or
    def parse_condition(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()

        while self.check_word("or"):
            self.advance()
            right = self.parse_and()

            left = Logical("or", left, right)

        return left

    def parse_and(self):
        left = self.parse_not()

        while self.check_word("and"):
            self.advance()
            right = self.parse_not()

            left = Logical("and", left, right)

        return left

    def parse_not(self):
        if self.check_word("not"):
            self.advance()

            return Not(
                self.parse_not()
            )

        return self.parse_condition_primary()

    def parse_condition_primary(self):

        if self.check_type("LPAREN"):
            self.advance()

            condition = self.parse_condition()

            self.expect_type(
                "RPAREN",
                "')' after condition"
            )

            return condition

        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_operand()

        op_token = self.expect_type(
            "OP",
            "comparison operator"
        )

        right = self.parse_operand()

        return Comparison(
            op_token.value,
            left,
            right
        )

    def parse_operand(self):
        token = self.current()

        if token.type == "NUMBER":
            self.advance()

            return Literal(
                token.value,
                "NUMBER"
            )

        if token.type == "STRING":
            self.advance()

            return Literal(
                token.value,
                "STRING"
            )

        if token.type == "IDENT":
            return self.parse_attribute()

        self.syntax_error(
            f"expected attribute, number, or string, "
            f"found {token.value!r}"
        )


# HELPER FUNCTION
def parse_query(text):
    tokens = Tokenizer(text).tokenize()
    parser = Parser(tokens)
    return parser.parse()


def parse_condition_text(text):
    tokens = Tokenizer(text).tokenize()
    parser = Parser(tokens)
    return parser.parse_condition_only()
