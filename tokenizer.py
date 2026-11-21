from dataclasses import dataclass

class LexicalError(Exception):
    pass

@dataclass
class Token:
    type: str
    value: object
    position: int

    def __repr__(self):
        return f"Token({self.type!r}, {self.value!r}, pos={self.position})"

class Tokenizer:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.tokens = []

    def current(self):
        if self.pos >= len(self.text):
            return "\0"
        return self.text[self.pos]

    def peek(self):
        if self.pos + 1 >= len(self.text):
            return "\0"
        return self.text[self.pos + 1]

    def advance(self):
        self.pos += 1

    def is_letter(self, ch):
        return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"

    def is_digit(self, ch):
        return "0" <= ch <= "9"

    def scan_identifier(self):
        start = self.pos
        value = ""

        while self.is_letter(self.current()) or self.is_digit(self.current()):
            value += self.current()
            self.advance()

        return Token("IDENT", value, start)

    def scan_number(self):
        start = self.pos
        value = ""

        if self.current() == "-":
            value += "-"
            self.advance()

        while self.is_digit(self.current()):
            value += self.current()
            self.advance()

        if self.current() == "." and self.is_digit(self.peek()):
            value += "."
            self.advance()

            while self.is_digit(self.current()):
                value += self.current()
                self.advance()

            return Token("NUMBER", float(value), start)

        return Token("NUMBER", int(value), start)

    def scan_string(self):
        start = self.pos
        value = ""

        # Skip opening quote
        self.advance()

        while self.pos < len(self.text):
            ch = self.current()

            if ch == "'":
                # Two single quotes mean one literal quote.
                if self.peek() == "'":
                    value += "'"
                    self.advance()
                    self.advance()
                    continue

                # Closing quote
                self.advance()
                return Token("STRING", value, start)

            value += ch
            self.advance()

        raise LexicalError(f"Unterminated string at position {start}")

    def tokenize(self):
        while self.pos < len(self.text):
            ch = self.current()

            # Ignore whitespace
            if ch in " \t\r\n":
                self.advance()
                continue

            # Ignore // or -- comments until end of line.
            # Bonus Project 1 used //; Project 2 SQL uses --.
            if (ch == "/" and self.peek() == "/") or (ch == "-" and self.peek() == "-"):
                while self.pos < len(self.text) and self.current() != "\n":
                    self.advance()
                continue

            # Identifier
            if self.is_letter(ch):
                self.tokens.append(self.scan_identifier())
                continue

            # Number, including negative numbers such as -30
            if self.is_digit(ch) or (ch == "-" and self.is_digit(self.peek())):
                self.tokens.append(self.scan_number())
                continue

            # Quoted string
            if ch == "'":
                self.tokens.append(self.scan_string())
                continue

            start = self.pos

            # Maximal munch for two-character comparison operators.
            if (ch in "<>!" and self.peek() == "=") or (ch == "<" and self.peek() == ">"):
                self.tokens.append(Token("OP", ch + self.peek(), start))
                self.advance()
                self.advance()
                continue

            # One-character comparison operator
            if ch in "=<>":
                self.tokens.append(Token("OP", ch, start))
                self.advance()
                continue

            # Punctuation
            punctuation = {
                "[": "LBRACKET",
                "]": "RBRACKET",
                "(": "LPAREN",
                ")": "RPAREN",
                "{": "LBRACE",
                "}": "RBRACE",
                ",": "COMMA",
                ".": "DOT",
                ";": "SEMICOLON",
                "*": "STAR",
            }

            if ch in punctuation:
                self.tokens.append(Token(punctuation[ch], ch, start))
                self.advance()
                continue

            raise LexicalError(
                f"Unexpected character {ch!r} at position {self.pos}"
            )

        self.tokens.append(Token("EOF", None, self.pos))
        return self.tokens
