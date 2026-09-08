"""Blocklight - A blazing fast mcfunction microcompiler"""

import string
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import InitVar, dataclass, field
from functools import cached_property
from typing import NamedTuple

# ------------------ #
# Compiler functions #
# ------------------ #

_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")
_MACRO_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_")
_FUNCTION_HEADER_KEYWORDS = frozenset(("root", "load", "tick"))
_MODIFIER_BLOCK_KEYWORDS = frozenset(
    ("align", "anchored", "as", "at", "facing", "in", "on", "positioned", "rotated", "summon")
)
_CONDITION_BLOCK_KEYWORDS = frozenset(("if", "elif", "else", "while"))
# Every keyword that begins an indented block. `python` runs at compile time; the rest still raise as not-implemented.
_BLOCK_KEYWORDS = _MODIFIER_BLOCK_KEYWORDS | _CONDITION_BLOCK_KEYWORDS | {"python"}


class _Line(NamedTuple):
    text: str
    lineno: int


class BLError(SyntaxError):
    def __init__(self, msg: str, line: _Line | None = None):
        super().__init__(msg)
        if line is not None:
            self.lineno = line.lineno
            self.text = line.text


class BLSyntaxError(BLError):  # Syntax error in function. Other functions in the file continue to compile.
    pass


class BLFatalError(BLError):  # Fatal error, stop compile of this file. Other files continue compiling.
    pass


class BLPythonError(BLSyntaxError):  # Raised while compiling a python: block; recoverable like BLSyntaxError.
    pass


# Source contents and metadata surrounding an input file.
@dataclass
class SourceFile:
    local_path: str
    source: InitVar[str]
    # Optional datapack metadata; surfaced to `python:` blocks as constants:
    pack_name: str | None = None
    pack_format: int | None = None
    namespace: str | None = None
    # Set at construction:
    source_lines: list[_Line] = field(init=False)

    def __post_init__(self, source: str) -> None:
        self.source_lines = self._split_lines(source)

    # Split lines, maintaining vanilla '\' behavior.
    # Returns cleaned list of _Line(text, source line number).
    @staticmethod
    def _split_lines(source: str) -> list[_Line]:
        output: list[_Line] = []
        for line_number, line in enumerate(source.split("\n"), start=1):
            line = line.rstrip()
            lstrip_line = line.lstrip()

            # Strip comment and whitespace lines
            if lstrip_line.startswith("#") or len(lstrip_line) == 0:
                continue

            if output and output[-1].text.endswith("\\"):
                prev = output[-1]
                output[-1] = _Line(prev.text[:-1] + lstrip_line, prev.lineno)
            else:
                output.append(_Line(line, line_number))
        return output

    # String of spaces/tabs representing 1x indent, or "  " if the file has no indented lines.
    # Computed on first read and cached.
    @cached_property
    def single_indent(self) -> str:
        for line in self.source_lines:
            indent = line.text[: len(line.text) - len(line.text.lstrip())]
            if not indent:
                continue
            if " " in indent and "\t" in indent:
                raise BLFatalError(
                    "This file's detected indentation schema mixes tabs and spaces, which is not permitted.", line
                )
            if indent == " ":
                raise BLFatalError("This file's indentation schema must be at least two spaces per indent.", line)
            return indent
        return "  "


# Accumulates compiled mcfunction file output (filepath -> contents) plus raised compile errors.
class CompiledOutput:
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.errors: list[BLError] = []
        self.load_functions: set[str] = set()
        self.tick_functions: set[str] = set()
        self.required_scoreboards: dict[str, dict[str, int]] = {"__bl_const": {}, "__bl_var": {}}

    # Add a compiled mcfunction file.
    def add_output_file(self, filepath: str, contents: str, function_def_line: _Line) -> None:
        if filepath in self.files:
            raise BLSyntaxError(f"Another function already compiles to '{filepath}'.", function_def_line)
        self.files[filepath] = contents

    def add_error(self, error: BLError) -> None:
        self.errors.append(error)

    def add_load_function(self, function_output_filepath: str):
        self.load_functions.add(function_output_filepath)

    def add_tick_function(self, function_output_filepath: str):
        self.tick_functions.add(function_output_filepath)

    def add_internal_constant(self, selector: str, value: int):
        self.required_scoreboards["__bl_const"][selector] = value

    def add_internal_var(self, selector: str, init_value: int):
        self.required_scoreboards["__bl_var"][selector] = init_value


