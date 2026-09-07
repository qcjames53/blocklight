"""Blocklight - A blazing fast mcfunction microcompiler"""

import string
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple


# ------------------ #
# Compiler functions #
# ------------------ #

_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")  # Characters permitted in a function name
_FUNCTION_HEADER_KEYWORDS = frozenset(("root", "load", "tick"))
_MODIFIER_BLOCK_KEYWORDS = frozenset(("align", "anchored", "as", "at", "facing", "in", "on", "positioned", "rotated", "summon"))
_CONDITION_BLOCK_KEYWORDS = frozenset(("if", "elif", "else", "while"))
_STORE_BLOCK_KEYWORDS = frozenset(("store",))
_BLOCK_KEYWORDS = _MODIFIER_BLOCK_KEYWORDS | _CONDITION_BLOCK_KEYWORDS | _STORE_BLOCK_KEYWORDS


class Line(NamedTuple):
    text: str
    lineno: int


class BLError(SyntaxError):
    def __init__(self, msg: str, line: Line | None = None):
        super().__init__(msg)
        if line is not None:
            self.lineno = line.lineno
            self.text = line.text
class BLSyntaxError(BLError):  # Syntax error in function. Other functions in the file continue to compile.
    pass
class BLFatalError(BLError):  # Fatal error, stop compile of this file. Other files continue compiling.
    pass


@dataclass
class FileContext:
    local_path: str
    source_lines: list[Line]
    single_indent: str | None = None


# Accumulates compiled mcfunction file output (filepath -> contents) plus raised compile errors.
class CompiledOutput:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.errors: list[BLError] = []

    # Add a compiled mcfunction file.
    def add_output_file(self, filepath: str, contents: str, function_def_line: Line) -> None:
        if filepath in self.files:
            raise BLSyntaxError(f"Another function already compiles to '{filepath}'.", function_def_line)
        self.files[filepath] = contents

    # Add a BLError error
    def add_error(self, error: BLError) -> None:
        self.errors.append(error)


# Compile a single .bl source file into the shared CompiledOutput.
def compile_file(compiled_output: CompiledOutput, local_path: str, contents: str) -> None:
    try:
        ctx = FileContext(local_path=local_path, source_lines=split_lines(contents))
        detect_indent_schema(ctx)  # settle the file's indent unit before any span is walked
        for start_index, end_index in span_iterator(ctx, 0, len(ctx.source_lines), 0):
            try:
                compile_function(compiled_output, ctx, start_index, end_index)
            except BLSyntaxError as err:
                err.filename = local_path
                compiled_output.add_error(err)  # recoverable: other functions still compile
    except BLFatalError as err:
        err.filename = local_path
        compiled_output.add_error(err)  # unrecoverable: other files still compile


# Split lines, maintaining vanilla '\' behavior
# Returns cleaned list of Line(text, source line number)
def split_lines(source: str) -> list[Line]:
    output: list[Line] = []
    for line_number, line in enumerate(source.split("\n"), start=1):
        line = line.rstrip()
        lstrip_line = line.lstrip()

        # Strip comment and whitespace lines
        if lstrip_line.startswith("#") or len(lstrip_line) == 0:
            continue

        if output and output[-1].text.endswith("\\"):
            prev = output[-1]
            output[-1] = Line(prev.text[:-1] + lstrip_line, prev.lineno)
        else:
            output.append(Line(line, line_number))
    return output


