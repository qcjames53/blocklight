"""Blocklight - A blazing fast mcfunction microcompiler"""

from collections.abc import Iterator

# ------------------ #
# Compiler functions #
# ------------------ #

_FUNCTION_KEYWORDS = frozenset({"root", "load", "ticking"})

# Compile a single .bl source file and return list of filepaths and file contents
def compile_file(local_path: list[str], source: str) -> list[tuple[list[str], str]]:
    source_lines = split_lines(source)

    output: list[tuple[list[str], str]] = []
    for name, body, is_root, is_load, is_ticking in iter_functions(source_lines):
        output += compile_function(local_path + [name], body, is_root, is_load, is_ticking)
    return output


# Yield (name, body_lines, is_root, is_load, is_ticking) for each top-level function definition
def iter_functions(source_lines: list[str]) -> Iterator[tuple[str, list[str], bool, bool, bool]]:
    name: str | None = None
    is_root = is_load = is_ticking = False
    body: list[str] = []

    for line in source_lines:
        if line.strip() and not line[0].isspace():
            if name is not None:
                yield name, body, is_root, is_load, is_ticking

            text = line.strip()
            if not text.endswith(":"):
                raise SyntaxError(f"expected ':' ending function definition: {line!r}")
            tokens = text[:-1].split()
            try:
                kw_end = tokens.index("function")
            except ValueError:
                raise SyntaxError(f"missing 'function' keyword: {line!r}") from None
            if kw_end != len(tokens) - 2:
                raise SyntaxError(f"expected a single function name: {line!r}")
            keywords = set(tokens[:kw_end])
            unknown = keywords - _FUNCTION_KEYWORDS
            if unknown:
                raise SyntaxError(f"unknown function keyword(s) {sorted(unknown)}: {line!r}")

            name, body = tokens[-1], []
            is_root = "root" in keywords
            is_load = "load" in keywords
            is_ticking = "ticking" in keywords
        elif name is not None:
            body.append(line)
        # lines before the first header (blank or stray-indented) are dropped

    if name is not None:
        yield name, body, is_root, is_load, is_ticking


# Split lines, maintaining vanilla '\' behavior, stripping comments
def split_lines(source: str) -> list[str]:
    output: list[str] = []
    for line in source.split("\n"):
        lstrip_line = line.lstrip()

        if lstrip_line.startswith("#"):
            continue

        if output and output[-1].endswith("\\"):
            output[-1] = output[-1][:-1] + lstrip_line
        else:
            output.append(line)
    return output

# Compile a single function and return a list of filepaths and file contents
def compile_function(function_path: list[str], source_lines: list[str], is_root: bool = False, is_load: bool = False, is_ticking: bool = False) -> list[tuple[list[str], str]]:
    pass


# ------------- #
# I/O functions #
# ------------- #

def main():
    pass

if __name__ == "__main__":
    main()