# Read-only context threaded through the compilation of one function.
@dataclass
class _BlockInput:
    sf: SourceFile
    function_name: str


# Mutable accumulator built up while compiling a function body.
@dataclass
class _BlockOutput:
    lines: list[str] = field(default_factory=list)  # compiled mcfunction command lines
    macros: set[str] = field(default_factory=set)  # vanilla macros the block may use
    can_return: bool = False  # whether the block may early-return


# The `bl` object exposed inside python blocks
class _PythonBlockContext:
    def __init__(self, block_in: _BlockInput) -> None:
        sf = block_in.sf
        self.PATH = sf.local_path
        self.FILE = sf.local_path.rsplit("/", 1)[-1]
        self.NAMESPACE = sf.namespace
        self.PACK_NAME = sf.pack_name
        self.PACK_FORMAT = sf.pack_format
        self.FUNCTION = block_in.function_name
        self.BLOCKLIGHT_VERSION = _BL_VERSION


# Compile a single .bl source file into the shared CompiledOutput.
def compile_file(sf: SourceFile, compiled_output: CompiledOutput) -> None:
    try:
        for function_lines in _iter_spans(sf.source_lines, sf.single_indent, 0):
            try:
                _compile_function(compiled_output, sf, function_lines)
            except BLSyntaxError as err:
                err.filename = sf.local_path
                compiled_output.add_error(err)  # recoverable: other functions still compile
    except BLFatalError as err:
        err.filename = sf.local_path
        compiled_output.add_error(err)  # unrecoverable: other files still compile


# Yield lists of _Line objects for each command / block encountered at provided depth.
def _iter_spans(lines: list[_Line], single_indent: str, depth: int) -> Iterator[list[_Line]]:
    indent = "" if depth == 0 else single_indent * depth
    indent_len = len(indent)

    if lines and lines[0].text[indent_len : indent_len + 1].isspace():  # first line must sit exactly at this depth
        if depth == 0:
            raise BLFatalError("This file must begin with a function definition.", lines[0])
        raise BLSyntaxError("This line is over-indented.", lines[0])

    span_start: int | None = None
    for index, line in enumerate(lines):
        if not line.text.startswith(indent):
            raise BLSyntaxError("This line is under-indented.", line)
        if not line.text[indent_len : indent_len + 1].isspace():  # a line exactly at this depth starts a statement
            if span_start is not None:
                yield lines[span_start:index]
            span_start = index
    if span_start is not None:
        yield lines[span_start:]


# Validate a function header and compile its body to an mcfunction file.
def _compile_function(compiled_output: CompiledOutput, sf: SourceFile, lines: list[_Line]) -> None:
    header = lines[0]
    header_split = header.text.split("function ")
    if len(header_split) <= 1:
        raise BLSyntaxError(
            "This is being interpreted as a function header but does not declare a function. Double-check indentation.",
            header,
        )
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

    if len(lines) == 1:  # header only: empty function produces no output
        return

    if "root" in seen_keywords:
        output_filepath = f"{function_name}.mcfunction"
    else:
        output_filepath = f"{sf.local_path}/{function_name}.mcfunction"

    block_out = _BlockOutput()
    _compile_lines(_BlockInput(sf, function_name), block_out, lines[1:], 1)
    compiled_output.add_output_file(output_filepath, "\n".join(block_out.lines), header)

    if "load" in seen_keywords:
        compiled_output.add_load_function(output_filepath)
    if "tick" in seen_keywords:
        compiled_output.add_tick_function(output_filepath)