# Compile a single function, writing its mcfunction output (and any helpers) into compiled_output.
def compile_function(compiled_output: CompiledOutput, ctx: FileContext, start: int, end: int) -> None:
    # Validate function header
    header = ctx.source_lines[start]
    header_split = header.text.split("function ")
    if len(header_split) <= 1:
        raise BLSyntaxError("This is being interpreted as a function header but does not declare a function. Double-check indentation.", header)
    if len(header_split) > 2:
        raise BLSyntaxError("This is an invalid function header.", header)

    # Validate header keywords
    seen_keywords: set[str] = set()
    for word in header_split[0].split():
        if word not in _FUNCTION_HEADER_KEYWORDS:
            raise BLSyntaxError(f"This function definition declares an unknown keyword: '{word}'", header)
        if word in seen_keywords:
            raise BLSyntaxError(f"This function definition declares '{word}' twice.", header)
        seen_keywords.add(word)

    # Validate function name
    function_name = header_split[1]
    if not function_name.endswith(":"):
        raise BLSyntaxError("This function definition must end with ':'.", header)
    function_name = function_name[:-1].strip()
    if not function_name:
        raise BLSyntaxError("This function definition does not declare a function name (e.g. 'function foo:')", header)
    if sorted(set(function_name) - _FUNCTION_NAME_CHARS):
        raise BLSyntaxError("Function names may only use a-z, 0-9, '_' and '-'", header)

    # Early return on empty functions
    if start + 1 >= end:
        return

    function_filepath = f"{function_name}.mcfunction" if "root" in seen_keywords else f"{ctx.local_path}/{function_name}.mcfunction"
    compile_block(compiled_output, ctx, start + 1, end, 1, function_filepath)


# Walk the body lines in [start, end) at `depth`, building output files from bottom to top.
def compile_block(compiled_output: CompiledOutput, ctx: FileContext, start: int, end: int, depth: int, output_filepath: str) -> None:
    output = []
    for span_start, span_end in span_iterator(ctx, start, end, depth):
        head = ctx.source_lines[start].text.strip()
        keyword = head.split(maxsplit=1)[0]  # all blocks begin with single-word keyword
        has_body = span_end > span_start + 1

        if keyword in _BLOCK_KEYWORDS:
            if not head.endswith(":"):
                raise BLSyntaxError(f"'{keyword}' begins a block and must end with ':'.", ctx.source_lines[span_start])
            if not has_body:
                raise BLSyntaxError(f"This '{keyword}' block has no body.", ctx.source_lines[span_start])
            # TODO create block handling here
            raise BLSyntaxError(f"The '{keyword}' block is not yet implemented.", ctx.source_lines[span_start])

        elif has_body:
            raise BLSyntaxError("Only block keywords may begin an indented block.", ctx.source_lines[span_start + 1])

        output.append(head)

    compiled_output.add_output_file(output_filepath, "\n".join(output), ctx.source_lines[start - 1])


# Yield (start, end) line-index spans (end exclusive) for each statement sitting at exactly `indentation_depth`
def span_iterator(ctx: FileContext, start_index: int, end_index: int, indentation_depth: int) -> Iterator[tuple[int, int]]:
    if start_index >= end_index:
        return

    expected_indent = "" if indentation_depth == 0 else ctx.single_indent * indentation_depth
    expected_indent_len = len(expected_indent)

    # The first line must sit exactly at the expected depth
    first_line = ctx.source_lines[start_index]
    if first_line.text[expected_indent_len:expected_indent_len+1].isspace():
        if indentation_depth == 0:
            raise BLFatalError("This file must begin with a function definition.", first_line)
        raise BLSyntaxError("This line is over-indented.", first_line)

    prev_span_start: int | None = None
    for index in range(start_index, end_index):
        line = ctx.source_lines[index]
        if not line.text.startswith(expected_indent):
            raise BLSyntaxError("This line is under-indented.", line)
        if not line.text[expected_indent_len:expected_indent_len+1].isspace():
            if prev_span_start is not None:
                yield prev_span_start, index
            prev_span_start = index

    if prev_span_start is not None:
        yield prev_span_start, end_index


# Set ctx.single_indent from the first indented line in the file. That line is always exactly one
# level deep, since any shallower parent would be encountered first.
def detect_indent_schema(ctx: FileContext) -> None:
    for line in ctx.source_lines:
        indent = line.text[: len(line.text) - len(line.text.lstrip())]
        if not indent:
            continue
        if " " in indent and "\t" in indent:
            raise BLFatalError("This file's detected indentation schema mixes tabs and spaces, which is not permitted.", line)
        if indent == " ":
            raise BLFatalError("This file's indentation schema must be at least two spaces per indent.", line)
        ctx.single_indent = indent
        return


# ------------- #
# I/O functions #
# ------------- #

def main():
    pass

if __name__ == "__main__":
    main()
