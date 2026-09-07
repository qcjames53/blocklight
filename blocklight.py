"""Blocklight - A blazing fast mcfunction microcompiler"""

import string
from collections.abc import Iterator
from dataclasses import dataclass
from typing import NamedTuple


# ------------------ #
# Compiler functions #
# ------------------ #

_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")  # Characters permitted in a function name
_HEADER_KEYWORDS = frozenset(("root", "load", "tick"))  # Keywords permitted in function headers


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
    single_indent: str | None = None


# Accumulates compiled mcfunction file output (filepath -> contents) plus raised compile errors.
class CompiledOutput:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.errors: list[BLError] = []

    # Add a compiled mcfunction file
    def add_output_file(self, filepath: str, contents: str, source_path: str, function_def: Line) -> None:
        if filepath in self.files:
            err = BLSyntaxError(f"Another function already compiles to '{filepath}'.", function_def)
            err.filename = source_path
            self.errors.append(err)
            return
        self.files[filepath] = contents

    # Add a BLError error
    def add_error(self, error: BLError) -> None:
        self.errors.append(error)


# Compile a single .bl source file into the shared CompiledOutput.
def compile_file(compiled_output: CompiledOutput, local_path: str, contents: str) -> None:
    ctx = FileContext(local_path=local_path)
    source_lines = split_lines(contents)

    for start_index, end_index in functions_iterator(source_lines):
        function_def = source_lines[start_index]
        try:
            function_files = compile_function(ctx, source_lines, start_index, end_index)
        except BLFatalError as err:
            err.filename = local_path
            compiled_output.add_error(err)
            return  # Fatal errors are unrecoverable, abandon file
        except BLSyntaxError as err:
            err.filename = local_path
            compiled_output.add_error(err)
            continue
        for filepath, file_contents in function_files.items():
            compiled_output.add_output_file(filepath, file_contents, local_path, function_def)


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


# Yield line numbers for start (inclusive) and end (exclusive) of functions in the file
def functions_iterator(source_lines: list[Line]) -> Iterator[tuple[int, int]]:
    prev_function_start_index: int | None = None
    for index, line in enumerate(source_lines):
        if not line.text[:1].isspace():  # any un-indented line starts a function def, validation later
            if prev_function_start_index is not None:
                yield prev_function_start_index, index
            prev_function_start_index = index

    if prev_function_start_index is not None:
        yield prev_function_start_index, len(source_lines)


# Compile a single function
# Returns dict mapping filepath of mcfunction output file to string of file contents
def compile_function(ctx: FileContext, source_lines: list[Line], start: int, end: int) -> dict[str, str]:
    # Validate function header
    header = source_lines[start]
    header_split = header.text.split("function ")
    if len(header_split) <= 1:
        raise BLSyntaxError("This is being interpreted as a function header but does not declare a function. Double-check indentation.", header)
    if len(header_split) > 2:
        raise BLSyntaxError("This is an invalid function header.", header)

    # Validate header keywords
    seen_keywords: set[str] = set()
    for word in header_split[0].split():
        if word not in _HEADER_KEYWORDS:
            raise BLSyntaxError(f"This function definition declares an unknown keyword: '{word}'", header)
        if word in seen_keywords:
            raise BLSyntaxError(f"This function definition declares '{word}' twice.", header)
        seen_keywords.add(word)
    is_root = "root" in seen_keywords

    # Validate function name
    function_name = header_split[1]
    if not function_name.endswith(":"):
        raise BLSyntaxError("This function definition must end with ':'.", header)
    function_name = function_name[:-1].strip()
    if not function_name:
        raise BLSyntaxError("This function definition does not declare a function name (e.g. 'function foo:')", header)
    if sorted(set(function_name) - _FUNCTION_NAME_CHARS):
        raise BLSyntaxError("Function names may only use a-z, 0-9, '_' and '-'", header)

    # Determine function filepath
    function_filepath = f"{function_name}.mcfunction" if is_root else f"{ctx.local_path}/{function_name}.mcfunction"

    # Early return on empty functions
    if start + 1 >= end:
        return {}

    # If undefined, determine the file's indentation schema using body line 1 (guaranteed to be 1x indent).
    if ctx.single_indent is None:
        body_line = source_lines[start + 1]
        indent = body_line.text[: len(body_line.text) - len(body_line.text.lstrip())]
        if " " in indent and "\t" in indent:
            raise BLFatalError("This file's detected indentation schema mixes tabs and spaces, which is not permitted.", body_line)
        if indent == " ":
            raise BLFatalError("This file's indentation schema must be at least two spaces per indent.", body_line)
        ctx.single_indent = indent

    # Walk the function body, validating indentation.
    contents = ""
    for i in range(start + 1, end):
        line = strip_indent(ctx, source_lines, i, 1)
        # TODO add ALL block keyword detection stuff here
        contents += line + "\n"

    return {function_filepath: contents}


# Validate that the supplied line is correctly indented, return the left stripped string
def strip_indent(ctx: FileContext, source_lines: list[Line], line_number: int, indentation_depth: int) -> str:
    line = source_lines[line_number]
    expected = ctx.single_indent * indentation_depth
    if not line.text.startswith(expected):
        raise BLSyntaxError("This line is under-indented.", line)
    remainder = line.text[len(expected):]
    if remainder[:1].isspace():
        raise BLSyntaxError("This line is over-indented", line)
    return remainder


# ------------- #
# I/O functions #
# ------------- #

def main():
    pass

if __name__ == "__main__":
    main()