# Compile the statements in `lines` at `depth`, appending commands and recording block properties onto `block_out`.
def _compile_lines(block_in: _BlockInput, block_out: _BlockOutput, lines: list[_Line], depth: int) -> None:
    for span in _iter_spans(lines, block_in.sf.single_indent, depth):
        line = span[0]
        text = line.text.lstrip()  # right is already stripped
        keyword = text.split(maxsplit=1)[0].removesuffix(":")  # 'python:' / 'else:' carry the colon; others don't
        has_body = len(span) > 1

        # Handle block defs
        if keyword in _BLOCK_KEYWORDS:
            if not text.endswith(":"):
                raise BLSyntaxError(f"'{keyword}' begins a block and must end with ':'.", line)
            if not has_body:
                raise BLSyntaxError(f"This '{keyword}' block has no body.", line)
            if keyword == "python":
                if text != "python:":
                    raise BLSyntaxError("A 'python:' block header takes no arguments.", line)
                _compile_lines(block_in, block_out, _run_python_block(block_in, span, depth), depth)
            else:
                # TODO create block handling here
                raise BLSyntaxError(f"The '{keyword}' block is not yet implemented.", line)
        elif has_body:
            raise BLSyntaxError("Only block keywords may begin an indented block.", span[1])

        # Handle regular commands
        else:
            _append_command(block_out, line)


# Record one command line's macros and early-return potential, then add it to the block's output.
def _append_command(block_out: _BlockOutput, line: _Line) -> None:
    text = line.text.lstrip()  # right side already stripped

    if not block_out.can_return:  # cheap early-return detection; occasional false positives are acceptable
        loc = text.find("return")
        if loc != -1 and (loc == 0 or text[loc - 1] == " ") and (len(text) <= loc + 6 or text[loc + 6] == " "):
            block_out.can_return = True

    has_dollar = text.startswith("$")
    uses_macro = False
    if "$(" in text:
        for macro_name in _iter_macro_names(line):
            block_out.macros.add(macro_name)
            uses_macro = True
    if not uses_macro and has_dollar:
        raise BLSyntaxError("This line begins with '$' but declares no macro.", line)
    block_out.lines.append("$" + text if uses_macro and not has_dollar else text)


# Yield the name inside each vanilla macro '$(name)' in line, left to right.
def _iter_macro_names(line: _Line) -> Iterator[str]:
    search_from = 0
    while (name_start := line.text.find("$(", search_from)) != -1:
        name_end = line.text.find(")", name_start + 2)
        if name_end == -1:
            raise BLSyntaxError("This line opens a macro with '$(' but never closes it with ')'.", line)
        name = line.text[name_start + 2 : name_end]
        if not name:
            raise BLSyntaxError("This line declares an empty macro '$()'.", line)
        if set(name) - _MACRO_NAME_CHARS:
            raise BLSyntaxError(f"Macro names may only use a-z, A-Z, 0-9 and '_': '$({name})'", line)
        yield name
        search_from = name_end + 1


# Execute a python: block and return the lines it emits re-indented to `depth` and anchored at the block header.
def _run_python_block(block_in: _BlockInput, span: list[_Line], depth: int) -> list[_Line]:
    sf = block_in.sf
    head = span[0]
    body = textwrap.dedent("\n".join(ln.text for ln in span[1:]))

    emitted: list[str] = []
    scope = {"emit": lambda command: emitted.append(str(command)), "bl": _PythonBlockContext(block_in)}
    try:
        exec(compile(body, f"{sf.local_path}:{head.lineno} python: block", "exec"), scope)
    except SyntaxError as err:
        raise BLPythonError(f"invalid Python in this block: {err.msg}", head) from err
    except Exception as err:
        raise BLPythonError(f"this block raised {type(err).__name__}: {err}", head) from err

    prefix = (sf.single_indent or "") * depth
    return [
        _Line(prefix + part, head.lineno) for command in emitted for part in str(command).split("\n") if part.strip()
    ]


# ------------- #
# I/O functions #
# ------------- #

_BL_VERSION = "1.0.dev"
_MIN_PYTHON = (3, 10)  # Python 3.10 EOL October 2026


def main():
    if sys.version_info < _MIN_PYTHON:
        required = ".".join(str(part) for part in _MIN_PYTHON)
        raise SystemExit(f"Blocklight {_BL_VERSION} requires Python {required} or newer.")


if __name__ == "__main__":
    main()
