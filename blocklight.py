"""Blocklight - A blazing fast mcfunction microcompiler"""

import string
from collections.abc import Iterator
from dataclasses import dataclass


# ------------------ #
# Compiler functions #
# ------------------ #

_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")  # Characters permitted in a function name


# Dataclass holding per-bl-file info
@dataclass
class FileContext:
    local_path: str
    single_indent: str | None = None


# BL source error with exposed lineno.
class BLError(SyntaxError):
    def __init__(self, msg: str, lineno: int | None = None):
        super().__init__(msg)
        self.lineno = lineno
class BLSyntaxError(BLError):  # Syntax error in function. Other functions in the file continue to compile.
    pass
class BLFatalError(BLError):  # Fatal error, stop compile of this file. Other files continue compiling.
    pass


# Compile a single .bl source file and return list of filepaths and file contents
# Returns tuple of (list of (filepath, mcfunction contents string), list of syntax errors)
def compile_file(local_path: str, contents: str) -> tuple[list[tuple[str, str]], list[BLError]]:
    ctx = FileContext(local_path=local_path)
    source_lines = split_lines(contents)

    output: list[tuple[str, str]] = []
    errors: list[BLError] = []
    for start_index, end_index in functions_iterator(source_lines):
        try:
            output += compile_function(ctx, source_lines, start_index, end_index)
        except BLFatalError as err:  # Fatal error, stop compile of this file
            return [], [*errors, err]
        except BLSyntaxError as err:  # Syntax error in function, keep compiling other functions
            errors.append(err)
    return output, errors


# Split lines, maintaining vanilla '\' behavior
# Returns cleaned list of (line contents, line number in source)
def split_lines(source: str) -> list[tuple[str, int]]:
    output: list[tuple[str, int]] = []
    for line_number, line in enumerate(source.split("\n"), start=1):
        line = line.rstrip()
        lstrip_line = line.lstrip()

        # Strip comment and whitespace lines
        if lstrip_line.startswith("#") or len(lstrip_line) == 0:
            continue

        if output and output[-1][0].endswith("\\"):
            prev_text, prev_line_number = output[-1]
            output[-1] = (prev_text[:-1] + lstrip_line, prev_line_number)
        else:
            output.append((line, line_number))
    return output


# Yield line numbers for start (inclusive) and end (exclusive) of functions in the file
def functions_iterator(source_lines: list[tuple[str, int]]) -> Iterator[tuple[int, int]]:
    prev_function_start_index: int | None = None
    for index, (text, _line_number) in enumerate(source_lines):
        if not text[:1].isspace():  # any un-indented line starts a function def, validation later
            if prev_function_start_index is not None:
                yield prev_function_start_index, index
            prev_function_start_index = index

    if prev_function_start_index is not None:
        yield prev_function_start_index, len(source_lines)


# Compile a single function
def compile_function(ctx: FileContext, source_lines: list[tuple[str, int]], start: int, end: int) -> list[tuple[str, str]]:
    # Validate function header
    header_text, header_line = source_lines[start]
    header_split = header_text.split("function ")
    if len(header_split) <= 1:
        raise BLSyntaxError("This is being interpreted as a function header but does not declare a function. Double-check indentation.", header_line)
    if len(header_split) > 2:
        raise BLSyntaxError("This is an invalid function header.", header_line)
    is_root = is_load = is_tick = False
    if header_split[0] != "":
        keywords = header_split[0].strip().split(" ")
        for word in keywords:
            if word == "root":
                if is_root:
                    raise BLSyntaxError("This function definition declares 'root' twice.", header_line)
                is_root = True
            elif word == "tick":
                if is_tick:
                    raise BLSyntaxError("This function definition declares 'tick' twice.", header_line)
                is_tick = True
            elif word == "load":
                if is_load:
                    raise BLSyntaxError("This function definition declares 'load' twice.", header_line)
                is_load = True
            else:
                raise BLSyntaxError(f"This function definition declares an unknown keyword: '{word}'", header_line)
    function_name = header_split[1]
    if not function_name.endswith(":"):
        raise BLSyntaxError("This function definition must end with ':'.", header_line)
    function_name = function_name[:-1].strip()
    if not function_name:
        raise BLSyntaxError("This function definition does not declare a function name (e.g. 'function foo:')", header_line)
    if sorted(set(function_name) - _FUNCTION_NAME_CHARS):
        raise BLSyntaxError("Function names may only use a-z, 0-9, '_' and '-'", header_line)

    # Determine function filepath
    function_filepath = f"{function_name}.mcfunction" if is_root else f"{ctx.local_path}/{function_name}.mcfunction"

    # Early return on empty functions
    if start + 1 >= end:
        return []

    # If undefined, determine the file's indentation schema using body line 1 (guaranteed to be 1x indent).
    if ctx.single_indent is None:
        f, line = source_lines[start + 1]
        indent = f[: len(f) - len(f.lstrip())]
        if " " in indent and "\t" in indent:
            raise BLFatalError("This file's detected indentation schema mixes tabs and spaces, which is not permitted.", line)
        if indent == " ":
            raise BLFatalError("This file's indentation schema must be at least two spaces per indent.", line)
        ctx.single_indent = indent

    # Walk the function body, validating indentation.
    contents = ""
    for i in range(start + 1, end):
        line = strip_indent(ctx, source_lines, i, 1)
        # TODO add ALL block keyword detection stuff here
        contents += line + "\n"

    return [(function_filepath, contents)]


# Validate that the supplied line is correctly indented, return the left stripped string
def strip_indent(ctx: FileContext, source_lines: list[tuple[str, int]], line_number: int, indentation_depth: int) -> str:
    expected = ctx.single_indent * indentation_depth
    if not source_lines[line_number][0].startswith(expected):
        raise BLSyntaxError("This line is under-indented.", source_lines[line_number][1])
    remainder = source_lines[line_number][0][len(expected):]
    if remainder[:1].isspace():
        raise BLSyntaxError("This line is over-indented", source_lines[line_number][1])
    return remainder


# ------------- #
# I/O functions #
# ------------- #

def main():
    pass

if __name__ == "__main__":
    main()