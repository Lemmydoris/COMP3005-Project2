from tokenizer import Tokenizer, LexicalError
from operators import make_relation, RAError

class RelationDefinitionError(Exception):
    pass

class RelationLoader:
    def __init__(self, text):
        self.tokens = Tokenizer(text).tokenize()
        self.pos = 0

    def current(self):
        return self.tokens[self.pos]

    def advance(self):
        token = self.current()

        if token.type != "EOF":
            self.pos += 1

        return token

    def check_type(self, token_type):
        return self.current().type == token_type

    def expect_type(self, token_type, description=None):
        token = self.current()

        if token.type != token_type:
            if description is None:
                description = token_type

            raise RelationDefinitionError(
                f"Relation definition error at position "
                f"{token.position}: expected {description}, "
                f"found {token.value!r}"
            )

        return self.advance()

    def parse_value(self):
        token = self.current()

        if token.type == "NUMBER":
            self.advance()
            return token.value

        if token.type == "STRING":
            self.advance()
            return token.value

        # Bare strings such as John, E1, D1
        if token.type == "IDENT":
            self.advance()
            return token.value

        raise RelationDefinitionError(
            f"Relation definition error at position "
            f"{token.position}: expected a value, "
            f"found {token.value!r}"
        )

    def parse_relation(self):
        # Employees
        name = self.expect_type(
            "IDENT",
            "relation name"
        ).value

        # (
        self.expect_type(
            "LPAREN",
            "'(' after relation name"
        )

        # EID, Name, Age, DID
        attributes = []

        attributes.append(
            self.expect_type(
                "IDENT",
                "attribute name"
            ).value
        )

        while self.check_type("COMMA"):
            self.advance()

            attributes.append(
                self.expect_type(
                    "IDENT",
                    "attribute name"
                ).value
            )

        # )
        self.expect_type(
            "RPAREN",
            "')' after attribute list"
        )

        # =
        equals = self.expect_type(
            "OP",
            "'=' after relation schema"
        )

        if equals.value != "=":
            raise RelationDefinitionError(
                f"Relation definition error at position "
                f"{equals.position}: expected '=', "
                f"found {equals.value!r}"
            )

        # {
        self.expect_type(
            "LBRACE",
            "'{' before relation tuples"
        )
        rows = []

        # We know the relation's arity, so each tuple must contain exactly this many values.
        arity = len(attributes)
        while not self.check_type("RBRACE"):

            if self.check_type("EOF"):
                token = self.current()

                raise RelationDefinitionError(
                    f"Relation definition error at position "
                    f"{token.position}: missing '}}'"
                )

            row = []

            for i in range(arity):
                row.append(self.parse_value())

                if i < arity - 1:
                    self.expect_type(
                        "COMMA",
                        "',' between tuple values"
                    )

            rows.append(tuple(row))
        # }
        self.expect_type(
            "RBRACE",
            "'}' after relation tuples"
        )
        return make_relation(
            name,
            attributes,
            rows
        )

    def parse_all(self):
        relations = {}
        while not self.check_type("EOF"):
            relation = self.parse_relation()

            if relation.name in relations:
                raise RelationDefinitionError(
                    f"Relation {relation.name} "
                    f"is defined more than once"
                )
            relations[relation.name] = relation
        return relations

def load_relations(text):
    loader = RelationLoader(text)
    return loader.parse_all()

def load_relations_file(filename):
    with open(filename, "r", encoding="utf-8") as file:
        return load_relations(file.read())
