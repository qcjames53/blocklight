#!/usr/bin/env python3

# ----- Blocklight ----- #
# A blazing fast mcfunction microcompiler
# © 2026 by Quinn James. Licensed under the GNU GPL v3.
# See https://github.com/qcjames53/blocklight for documentation and license info.


# ----- Quick start ----- #
# 1) Install Python on your system (3.10+).
# 2) Copy this script to your datapack's top level directory (e.g. `my_pack/blocklight.py`).
# 3) Create your .bl source files in `<pack>/data/<namespace>/blocklight/`. See the GitHub link above for examples.
# 4) Run the compiler in the terminal from your datapack's top level directory with `python3 blocklight.py`.


# ----- Contributor guidelines ----- #
# When developing changes, please keep these tenets in mind:
#
# 1) Mcfunction is not a normal language, so a normal compiler is the wrong tool; blocklight syntax must allow for messy
#    mcfunction cleverness without binding datapack authors to a structured "happy path".
# 2) The compiler must remain portable, distributable, free, and broadly compatible with future Minecraft updates.
# 3) Compile operations must remain accurate, idempotent, resource efficient, and output must co-exist peacefully with
#    files the user has hand-created.
# 4) Failures are recoverable on re-compile, clear to understand, and isolated to a single function where possible.
# 5) The language model must maintain broadly independent source files.
# 6) Custom compiler-only behavior should take the form of a one line command or block header with a leading reserved
#    keyword. Indentation indicates block contents.
# 7) Avoid parsing vanilla command syntax wherever possible. Pass it through. Minecraft updates can easily break things.
# 8) Don't delete or modify any file unless Blocklight created it. Exceptions (e.g. load/tick tags) must be very robust.
# 9) Vanilla function macros and vanilla return commands are to be supported everywhere, no exceptions.
#
# Thank you very much for reading all of this! Contributions and issues are more than welcome on GitHub. I look forward
# to seeing what you create! - Quinn

import argparse
import enum
import functools
import json
import os
import stat
import string
import sys
import textwrap
import time
from _blake2 import blake2b
from collections.abc import Callable, Iterable, Iterator
from typing import IO, ClassVar, NamedTuple, cast

# ----- Tweakable constants ----- #
_BL_VERSION = (1, 1)
_BL_IS_DEV_BUILD = False
_MIN_PYTHON = (3, 10)  # Python 3.10 EOL October 2026

# ----- Compiler internal constants ----- #
_BL_VERSION_STRING = f"{_BL_VERSION[0]}.{_BL_VERSION[1]}" + (".dev" if _BL_IS_DEV_BUILD else "")
_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003  # Windows junction; stat only defines it on Windows
_ANSI_RED = "\033[31m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_BLUE = "\033[34m"
_ANSI_WHITE = "\033[37m"
_ANSI_GREY = "\033[90m"
_ANSI_RESET = "\033[0m"


class _KeywordType(enum.Enum):
    MODIFIER = enum.auto()  # execute-modifier: recurses into a new child .mcfunction
    CONDITIONAL = enum.auto()  # if / elif / else / while - reserved, not yet implemented
    INLINE_PYTHON = enum.auto()  # python: expands inline, same depth/block_out


class _KeywordSpec(NamedTuple):
    type: _KeywordType
    args_required: bool


# One line in bl source tracking original line number
class _Line(NamedTuple):
    text: str
    lineno: int

    # Parse line as block header (<keyword> <args>)
    # Return first word of line text as keyword, remainder as args
    def as_keyword_args(self) -> tuple[str, str]:
        keyword, _, args = self.text.lstrip().partition(" ")
        return keyword, args

    # Parse line as function header (<modifiers> function <name>)
    # Returns function name, is_root, is_load, is_tick
    def as_function_header(self) -> tuple[str, bool, bool, bool]:
        modifiers_part, _, name_part = self.text.partition("function ")
        modifiers = frozenset(modifiers_part.split())
        return name_part.strip(), "root" in modifiers, "load" in modifiers, "tick" in modifiers


# One bl source file's properties stored in the manifest
class _ManifestSourceEntry(NamedTuple):
    source_hash: str
    outputs: frozenset[str]


# Manifest file tracking facets of the previous compile
class _Manifest(NamedTuple):
    sources: dict[str, _ManifestSourceEntry]
    load: frozenset[str]
    tick: frozenset[str]
    version: tuple[int, int]


class BLError(SyntaxError):
    def __init__(self, msg: str, line: _Line | None = None):
        super().__init__(msg)
        if line is not None:
            self.lineno = line.lineno
            self.text = line.text


class BLNonFatalError(BLError):  # Nonfatal error, keep compile going in next function.
    pass


class BLFatalError(BLError):  # Fatal error, stop compiling this source file.
    pass


class BLFileError(BLNonFatalError):  # Raised on failures during file operations.
    pass


class BLSyntaxError(BLNonFatalError):  # Syntax error in bl function.
    pass


class BLPythonError(BLNonFatalError):  # Raised while compiling a python: block.
    pass


# Bare conditional statement in `execute if` subcommand (e.g. "score @s v matches 1")
class _ConditionalStatement(NamedTuple):
    text: str
    negated: bool = False  # compiles to `unless` instead of `if`


# Condition operator node ("and", "or" or "not").
class _ConditionalOperator(NamedTuple):
    op: str
    terms: tuple["_ConditionalStatement | _ConditionalOperator", ...]


_ConditionalNode = _ConditionalStatement | _ConditionalOperator


# Whether `path` (relative to `root`) or any folder between it and `root` is a symlink (or junction). Cached so a
# folder shared by many paths is checked once; Pack.compile() clears the cache so each run sees the disk afresh.
@functools.cache
def _contains_symlink(path: str, root: str) -> bool:
    path = os.path.normpath(path)
    try:
        st = os.lstat(os.path.join(root, path))
        if stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT:
            return True
    except OSError:
        pass  # missing: nothing here to follow
    parent = os.path.dirname(path)
    return bool(parent) and parent != path and _contains_symlink(parent, root)


# Whether `filepath` normalizes to a path inside data/<namespace>/function. Rejects malformed namespaces.
def _in_function_dir(filepath: str, namespace: str) -> bool:
    if namespace in ("", ".", "..") or "/" in namespace or os.sep in namespace:
        return False
    expected_root = os.path.normpath(f"data/{namespace}/function")
    normalized = os.path.normpath(filepath)
    return normalized == expected_root or normalized.startswith(expected_root + os.sep)


# Clean lines from any (line number, raw text) source
# Drops trailing whitespace, blank lines, collapses newlines, strips leading macro symbols, and removes comments.
def _iter_clean_lines(numbered_lines: Iterable[tuple[int, str]]) -> Iterator[_Line]:
    pending: _Line | None = None
    for line_number, raw_line in numbered_lines:
        line = raw_line.rstrip()
        lstrip_line = line.lstrip()

        # Strip comment and whitespace lines
        if lstrip_line.startswith("#") or len(lstrip_line) == 0:
            if pending is not None and pending.text.endswith("\\"):
                pending = _Line(pending.text[:-1], pending.lineno)
            continue
        if lstrip_line.startswith("$") and not lstrip_line.startswith("$("):
            line = line[: len(line) - len(lstrip_line)] + lstrip_line[1:]
            lstrip_line = lstrip_line[1:]

        if pending is not None and pending.text.endswith("\\"):
            pending = _Line(pending.text[:-1] + lstrip_line, pending.lineno)
        else:
            if pending is not None:
                yield pending
            pending = _Line(line, line_number)
    if pending is not None:
        if pending.text.endswith("\\"):
            pending = _Line(pending.text[:-1], pending.lineno)
        yield pending


# A bl source file's contents + metadata.
class SourceFile(NamedTuple):
    local_path: str
    namespace: str
    source_lines: list[_Line]

    # Source file from its raw `text`: comments and blank lines dropped, '\' continuations joined.
    @classmethod
    def parse(cls, local_path: str, namespace: str, text: str) -> "SourceFile":
        return cls(local_path, namespace, list(_iter_clean_lines(enumerate(text.split("\n"), start=1))))

    # Hash of bl source file's cleaned contents
    @property
    def content_hash(self) -> str:
        hasher = blake2b()
        for line in self.source_lines:
            hasher.update(line.text.encode("utf-8"))
            hasher.update(b"\n")
        return hasher.hexdigest()


# Compile-time options parsed from the command line.
class CompilerOptions(NamedTuple):
    no_python: bool = False  # Throw an error on `python:` blocks instead of executing them
    no_symlink: bool = False  # Refuse to follow symlinked directories or read symlinked bl source files
    dry_run: bool = False  # Compile in-memory only; do not write any files to disk
    force: bool = False  # Recompile every bl source regardless of the cached hash


# Information about the datapack + compile options used at compile time.
class _PackInfo(NamedTuple):
    name: str  # the datapack's folder name
    format: int | None  # from pack.mcmeta; None if it declares none
    options: CompilerOptions


# Read-only context threaded through the compilation of one block
class _BlockInput(NamedTuple):
    source_function_name: str  # Name of the top-level function from the function def
    function_name: str  # Name of the output function this block will compile into
    depth: int  # Indentation depth of the block's lines; 1 for a function's own body
    source_function_id: str = ""  # Namespaced name of the top-level function; empty outside any function


# Mutable accumulator built up while compiling one block.
class _BlockOutput:
    def __init__(self) -> None:
        self.lines: list[str] = []  # compiled mcfunction command lines
        self.macros: set[str] = set()  # vanilla macros the block may use
        self.can_return = False  # whether the block may early-return


# if/elif condition compiled to execute subcommands
class _CompiledCondition(NamedTuple):
    setup_lines: list[_Line]  # run immediately before testing `subcommands`
    subcommands: str  # e.g. "if score @s v matches 1 unless function pack:f_helper/cond_0"
    macros: set[str]  # macros referenced by `setup_lines` and `subcommands`


# Read-only context threaded through the compilation of one if/elif/while condition
class _ConditionInput(NamedTuple):
    block_in: _BlockInput
    line: _Line
    or_functions: dict[_ConditionalOperator, str]  # helper function written per distinct 'or' node


# One compiled mcfunction output file's contents + linedef.
class _MCFOutputContents(NamedTuple):
    contents: str
    line: _Line


# The output of compiling one bl source file
class CompiledSource:
    def __init__(self) -> None:
        self.mcf_outputs: dict[str, _MCFOutputContents] = {}
        self.load: set[str] = set()  # output paths of load functions
        self.tick: set[str] = set()  # output paths of tick functions
        self.errors: list[BLError] = []
        self.ran_python = False  # a python block ran, and may emit something different next run
        self.python_scope: dict[str, object] = {}  # globals shared by every python block in this source file


# What writing one output did, or would do in a dry run
class _WriteOutcome(enum.Enum):
    NEW = enum.auto()
    MODIFIED = enum.auto()
    UNCHANGED = enum.auto()


# Outcome of one build: its errors in order, the functions registered for the load and tick tags, and the counts
# the terminal summary prints.
class BuildResult:
    def __init__(self) -> None:
        self.pack_name = ""
        self.errors: list[BLError] = []
        self.load_functions: set[str] = set()  # output paths
        self.tick_functions: set[str] = set()  # output paths
        self.sources_read = 0
        self.sources_skipped = 0
        self.outputs_new = 0
        self.outputs_modified = 0
        self.outputs_unchanged = 0
        self.outputs_reused = 0  # kept as-is from sources that were not recompiled
        self.outputs_deleted = 0  # stale outputs and the setup function, once no sources are left


# Emitter helpers exposed to python blocks.
class _PythonEmitter:
    def __init__(self, indent: str, depth: int) -> None:
        self.lines: list[str] = []
        self._indent = indent
        self._depth = depth

    # Emits a command at the correct indentation
    def cmd(self, command: object) -> None:
        prefix = self._indent * self._depth
        self.lines.extend(prefix + part for part in str(command).split("\n"))

    # Emits a block header at the correct indentation and indents child contents
    def blk(self, header: object) -> "_PythonEmitter":
        self.cmd(header)
        return self

    def __enter__(self) -> None:
        self._depth += 1

    def __exit__(self, *_exc_info: object) -> None:
        self._depth -= 1


# ----- Terminal ----- #
# Print the compile results. All errors + a status line.
def report(result: BuildResult, elapsed: float) -> None:
    for error in result.errors:
        # Errors get stderr + red
        sys.stderr.write(_color(f"{type(error).__name__}: {error}", _ANSI_RED, sys.stderr) + "\n")
    sys.stderr.flush()

    line = _color(result.pack_name, _ANSI_WHITE, sys.stdout) + _color(": ", _ANSI_GREY, sys.stdout)
    total = result.outputs_new + result.outputs_modified + result.outputs_unchanged + result.outputs_reused
    functions = f"{total} function{'' if total == 1 else 's'}"
    if result.errors:
        line += _color(f"compiled {functions} with errors", _ANSI_RED, sys.stdout)
    else:
        line += _color(f"compiled {functions}", _ANSI_GREEN, sys.stdout)
    changes: list[str] = []
    if result.outputs_new > 0:
        changes.append(_color(f"{result.outputs_new} new", _ANSI_BLUE, sys.stdout))
    if result.outputs_modified > 0:
        changes.append(_color(f"{result.outputs_modified} modified", _ANSI_YELLOW, sys.stdout))
    if result.outputs_deleted > 0:
        changes.append(_color(f"{result.outputs_deleted} deleted", _ANSI_RED, sys.stdout))
    if len(changes) == 0:
        changes = [_color("no changes", _ANSI_GREY, sys.stdout)]
    line += _color(f" ({', '.join(changes)})", _ANSI_GREY, sys.stdout)
    line += _color(f" {round(elapsed * 1000)}ms", _ANSI_YELLOW, sys.stdout)
    print(line)


# Wraps text in an ANSI color code, only when the stream is a terminal and NO_COLOR is unset.
def _color(text: str, code: str, stream: IO[str]) -> str:
    if os.environ.get("NO_COLOR") or not stream.isatty():
        return text
    return f"{code}{text}{_ANSI_RESET}"


# Handles pack reads + writes, orchestrating compiles, and organizing pack metadata + diffs.
class Pack:
    _MANIFEST_FILENAME = ".blocklight-manifest.json"
    _FUNCTION_TAG_DIR = "data/minecraft/tags/function"
    _SETUP_FUNCTION_FILEPATH = "data/_bl/function/load.mcfunction"

    def __init__(self, options: CompilerOptions) -> None:
        self._options = options
        self._info = _PackInfo("", None, options)  # filled in from pack.mcmeta
        self._result = BuildResult()
        self._previous_manifest: _Manifest | None = None
        self._manifest_file: IO[str] | None = None  # open from _read_manifest until _write_manifest
        self._files: set[str] = set()  # outputs on disk this run: written, unchanged or reused
        self._source_hashes: dict[str, str] = {}
        self._source_outputs: dict[str, dict[str, _Line | None]] = {}  # source -> output -> defining line
        self._failed_writes: set[str] = set()  # produced outputs that could not be written
        self._deleted: set[str] = set()  # files deleted this run, or that a dry run would delete
        self._needs_recompile: set[str] = set()
        self._pack_root_dir = os.getcwd()  # pack root: symlink checks stop here

    # Compile the datapack at the current directory.
    def compile(self) -> BuildResult:
        _contains_symlink.cache_clear()  # links may have changed since an earlier compile in this process
        self._read_pack_meta()
        if self._options.no_symlink and _contains_symlink("data", self._pack_root_dir):
            self._log_error(BLFileError("Refusing to read 'data': the path contains a symlink."))
            return self._result
        if not os.path.isdir("data"):
            return self._result

        try:
            self._previous_manifest = self._read_manifest()
        except BLFileError as err:
            if self._manifest_file is not None:
                self._manifest_file.close()
            self._log_error(BLFileError(f"{err} Compile aborted."))
            return self._result

        sources = self._discover_sources()
        for local_path, namespace in sources.items():
            try:
                self._compile_source(local_path, namespace)
            except Exception as err:  # a bug or unanticipated failure must not vanish silently
                self._report_error(local_path, BLFileError(f"Unexpected error while compiling: {err}."))

        producers = self._output_producers()
        self._report_collisions(producers)
        self._delete_stale_outputs(producers)
        if sources:
            self._write_setup_function(producers)
        else:  # no sources left
            self._delete_setup_function()
        self._result.outputs_deleted = len(self._deleted)
        if not self._options.dry_run:
            self._prune_empty_dirs()
            self._write_function_tags()
            self._write_manifest()
        return self._result

    # Read pack.mcmeta's format and take the pack's name from its folder.
    def _read_pack_meta(self) -> None:
        if self._options.no_symlink and _contains_symlink("pack.mcmeta", self._pack_root_dir):
            raise SystemExit("Refusing to read 'pack.mcmeta': the path contains a symlink.")
        if not os.path.isfile("pack.mcmeta"):
            raise SystemExit("No 'pack.mcmeta' found in the current directory.")
        with self._open_symlink_safe("pack.mcmeta") as f:
            try:
                pack_meta: dict[str, object] = json.load(f)
            except json.JSONDecodeError as err:
                raise SystemExit(f"Malformed JSON in 'pack.mcmeta': {err}.") from err

        name = os.path.basename(os.getcwd())
        self._info = _PackInfo(name, self._read_pack_format(pack_meta), self._options)
        self._result.pack_name = name

    # Each .bl file under data/<namespace>/blocklight/ -> its namespace. Invalid names are logged and skipped.
    def _discover_sources(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        for namespace in sorted(os.listdir("data")):
            namespace_dir = os.path.join("data", namespace)
            if self._options.no_symlink and _contains_symlink(namespace_dir, self._pack_root_dir):
                self._log_error(
                    BLFileError(f"Refusing to read namespace '{namespace_dir}': the path contains a symlink.")
                )
                continue
            if not os.path.isdir(namespace_dir):
                continue
            blocklight_dir = os.path.join(namespace_dir, "blocklight")
            for local_path in self._iter_bl_files(blocklight_dir):
                # Folder and file names become part of the function id
                names = local_path.removesuffix(".bl").split("/")[3:]
                if any(not name or set(name) - _FUNCTION_NAME_CHARS for name in names):
                    self._log_error(
                        BLSyntaxError(
                            f"The source path '{local_path}' may only use a-z, 0-9, '_' and '-' in folder and "
                            "file names."
                        )
                    )
                    continue
                sources[local_path] = namespace
        return sources

    # Compile one bl source file and write outputs to disk if appropriate (respecting I/O file caching)
    def _compile_source(self, local_path: str, namespace: str) -> None:
        try:
            text = self._read_text(local_path, "read")
        except BLFileError as err:
            self._report_error(local_path, err)
            return
        if text is None:  # deleted since discovery
            return
        source = SourceFile.parse(local_path, namespace, text)
        content_hash = source.content_hash
        self._result.sources_read += 1
        self._source_hashes[local_path] = content_hash
        self._source_outputs[local_path] = {}
        if self._reuse_outputs(local_path, content_hash):
            self._result.sources_skipped += 1
            return

        compiled = Compile(source, self._info).compile()
        for error in compiled.errors:
            self._report_error(local_path, error)
        if compiled.ran_python:
            self._needs_recompile.add(local_path)
        for filepath, output in compiled.mcf_outputs.items():
            self._source_outputs[local_path][filepath] = output.line
            try:
                outcome = self._write_output(filepath, output.contents)
            except BLFileError as err:
                err.lineno, err.text = output.line.lineno, output.line.text
                self._failed_writes.add(filepath)
                self._report_error(local_path, err)
                continue
            self._files.add(filepath)
            self._count_write(outcome)
        self._result.load_functions |= compiled.load
        self._result.tick_functions |= compiled.tick

    # Re-register `local_path`'s previous outputs without recompiling, if they are still current. Returns whether
    # they were.
    def _reuse_outputs(self, local_path: str, content_hash: str) -> bool:
        previous = self._previous_manifest
        entry = previous.sources.get(local_path) if previous else None
        if (
            self._options.force
            or previous is None
            or entry is None
            or previous.version != _BL_VERSION
            or entry.source_hash != content_hash
            or not all(os.path.isfile(output) for output in entry.outputs)
        ):
            return False
        self._result.outputs_reused += len(entry.outputs)
        for output in entry.outputs:
            self._files.add(output)
            self._source_outputs[local_path][output] = None
            function_id = self._function_id(output)
            if function_id in previous.load:
                self._result.load_functions.add(output)
            if function_id in previous.tick:
                self._result.tick_functions.add(output)
        return True

    def _count_write(self, outcome: _WriteOutcome) -> None:
        match outcome:
            case _WriteOutcome.NEW:
                self._result.outputs_new += 1
            case _WriteOutcome.MODIFIED:
                self._result.outputs_modified += 1
            case _WriteOutcome.UNCHANGED:
                self._result.outputs_unchanged += 1

    def _log_error(self, error: BLError) -> None:
        self._result.errors.append(error)

    # Log an error and force a recompile of `local_path` next run.
    def _report_error(self, local_path: str, error: BLError) -> None:
        error.filename = local_path
        self._log_error(error)
        self._needs_recompile.add(local_path)

    # Safely write `contents` to `path`. Returns what the write did (or would do, in a dry run).
    def _write_output(self, path: str, contents: str) -> _WriteOutcome:
        existing = self._read_text(path, "write")
        if existing == contents:
            return _WriteOutcome.UNCHANGED
        # Empty counts as ours: there is nothing in it to lose, and an interrupted write can leave one
        if existing and Compile.HEADER_MARKER not in existing:
            raise BLFileError(f"Refusing to overwrite '{path}': missing the Blocklight header.")
        if not self._options.dry_run:
            self._write_text(path, contents, "write")
        return _WriteOutcome.NEW if existing is None else _WriteOutcome.MODIFIED

    # Normalized path of each output produced this run -> (source, defining line or None if reused) per producer.
    def _output_producers(self) -> dict[str, list[tuple[str, _Line | None]]]:
        producers: dict[str, list[tuple[str, _Line | None]]] = {}
        for local_path, outputs in self._source_outputs.items():
            for output, line in outputs.items():
                producers.setdefault(os.path.normpath(output), []).append((local_path, line))
        return producers

    # Report outputs produced by more than one source. Writes don't catch these, since the second source sees
    # the first's file as an earlier Blocklight output and replaces it.
    def _report_collisions(self, producers: dict[str, list[tuple[str, _Line | None]]]) -> None:
        for path, sources in sorted(producers.items()):
            if len(sources) < 2:
                continue
            for local_path, line in sources:
                others = ", ".join(sorted(f"'{other}'" for other, _line in sources if other != local_path))
                self._report_error(local_path, BLFileError(f"The output '{path}' is also compiled by {others}.", line))

    # Delete the previous run's outputs that nothing produced this run. A dry run checks and counts them only.
    def _delete_stale_outputs(self, producers: dict[str, list[tuple[str, _Line | None]]]) -> None:
        if self._previous_manifest is None:
            return
        for local_path, entry in sorted(self._previous_manifest.sources.items()):
            for output in sorted(entry.outputs):
                if os.path.normpath(output) not in producers:
                    self._delete_stale_output(output, local_path)

    # Delete one stale output file. Paths come from the manifest, so they are untrusted: only deletes
    # a .mcfunction inside data/<namespace>/function of the source's namespace, carrying the Blocklight header.
    def _delete_stale_output(self, filepath: str, local_path: str) -> None:
        filepath = os.path.normpath(filepath)
        parts = os.path.normpath(local_path).split(os.sep)
        namespace = parts[1] if len(parts) > 3 and parts[0] == "data" and parts[2] == "blocklight" else ""
        if not filepath.endswith(".mcfunction") or not _in_function_dir(filepath, namespace):
            error = BLFileError(f"Refusing to delete '{filepath}': not an output file of '{local_path}'.")
            self._report_error(local_path, error)
            return
        if self._options.no_symlink and _contains_symlink(filepath, self._pack_root_dir):
            error = BLFileError(f"Refusing to delete stale file '{filepath}': the path contains a symlink.")
            self._report_error(local_path, error)
            return
        if not os.path.isfile(filepath):
            return
        try:
            with self._open_symlink_safe(filepath) as f:
                content = f.read()
        except OSError as err:
            error = BLFileError(f"Failed to verify stale file '{filepath}': {err.strerror or err}.")
            self._report_error(local_path, error)
            return
        if Compile.HEADER_MARKER not in content:
            error = BLFileError(f"Refusing to delete '{filepath}': missing the Blocklight header.")
            self._report_error(local_path, error)
            return

        # Delete file
        try:
            if not self._options.dry_run:
                os.remove(filepath)
        except OSError as err:
            error = BLFileError(f"Failed to delete stale file '{filepath}': {err.strerror or err}.")
            self._report_error(local_path, error)
            return
        self._deleted.add(filepath)

    # Remove folders left empty by deleted files, up to but not including data/.
    def _prune_empty_dirs(self) -> None:
        for directory in sorted({os.path.dirname(path) for path in self._deleted}, key=len, reverse=True):
            while directory and os.path.normpath(directory) != "data":
                try:
                    os.rmdir(directory)  # fails unless empty
                except OSError:
                    break
                directory = os.path.dirname(directory)

    # Write the load function creating the reserved scoreboard objective and register it.
    def _write_setup_function(self, producers: dict[str, list[tuple[str, _Line | None]]]) -> None:
        path = self._SETUP_FUNCTION_FILEPATH
        if sources := producers.get(os.path.normpath(path)):
            for local_path, line in sources:
                self._report_error(local_path, BLFileError(f"The path '{path}' is reserved for Blocklight.", line))
            return
        try:
            outcome = self._write_output(path, Compile.setup_function_contents())
        except BLFileError as err:
            self._log_error(err)
            return
        self._count_write(outcome)
        self._files.add(path)
        self._result.load_functions.add(path)

    # Delete the setup function, unless it lacks the Blocklight header. A dry run only counts it.
    def _delete_setup_function(self) -> None:
        path = self._SETUP_FUNCTION_FILEPATH
        try:
            existing = self._read_text(path, "delete")
            if existing is not None and Compile.HEADER_MARKER in existing:
                if not self._options.dry_run:
                    os.remove(path)
                self._deleted.add(path)
        except BLFileError as err:
            self._log_error(err)
        except OSError as err:
            self._log_error(BLFileError(f"Failed to delete '{path}': {err.strerror or err}."))

    # Update the load and tick function tags.
    def _write_function_tags(self) -> None:
        previous = self._previous_manifest
        for tag, outputs, previous_ids in (
            ("load", self._result.load_functions, previous.load if previous else frozenset[str]()),
            ("tick", self._result.tick_functions, previous.tick if previous else frozenset[str]()),
        ):
            path = f"{self._FUNCTION_TAG_DIR}/{tag}.json"
            ids = self._tag_function_ids(outputs)
            try:
                self._update_function_tag(path, ids, previous_ids)
            except BLFileError as err:
                # The manifest records only this run's ids, so the next run won't remove entries dropped this run.
                # Current ids are re-added by the next run once the tag is fixed.
                if dropped := sorted(previous_ids.difference(ids)):
                    entries = ", ".join(f"'{function_id}'" for function_id in dropped)
                    err = BLFileError(
                        f"{err} Orphaned entries {entries} remain in '{path}'. Please manually clean up this file."
                    )
                self._log_error(err)

    # Rewrite the function tag at `path`: drop entries for `previous_ids` and `ids`, then append `ids`, keeping
    # everything else. Creates the file only if there is an id to add.
    def _update_function_tag(self, path: str, ids: list[str], previous_ids: frozenset[str]) -> None:
        text = self._read_text(path, "update function tag", writable=True)
        if text is None and not ids:
            return
        raw: object = {} if text is None else self._parse_json(path, text)
        if not isinstance(raw, dict):
            raise BLFileError(f"Malformed function tag '{path}': must be a JSON object.")
        tag_json = cast(dict[str, object], raw)
        values = tag_json.get("values", [])
        if not isinstance(values, list):
            raise BLFileError(f"Malformed function tag '{path}': 'values' must be a list.")

        owned = previous_ids.union(ids)
        new_values = [entry for entry in cast(list[object], values) if self._tag_entry_id(entry) not in owned] + ids
        if "values" not in tag_json or new_values != values:
            tag_json["values"] = new_values
            self._write_text(path, json.dumps(tag_json, indent=2), "update function tag")

    # Sorted ids of `outputs` that were written, the setup function first so other load functions can use
    # the reserved objective. A tag naming a missing function fails to load.
    def _tag_function_ids(self, outputs: set[str]) -> list[str]:
        setup_id = self._function_id(self._SETUP_FUNCTION_FILEPATH)
        ids = (self._function_id(output) for output in outputs & self._files)
        return sorted(ids, key=lambda function_id: (function_id != setup_id, function_id))

    # Id of a function tag entry: a bare string or an {"id": ...} object. None if neither.
    @staticmethod
    def _tag_entry_id(entry: object) -> str | None:
        if isinstance(entry, dict):
            entry = cast(dict[str, object], entry).get("id")
        return entry if isinstance(entry, str) else None

    # Load the previous run's manifest, or None if there is none. Outside a dry run, also opens (or creates) it for
    # the final write, so an unwritable manifest stops the run before any file changes. Raises BLFileError if the
    # manifest is unusable.
    def _read_manifest(self) -> _Manifest | None:
        path = self._MANIFEST_FILENAME
        if self._options.dry_run:
            text = self._read_text(path, "read manifest")
        else:
            if self._options.no_symlink and _contains_symlink(path, self._pack_root_dir):
                raise BLFileError(f"Refusing to open manifest '{path}': the path contains a symlink.")
            try:
                try:
                    self._manifest_file = self._open_symlink_safe(path, "r+")
                except FileNotFoundError:
                    self._manifest_file = self._open_symlink_safe(path, "x+")
                text = self._manifest_file.read()
            except OSError as err:
                raise BLFileError(f"Failed to read and write '{path}': {err.strerror or err}.") from err
            except UnicodeDecodeError as err:
                raise BLFileError(f"Failed to read and write '{path}': {err}.") from err
        if text is None or not text.strip():  # missing, just created, or a crash interrupted the last write
            return None
        try:
            return self._parse_manifest(path, text)
        except BLFileError as err:
            raise BLFileError(f"{err} Delete '{path}' to rebuild from scratch.") from err

    # Manifest from its JSON `text`. Missing fields read as empty. Raises BLFileError if malformed.
    def _parse_manifest(self, path: str, text: str) -> _Manifest:
        root = self._manifest_dict(self._parse_json(path, text), "manifest")
        sources: dict[str, _ManifestSourceEntry] = {}
        for local_path, value in self._manifest_dict(root.get("sources", {}), "sources").items():
            where = f"sources.{local_path}"
            entry = self._manifest_dict(value, where)
            source_hash = entry.get("source_hash", "")
            if not isinstance(source_hash, str):
                self._log_bad_manifest_field(f"{where}.source_hash", "a string")
                source_hash = ""
            sources[local_path] = _ManifestSourceEntry(
                source_hash=source_hash,
                outputs=self._manifest_str_set(entry.get("outputs", []), f"{where}.outputs"),
            )

        version = self._version_pair(root.get("version", [0, 0]))
        if version is None:
            self._log_bad_manifest_field("version", "a [major, minor] pair")
            version = (0, 0)
        return _Manifest(
            sources=sources,
            load=self._manifest_str_set(root.get("load", []), "load"),
            tick=self._manifest_str_set(root.get("tick", []), "tick"),
            version=version,
        )

    # Write this run's manifest through the handle opened by _read_manifest, then close it.
    def _write_manifest(self) -> None:
        sources: dict[str, dict[str, object]] = {}
        for local_path, content_hash in self._source_hashes.items():
            outputs = self._source_outputs.get(local_path, {})
            sources[local_path] = {"outputs": sorted(outputs.keys() - self._failed_writes)}
            if local_path not in self._needs_recompile:  # a missing hash forces a recompile next run
                sources[local_path]["source_hash"] = content_hash
        manifest = {
            "version": list(_BL_VERSION),
            "load": self._tag_function_ids(self._result.load_functions),
            "tick": self._tag_function_ids(self._result.tick_functions),
            "sources": sources,
        }

        manifest_file = self._manifest_file
        assert manifest_file is not None
        try:
            with manifest_file:
                manifest_file.seek(0)
                manifest_file.truncate()
                json.dump(manifest, manifest_file, indent=2, sort_keys=True)
        except OSError as err:
            self._log_error(
                BLFileError(f"Failed to write manifest '{self._MANIFEST_FILENAME}': {err.strerror or err}.")
            )

    def _read_pack_format(self, pack_meta: dict[str, object]) -> int | None:
        pack_obj = pack_meta.get("pack")
        value: object = None
        if isinstance(pack_obj, dict):
            pack = cast(dict[str, object], pack_obj)  # JSON object keys are always strings
            if "min_format" in pack:
                value = pack["min_format"]
            elif "pack_format" in pack:
                value = pack["pack_format"]
            elif "supported_formats" in pack:
                value = pack["supported_formats"]

        if isinstance(value, dict):
            value = cast(dict[str, object], value).get("min_inclusive")
        if isinstance(value, list) and value:
            value = cast(list[object], value)[0]

        if isinstance(value, bool) or not isinstance(value, int | float):
            self._log_error(
                BLSyntaxError(
                    "The file 'pack.mcmeta' must declare 'min_format', 'pack_format', or 'supported_formats'."
                )
            )
            return None
        return int(value)

    # `value` as a JSON object, else raise BLFileError naming manifest field `where`.
    @staticmethod
    def _manifest_dict(value: object, where: str) -> dict[str, object]:
        if not isinstance(value, dict):
            raise BLFileError(f"Malformed manifest: '{where}' must be an object.")
        return cast(dict[str, object], value)

    # `value` as a set of strings, else raise BLFileError naming manifest field `where`.
    @staticmethod
    def _manifest_str_set(value: object, where: str) -> frozenset[str]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in cast(list[object], value)):
            raise BLFileError(f"Malformed manifest: '{where}' must be a list of strings.")
        return frozenset(cast(list[str], value))

    # Log a malformed manifest field whose fallback value only forces a recompile.
    def _log_bad_manifest_field(self, where: str, expected: str) -> None:
        self._log_error(BLFileError(f"Malformed manifest: '{where}' must be {expected}. Recompiling."))

    # `value` as a (major, minor) pair, or None if malformed.
    @staticmethod
    def _version_pair(value: object) -> tuple[int, int] | None:
        if isinstance(value, list):
            parts = cast(list[object], value)
            if len(parts) == 2 and all(type(part) is int for part in parts):  # rejects bool
                return (cast(int, parts[0]), cast(int, parts[1]))
        return None

    # Convert "data/<namespace>/function/<filepath_remainder>.mcfunction" to "<namespace>:<filepath_remainder>"
    @staticmethod
    def _function_id(filepath: str) -> str:
        _data, namespace, _function, *rest = filepath.split("/")
        return f"{namespace}:{'/'.join(rest).removesuffix('.mcfunction')}"

    # Contents of `path`, or None if it does not exist. Raises BLFileError if it cannot be read, or with
    # `writable`, if it cannot be written.
    def _read_text(self, path: str, action: str, writable: bool = False) -> str | None:
        if self._options.no_symlink and _contains_symlink(path, self._pack_root_dir):
            raise BLFileError(f"Refusing to {action} '{path}': the path contains a symlink.")
        access = "read and write" if writable else "read"
        try:
            with self._open_symlink_safe(path, "r+" if writable else "r") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as err:
            raise BLFileError(f"Failed to {access} '{path}': {err.strerror or err}.") from err
        except UnicodeDecodeError as err:
            raise BLFileError(f"Failed to {access} '{path}': {err}.") from err

    # Parsed JSON of `text`, else raise BLFileError naming `path`.
    @staticmethod
    def _parse_json(path: str, text: str) -> object:
        try:
            return json.loads(text)
        except (ValueError, RecursionError) as err:
            raise BLFileError(f"Malformed JSON in '{path}': {err}.") from err

    # Write `contents` to `path`, creating parent directories. Raises BLFileError on failure.
    def _write_text(self, path: str, contents: str, action: str) -> None:
        if self._options.no_symlink and _contains_symlink(path, self._pack_root_dir):
            raise BLFileError(f"Refusing to {action} '{path}': the path contains a symlink.")
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with self._open_symlink_safe(path, "w") as f:
                f.write(contents)
        except OSError as err:
            raise BLFileError(f"Failed to write '{path}': {err.strerror or err}.") from err

    # Yield .bl paths under blocklight_dir. With no_symlink, refuses to follow symlinked
    # directories or read symlinked files, logging a recoverable error for each one skipped.
    def _iter_bl_files(self, blocklight_dir: str) -> Iterator[str]:
        if self._options.no_symlink and _contains_symlink(blocklight_dir, self._pack_root_dir):
            self._log_error(BLFileError(f"Refusing to read '{blocklight_dir}': the path contains a symlink."))
            return
        for root, dirs, files in os.walk(blocklight_dir, followlinks=not self._options.no_symlink):
            if self._options.no_symlink:
                kept_dirs: list[str] = []
                for d in dirs:
                    full = os.path.join(root, d)
                    if _contains_symlink(full, self._pack_root_dir):
                        self._log_error(BLFileError(f"Refusing to follow '{full}': the path contains a symlink."))
                    else:
                        kept_dirs.append(d)
                dirs[:] = kept_dirs
            # A directory literally named "*.bl" is a candidate too; it fails naturally on open().
            for name in [*files, *(d for d in dirs if d.endswith(".bl"))]:
                if not name.endswith(".bl"):
                    continue
                path = os.path.join(root, name)
                if self._options.no_symlink and _contains_symlink(path, self._pack_root_dir):
                    self._log_error(BLFileError(f"Refusing to read '{path}': the path contains a symlink."))
                    continue
                yield path.replace(os.sep, "/")  # same manifest keys on every OS

    # Fails file open if a symlink must be traversed. New files get 0o666 like open(), so the umask decides.
    def _open_symlink_safe(self, path: str, mode: str = "r") -> IO[str]:
        no_follow = getattr(os, "O_NOFOLLOW", 0) if self._options.no_symlink else 0
        return open(path, mode, encoding="utf-8", opener=lambda p, flags: os.open(p, flags | no_follow, 0o666))


# Compiles one bl source file into the contents of its outputs. Never touches the disk: Pack reads the source and
# writes the outputs.
class Compile:
    _FUNCTION_HEADER_KEYWORDS = frozenset(("root", "load", "tick"))
    _MACRO_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_")
    _BLOCK_KEYWORD_SPECS: ClassVar[dict[str, _KeywordSpec]] = {
        "align": _KeywordSpec(_KeywordType.MODIFIER, True),
        "anchored": _KeywordSpec(_KeywordType.MODIFIER, True),
        "as": _KeywordSpec(_KeywordType.MODIFIER, True),
        "at": _KeywordSpec(_KeywordType.MODIFIER, True),
        "facing": _KeywordSpec(_KeywordType.MODIFIER, True),
        "in": _KeywordSpec(_KeywordType.MODIFIER, True),
        "on": _KeywordSpec(_KeywordType.MODIFIER, True),
        "positioned": _KeywordSpec(_KeywordType.MODIFIER, True),
        "rotated": _KeywordSpec(_KeywordType.MODIFIER, True),
        "summon": _KeywordSpec(_KeywordType.MODIFIER, True),
        "if": _KeywordSpec(_KeywordType.CONDITIONAL, True),
        "elif": _KeywordSpec(_KeywordType.CONDITIONAL, True),
        "while": _KeywordSpec(_KeywordType.CONDITIONAL, True),
        "else": _KeywordSpec(_KeywordType.CONDITIONAL, False),
        "python": _KeywordSpec(_KeywordType.INLINE_PYTHON, False),
    }

    # ----- Scoreboard reserved ----- #
    _BL_RESERVED_SCOREBOARD = "_bl"
    _BL_RETURNING_HOLDER = "#_bl_returning"
    _BL_SUCCESS_HOLDER = "#_bl_return_success"
    _BL_VALUE_HOLDER = "#_bl_return_value"
    _BL_COND_HOLDER = "#_bl_cond"  # 1 = true, 0 = false (a failed helper call stores 0)

    # ----- Compiled output strings ----- #
    HEADER_MARKER = "Compiled by Blocklight"
    _HEADER_TEXT: ClassVar[list[str]] = [
        f"# {HEADER_MARKER} {_BL_VERSION_STRING} (https://github.com/qcjames53/blocklight)",
        "# Changes saved to this file will not persist. Please modify the bl source file instead:",
    ]
    # A 'return' below a function's own level holds its result, sets #_bl_returning, and exits its helper. Each caller
    # forwards it up; the function's return_handler clears #_bl_returning and returns the held result. So the flag is
    # only ever 1 while a return climbs out of one function.
    _RET_VALUE = f"{_BL_VALUE_HOLDER} {_BL_RESERVED_SCOREBOARD}"
    _RET_SUCCESS = f"{_BL_SUCCESS_HOLDER} {_BL_RESERVED_SCOREBOARD}"
    _RET_RETURNING = f"{_BL_RETURNING_HOLDER} {_BL_RESERVED_SCOREBOARD}"
    # Mark the function as returning and exit this helper
    _RET_MARK_AND_EXIT = f"return run scoreboard players set {_RET_RETURNING} 1"
    # After a call to a child that may return, below the function's own level: forward the return up one level
    _RET_FORWARD = f"execute if score {_RET_RETURNING} matches 1 run return 0"
    # Body of <function>_helper/return_handler: end the return and give the function the held result
    _RET_HANDLER_LINES: ClassVar[list[str]] = [
        f"scoreboard players set {_RET_RETURNING} 0",
        f"execute if score {_RET_SUCCESS} matches 0 run return fail",
        f"return run scoreboard players get {_RET_VALUE}",
    ]

    def __init__(self, source: SourceFile, pack: _PackInfo) -> None:
        self._source = source
        self._pack = pack
        self._indent = "  "  # one indentation level, detected by compile()
        self._compiled = CompiledSource()
        self._helper_counts: dict[tuple[str, str], int] = {}  # (output function, helper kind) -> helpers named

    # Compile every function in the source, isolating recoverable errors to the function that raised them.
    # A top-level python block must emit whole functions, which are compiled next in place of the block.
    def compile(self) -> CompiledSource:
        try:
            self._indent = self._single_indent(self._source.source_lines)
            span_iters = [self._iter_spans(self._source.source_lines, 0)]
            while span_iters:
                span = next(span_iters[-1], None)
                if span is None:  # base case
                    span_iters.pop()
                    continue
                try:
                    if span[0].as_keyword_args()[0] == "python":
                        span_iters.append(self._iter_spans(self._handle_top_level_python_block(span), 0))
                    else:
                        self._compile_function(span)
                except BLNonFatalError as err:
                    self._compiled.errors.append(err)
        except BLFatalError as err:
            self._compiled.errors.append(err)
        return self._compiled

    # Execute a python block outside any function and return the lines it emits, which must begin a function.
    def _handle_top_level_python_block(self, span: list[_Line]) -> list[_Line]:
        head = span[0]
        if len(span) == 1:
            raise BLSyntaxError("This 'python' block has no body.", head)
        if head.text != "python":
            raise BLSyntaxError("This 'python' block does not permit arguments.", head)
        emitted = self._handle_python_block(_BlockInput("", "", 0), span)
        if emitted and emitted[0].text[:1].isspace():
            raise BLSyntaxError("This top-level Python block must emit a function definition first.", head)
        return emitted

    @staticmethod
    def _single_indent(lines: list[_Line]) -> str:
        for line in lines:
            indent = line.text[: len(line.text) - len(line.text.lstrip())]
            if not indent:
                continue
            if " " in indent and "\t" in indent:
                raise BLFatalError(
                    "This file's detected indentation schema mixes tabs and spaces, which is not permitted.", line
                )
            return indent
        return "  "

    # Yield lists of _Line objects for each command / block encountered at provided depth.
    def _iter_spans(self, lines: list[_Line], depth: int) -> Iterator[list[_Line]]:
        indent = "" if depth == 0 else self._indent * depth
        indent_len = len(indent)

        if lines and lines[0].text[indent_len : indent_len + 1].isspace():  # first line must sit at this depth
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

    # Convert a minecraft-consumable namespaced function name
    # "<namespace>:<path/without/extension>" -> "data/<namespace>/function/<path>.mcfunction".
    @staticmethod
    def _function_filepath(function_name: str) -> str:
        namespace, path = function_name.split(":", 1)
        return f"data/{namespace}/function/{path}.mcfunction"

    # Name the next helper of `kind` (e.g. "as") under output function `function_name`: "<function_name>_helper/as_0",
    # then as_1. Numbering is per output function, including blocks a python block emits into it.
    def _helper_name(self, function_name: str, kind: str) -> str:
        index = self._helper_counts.get((function_name, kind), 0)
        self._helper_counts[(function_name, kind)] = index + 1
        return f"{function_name}_helper/{kind}_{index}"

    # Prefix of the namespaced name of every non-root function defined in this source file: "<ns>:<subdirs>/<file>/".
    def _sibling_id_prefix(self) -> str:
        _data, namespace, _src_root, *subdirs, source_file = self._source.local_path.split("/")
        return f"{namespace}:" + "/".join([*subdirs, source_file.removesuffix(".bl")]) + "/"

    # Namespaced path of non-root function `function_name` defined in this source file, as `_compile_function` names it.
    def _local_function_path(self, function_name: str) -> str:
        return self._sibling_id_prefix() + function_name

    # Header lines every compiled output file (including helpers) begins with.
    def _header_lines(self, lineno: int) -> list[str]:
        return [*self._HEADER_TEXT, f"#     `{self._source.local_path}:{lineno}`"]

    # Contents of the load function that creates the reserved scoreboard objective.
    @staticmethod
    def setup_function_contents() -> str:
        return f"{Compile._HEADER_TEXT[0]}\nscoreboard objectives add {Compile._BL_RESERVED_SCOREBOARD} dummy"

    # Record `block_out` as the output file of `function_name`, defined at `line`.
    # Raises BLFileError for a path outside the namespace or one this source already compiles to.
    def _add_output(self, function_name: str, block_out: _BlockOutput, line: _Line) -> None:
        filepath = self._function_filepath(function_name)
        namespace = function_name.split(":", 1)[0]
        if not _in_function_dir(filepath, namespace):
            raise BLFileError(f"Output path '{filepath}' escapes namespace '{namespace}'.", line)
        if filepath in self._compiled.mcf_outputs:
            raise BLFileError(f"Another function already compiles to '{filepath}'.", line)
        self._compiled.mcf_outputs[filepath] = _MCFOutputContents("\n".join(block_out.lines), line)

    # Validate a function header and compile its body to an mcfunction file.
    def _compile_function(self, lines: list[_Line]) -> None:
        header = lines[0]
        header_split = header.text.split("function ")
        if len(header_split) <= 1:
            raise BLSyntaxError(
                "This line is interpreted as a function header but does not declare a function. "
                "Double-check indentation.",
                header,
            )
        if len(header_split) > 2:
            raise BLSyntaxError("This is an invalid function header.", header)

        # Validate header keywords
        seen_keywords: set[str] = set()
        for word in header_split[0].split():
            if word not in self._FUNCTION_HEADER_KEYWORDS:
                raise BLSyntaxError(f"This function definition declares an unknown keyword: '{word}'.", header)
            if word in seen_keywords:
                raise BLSyntaxError(f"This function definition declares '{word}' twice.", header)
            seen_keywords.add(word)

        # Validate function name
        function_name, is_root, is_load, is_tick = header.as_function_header()
        if not function_name:
            raise BLSyntaxError(
                "This function definition does not declare a function name (e.g. 'function foo').", header
            )
        if sorted(set(function_name) - _FUNCTION_NAME_CHARS):
            raise BLSyntaxError(f"The function name '{function_name}' may only use a-z, 0-9, '_' and '-'.", header)

        # Validate function actually has contents. No output otherwise.
        if len(lines) == 1:
            return

        # Determine output filepath from the source path, data/<ns>/blocklight/*/f.bl
        if is_root:
            output_name = f"{self._source.namespace}:{function_name}"
        else:
            output_name = self._local_function_path(function_name)
        block_in = _BlockInput(function_name, output_name, 1, output_name)
        output_filepath = self._function_filepath(block_in.function_name)
        # Checked before its helpers continue the earlier function's numbering
        if output_filepath in self._compiled.mcf_outputs:
            raise BLFileError(f"Another function already compiles to '{output_filepath}'.", header)

        # Build function and helpers
        block_out = _BlockOutput()
        block_out.lines.extend(self._header_lines(header.lineno))
        self._compile_lines(block_in, block_out, lines[1:])
        if block_out.can_return:  # a return below this level climbs to the function's return handler
            handler_out = _BlockOutput()
            handler_out.lines.extend(self._header_lines(header.lineno))
            handler_out.lines.extend(self._RET_HANDLER_LINES)
            self._add_output(self._return_handler_name(block_in.function_name), handler_out, header)

        # Write output file to disk
        self._add_output(block_in.function_name, block_out, header)
        if is_load:
            self._compiled.load.add(output_filepath)
        if is_tick:
            self._compiled.tick.add(output_filepath)

    # Compile the commands in `lines` (at `depth`) to an output mcfunction + recursively compile child blocks.
    def _compile_lines(self, block_in: _BlockInput, block_out: _BlockOutput, lines: list[_Line]) -> None:
        pending_chain: list[tuple[str, str, list[_Line]]] = []  # In progress if-chain

        # Iterate over commands and block headers at depth
        # Spans are a list of one header _Line + child _Lines at greater indentation
        # Each python block pushes an iterator over its output's spans, read before the spans after the block
        span_iters = [self._iter_spans(lines, block_in.depth)]
        while span_iters:
            span = next(span_iters[-1], None)
            if span is None:
                span_iters.pop()
                continue
            line = span[0]
            text = line.text.lstrip()  # right is already stripped
            has_body = len(span) > 1
            keyword, args = line.as_keyword_args()
            keyword_spec = self._BLOCK_KEYWORD_SPECS.get(keyword)
            if keyword == "summon" and not has_body:  # without a block, 'summon' is the vanilla command
                keyword_spec = None

            # Anything other than a continuing 'elif'/'else' closes a pending if-chain.
            # A python block's output may contain 'elif'/'else' so we inline expand before closing the chain.
            if keyword not in ("elif", "else", "python") and pending_chain:
                self._compile_if_chain(block_in, block_out, pending_chain)
                pending_chain = []

            # Handle block keywords
            if keyword_spec is not None:
                if not has_body:
                    raise BLSyntaxError(f"This '{keyword}' block has no body.", line)
                if args.startswith(" "):
                    raise BLSyntaxError("There are too many spaces between the keyword and the arguments.", line)
                if keyword_spec.args_required and args == "":
                    raise BLSyntaxError(f"This '{keyword}' block requires arguments.", line)
                if not keyword_spec.args_required and args != "":
                    raise BLSyntaxError(f"This '{keyword}' block does not permit arguments.", line)

                match keyword_spec.type:
                    case _KeywordType.MODIFIER:
                        # Recursively compile this block into
                        # <current_function>_helper/<keyword>_<instance_of_this_keyword>.mcfunction
                        child_function_name = self._helper_name(block_in.function_name, keyword)
                        new_block_in = block_in._replace(function_name=child_function_name, depth=block_in.depth + 1)
                        new_block_out = _BlockOutput()
                        new_block_out.lines.extend(self._header_lines(line.lineno))
                        self._compile_lines(new_block_in, new_block_out, span[1:])
                        self._add_output(child_function_name, new_block_out, line)

                        # Determine what framework needs to be constructed around the child function call
                        macros_string = self._macros_forwarder(new_block_out.macros)  # Were macros used?
                        self._append_line_to_block_out(
                            block_out,
                            _Line(
                                f"execute {keyword} {args} run function {child_function_name}{macros_string}",
                                line.lineno,
                            ),
                        )

                        if new_block_out.can_return:
                            self._append_return_handler(block_in, block_out)

                    case _KeywordType.CONDITIONAL:
                        if keyword == "while":
                            self._compile_while(block_in, block_out, span)
                        elif keyword == "if":
                            pending_chain = [(keyword, args, span)]
                        else:  # 'elif' or 'else', continuing the chain just closed above if unrelated
                            if not pending_chain:
                                raise BLSyntaxError(
                                    f"An '{keyword}' block must immediately follow an 'if' or 'elif' block.", line
                                )
                            pending_chain.append((keyword, args, span))
                            if keyword == "else":  # 'else' always ends a chain
                                self._compile_if_chain(block_in, block_out, pending_chain)
                                pending_chain = []

                    case _KeywordType.INLINE_PYTHON:
                        # Execute python (if permitted); the lines it emits are compiled next, in place of this block
                        emitted = self._handle_python_block(block_in, span)
                        span_iters.append(self._iter_spans(emitted, block_in.depth))

            # Raise error on regular commands with body
            elif has_body:
                raise BLSyntaxError("Only block keywords may begin an indented block.", span[1])

            # Handle inline return commands. At the function's own level they are vanilla returns already.
            elif text.startswith("execute ") and " run return " in text and block_in.depth > 1:
                split_result = text.split(" run return ")
                if len(split_result) != 2:
                    raise BLSyntaxError("This 'execute' statement contains a malformed 'return' command.", line)
                execute_command, return_command_tail = split_result

                # Create a child helper file to call the inline return
                child_function_name = self._helper_name(block_in.function_name, "return")
                child_block_out = _BlockOutput()
                child_block_out.lines.extend(self._header_lines(line.lineno))
                self._append_nested_return(child_block_out, _Line(return_command_tail, line.lineno))
                self._add_output(child_function_name, child_block_out, line)

                # Call the helper inline, forcing return if it runs.
                block_out.can_return = True
                macros_string = self._macros_forwarder(child_block_out.macros)
                self._append_line_to_block_out(
                    block_out,
                    _Line(
                        f"{execute_command} run return run function {child_function_name}{macros_string}",
                        line.lineno,
                    ),
                )

            # Handle regular return commands. At the function's own level they are vanilla returns already.
            elif text.startswith("return ") and block_in.depth > 1:
                self._append_nested_return(block_out, _Line(text[len("return ") :], line.lineno))

            # Handle regular commands
            else:
                self._append_line_to_block_out(block_out, line)

        # Close any trailing if-chains at the end of the block.
        if pending_chain:
            self._compile_if_chain(block_in, block_out, pending_chain)

    # Compile 'return <tail>' below the function's own level: hold the result, then mark and exit (see _RET_VALUE).
    # The result is held before marking, so a function the tail calls can't clear the mark.
    def _append_nested_return(self, block_out: _BlockOutput, tail: _Line) -> None:
        block_out.can_return = True
        if tail.text == "fail":
            commands = [f"scoreboard players set {self._RET_SUCCESS} 0"]
        elif tail.text.startswith("run "):
            commands = [
                f"scoreboard players set {self._RET_SUCCESS} 0",  # stays 0 if it runs a function that never returns
                f"execute store result score {self._RET_VALUE} store success score {self._RET_SUCCESS} {tail.text}",
            ]
        else:
            commands = [
                f"scoreboard players set {self._RET_VALUE} {tail.text}",
                f"scoreboard players set {self._RET_SUCCESS} 1",
            ]
        for command in [*commands, self._RET_MARK_AND_EXIT]:
            self._append_line_to_block_out(block_out, _Line(command, tail.lineno))

    # After a call to a child that may return: forward the return up a level, or at the function's own level, hand
    # it to the function's return handler.
    def _append_return_handler(self, block_in: _BlockInput, block_out: _BlockOutput) -> None:
        block_out.can_return = True
        if block_in.depth > 1:
            block_out.lines.append(self._RET_FORWARD)
        else:
            handler_name = self._return_handler_name(block_in.function_name)
            block_out.lines.append(
                f"execute if score {self._RET_RETURNING} matches 1 run return run function {handler_name}"
            )

    @staticmethod
    def _return_handler_name(function_name: str) -> str:
        return f"{function_name}_helper/return_handler"

    # Compile one if-elif-else chain.
    def _compile_if_chain(
        self, block_in: _BlockInput, block_out: _BlockOutput, chain: list[tuple[str, str, list[_Line]]]
    ) -> None:
        dispatcher_function_name = self._helper_name(block_in.function_name, "chain")  # also prefixes each branch
        if_line = chain[0][2][0]

        # Compile each branch's body recursively
        branches: list[tuple[_CompiledCondition | None, str, _BlockOutput]] = []  # (None for else, name, output)
        elif_index = 0
        for keyword, args, span in chain:
            header_line = span[0]
            cond: _CompiledCondition | None = None
            if keyword == "if":
                branch_name = "if"
                cond = self._compile_condition(block_in, args, header_line)
            elif keyword == "elif":
                branch_name = f"elif_{elif_index}"
                elif_index += 1
                cond = self._compile_condition(block_in, args, header_line)
            else:
                branch_name = "else"

            child_function_name = f"{dispatcher_function_name}_{branch_name}"
            new_block_in = block_in._replace(function_name=child_function_name, depth=block_in.depth + 1)
            new_block_out = _BlockOutput()
            new_block_out.lines.extend(self._header_lines(header_line.lineno))
            self._compile_lines(new_block_in, new_block_out, span[1:])
            self._add_output(child_function_name, new_block_out, header_line)
            branches.append((cond, child_function_name, new_block_out))

        # Bare 'if' chains use a single execute command to run the compiled helper function.
        if len(branches) == 1:
            cond, child_function_name, branch_out = branches[0]
            assert cond is not None
            for setup_line in cond.setup_lines:
                self._append_line_to_block_out(block_out, setup_line)
            macros_string = self._macros_forwarder(branch_out.macros)
            self._append_line_to_block_out(
                block_out,
                _Line(f"execute {cond.subcommands} run function {child_function_name}{macros_string}", if_line.lineno),
            )
            if branch_out.can_return:
                self._append_return_handler(block_in, block_out)
            return

        # Chains containing elif or else use an intermediate helper function to use return commands (fastest option).
        dispatcher_out = _BlockOutput()
        dispatcher_out.lines.extend(self._header_lines(if_line.lineno))
        for cond, child_function_name, branch_out in branches:
            macros_string = self._macros_forwarder(branch_out.macros)
            if cond is not None:  # 'if' / 'elif': only run (and exit the dispatcher) if the condition matches
                for setup_line in cond.setup_lines:
                    self._append_line_to_block_out(dispatcher_out, setup_line)
                self._append_line_to_block_out(
                    dispatcher_out,
                    _Line(
                        f"execute {cond.subcommands} run return run function {child_function_name}{macros_string}",
                        if_line.lineno,
                    ),
                )
            else:  # 'else': unconditional, always last
                self._append_line_to_block_out(
                    dispatcher_out, _Line(f"return run function {child_function_name}{macros_string}", if_line.lineno)
                )
            if branch_out.can_return:
                dispatcher_out.can_return = True
        self._add_output(dispatcher_function_name, dispatcher_out, if_line)

        # Call the dispatcher unconditionally; it already decided which branch (if any) matched.
        macros_string = self._macros_forwarder(dispatcher_out.macros)
        self._append_line_to_block_out(
            block_out,
            _Line(f"function {dispatcher_function_name}{macros_string}", if_line.lineno),
        )
        if dispatcher_out.can_return:
            self._append_return_handler(block_in, block_out)

    # Compile a while loop: the head helper tests the condition and tail-calls the body, which tail-calls the head.
    def _compile_while(self, block_in: _BlockInput, block_out: _BlockOutput, span: list[_Line]) -> None:
        line = span[0]
        _keyword, args = line.as_keyword_args()
        head_function_name = self._helper_name(block_in.function_name, "while")
        body_function_name = f"{head_function_name}_body"
        cond = self._compile_condition(block_in, args, line)

        body_in = block_in._replace(function_name=body_function_name, depth=block_in.depth + 1)
        body_out = _BlockOutput()
        body_out.lines.extend(self._header_lines(line.lineno))
        self._compile_lines(body_in, body_out, span[1:])
        # Head and body call each other, so both forward the union of their macros
        loop_macros_string = self._macros_forwarder(body_out.macros | cond.macros)
        self._append_line_to_block_out(
            body_out, _Line(f"return run function {head_function_name}{loop_macros_string}", line.lineno)
        )
        self._add_output(body_function_name, body_out, line)

        head_out = _BlockOutput()
        head_out.lines.extend(self._header_lines(line.lineno))
        for setup_line in cond.setup_lines:
            self._append_line_to_block_out(head_out, setup_line)
        self._append_line_to_block_out(
            head_out,
            _Line(
                f"execute {cond.subcommands} run return run function {body_function_name}{loop_macros_string}",
                line.lineno,
            ),
        )
        self._add_output(head_function_name, head_out, line)

        self._append_line_to_block_out(
            block_out, _Line(f"function {head_function_name}{self._macros_forwarder(head_out.macros)}", line.lineno)
        )
        if body_out.can_return:
            self._append_return_handler(block_in, block_out)

    # Compile an if/elif condition to execute subcommands.
    def _compile_condition(self, block_in: _BlockInput, args: str, line: _Line) -> _CompiledCondition:
        node = self._normalize_condition(self._parse_condition(args, line))
        cond_in = _ConditionInput(block_in, line, {})
        if not self._condition_has_macro_or(node):
            subcommands = self._condition_subcommands(cond_in, node)
            macros = set(self._iter_macro_names(_Line(subcommands, line.lineno)))
            return _CompiledCondition([], subcommands, macros)

        clauses = self._condition_clauses(node)
        cond_function_name, cond_out = self._add_condition_function(cond_in, clauses)
        holder = f"{self._BL_COND_HOLDER} {self._BL_RESERVED_SCOREBOARD}"
        macros_string = self._macros_forwarder(cond_out.macros)
        return _CompiledCondition(
            [
                _Line(
                    f"execute store result score {holder} run function {cond_function_name}{macros_string}",
                    line.lineno,
                ),
            ],
            f"if score {holder} matches 1",
            cond_out.macros,
        )

    # Execute subcommands testing a normalized condition. Adds one helper per distinct 'or' node.
    def _condition_subcommands(self, cond_in: _ConditionInput, node: _ConditionalNode) -> str:
        if isinstance(node, _ConditionalStatement):
            return f"{'unless' if node.negated else 'if'} {node.text}"
        if node.op == "and":
            return " ".join(self._condition_subcommands(cond_in, term) for term in node.terms)
        if node not in cond_in.or_functions:
            cond_in.or_functions[node], _cond_out = self._add_condition_function(
                cond_in, [[term] for term in node.terms]
            )
        return f"if function {cond_in.or_functions[node]}"

    # Add a helper returning 1 if any clause (conjunction of terms) matches, else 0.
    def _add_condition_function(
        self, cond_in: _ConditionInput, clauses: list[list[_ConditionalNode]]
    ) -> tuple[str, _BlockOutput]:
        cond_function_name = self._helper_name(cond_in.block_in.function_name, "cond")
        cond_out = _BlockOutput()
        cond_out.lines.extend(self._header_lines(cond_in.line.lineno))
        for clause in clauses:
            subcommands = " ".join(self._condition_subcommands(cond_in, term) for term in clause)
            self._append_line_to_block_out(cond_out, _Line(f"execute {subcommands} run return 1", cond_in.line.lineno))
        cond_out.lines.append("return 0")
        self._add_output(cond_function_name, cond_out, cond_in.line)
        return cond_function_name, cond_out

    # Distribute 'and' over macro-bearing 'or' nodes, giving clauses in order. Macro-free subtrees stay whole.
    @staticmethod
    def _condition_clauses(node: _ConditionalNode) -> list[list[_ConditionalNode]]:
        if isinstance(node, _ConditionalStatement) or not Compile._condition_has_macro(node):
            return [[node]]
        if node.op == "or":
            return [clause for term in node.terms for clause in Compile._condition_clauses(term)]
        clauses: list[list[_ConditionalNode]] = [[]]
        for term in node.terms:
            clauses = [clause + term_clause for clause in clauses for term_clause in Compile._condition_clauses(term)]
        return clauses

    @staticmethod
    def _condition_has_macro(node: _ConditionalNode) -> bool:
        if isinstance(node, _ConditionalStatement):
            return "$(" in node.text
        return any(Compile._condition_has_macro(term) for term in node.terms)

    # Whether any 'or' node references a macro.
    @staticmethod
    def _condition_has_macro_or(node: _ConditionalNode) -> bool:
        if isinstance(node, _ConditionalStatement):
            return False
        if node.op == "or" and Compile._condition_has_macro(node):
            return True
        return any(Compile._condition_has_macro_or(term) for term in node.terms)

    # Push 'not' down to atoms using De Morgan's law and flatten nested same-operator nodes.
    @staticmethod
    def _normalize_condition(node: _ConditionalNode, negate: bool = False) -> _ConditionalNode:
        if isinstance(node, _ConditionalStatement):
            return node._replace(negated=node.negated != negate)
        if node.op == "not":
            return Compile._normalize_condition(node.terms[0], not negate)
        op = {"and": "or", "or": "and"}[node.op] if negate else node.op
        terms: list[_ConditionalNode] = []
        for term in node.terms:
            normalized = Compile._normalize_condition(term, negate)
            if isinstance(normalized, _ConditionalOperator) and normalized.op == op:
                terms.extend(normalized.terms)
            else:
                terms.append(normalized)
        return _ConditionalOperator(op, tuple(terms))

    # Parse an if/elif condition into a tree. Precedence: 'not' > 'and' > 'or'.
    @staticmethod
    def _parse_condition(args: str, line: _Line) -> _ConditionalNode:
        def parse_binary(op: str, parse_term: Callable[[], _ConditionalNode]) -> _ConditionalNode:
            nonlocal pos
            terms = [parse_term()]
            while pos < len(tokens) and tokens[pos][0] == op:
                pos += 1
                terms.append(parse_term())
            return terms[0] if len(terms) == 1 else _ConditionalOperator(op, tuple(terms))

        def parse_or() -> _ConditionalNode:
            return parse_binary("or", parse_and)

        def parse_and() -> _ConditionalNode:
            return parse_binary("and", parse_not)

        def parse_not() -> _ConditionalNode:
            nonlocal pos
            kind = tokens[pos][0] if pos < len(tokens) else ""
            if kind == "not":
                pos += 1
                return _ConditionalOperator("not", (parse_not(),))
            if kind == "(":
                pos += 1
                node = parse_or()
                if pos >= len(tokens):
                    raise BLSyntaxError("This condition is missing a closing ')'.", line)
                if tokens[pos][0] != ")":
                    raise BLSyntaxError(f"This condition expected ')' but found '{tokens[pos][1]}'.", line)
                pos += 1
                return node
            if kind == "atom":
                pos += 1
                return _ConditionalStatement(tokens[pos - 1][1])
            if pos >= len(tokens):
                raise BLSyntaxError("This condition ends where a condition was expected.", line)
            raise BLSyntaxError(f"This condition expected a condition but found '{tokens[pos][1]}'.", line)

        tokens = Compile._tokenize_condition(args, line)
        pos = 0
        node = parse_or()
        if pos < len(tokens):
            raise BLSyntaxError(
                f"This condition has an unexpected '{tokens[pos][1]}'. Join conditions with 'and' or 'or'.", line
            )
        return node

    # Split a condition into (kind, text) tokens of kind "(", ")", "and", "or", "not" or "atom".
    # Brackets, braces, quoted strings and `$(macro)` references stay intact inside atoms.
    @staticmethod
    def _tokenize_condition(cond: str, line: _Line) -> list[tuple[str, str]]:
        def flush(end: int) -> None:
            text = cond[atom_start:end].strip()
            if text:
                tokens.append(("atom", text))

        def is_boundary(index: int) -> bool:
            return index < 0 or index >= len(cond) or cond[index].isspace() or cond[index] in "()"

        tokens: list[tuple[str, str]] = []
        closers: list[str] = []  # expected closers for open '[' / '{'
        atom_start = 0
        i = 0
        while i < len(cond):
            ch = cond[i]
            if ch in "\"'":  # skip quoted string
                end = i + 1
                while end < len(cond) and cond[end] != ch:
                    end += 2 if cond[end] == "\\" else 1
                if end >= len(cond):
                    raise BLSyntaxError("This condition has an unterminated string.", line)
                i = end + 1
                continue
            if ch in "[{":
                closers.append("]" if ch == "[" else "}")
            elif ch in "]}":
                if not closers or closers.pop() != ch:
                    raise BLSyntaxError(f"This condition has an unmatched '{ch}'.", line)
            elif closers:
                pass
            elif cond.startswith("$(", i):  # macro reference stays in the atom
                end = cond.find(")", i)
                i = len(cond) if end == -1 else end + 1
                continue
            elif ch in "()":
                flush(i)
                tokens.append((ch, ch))
                atom_start = i + 1
            else:
                for op in frozenset(("and", "or", "not")):
                    if not (cond.startswith(op, i) and is_boundary(i - 1) and is_boundary(i + len(op))):
                        continue
                    if op == "not" and cond[atom_start:i].strip():  # unary: only where an operand begins
                        continue
                    flush(i)
                    tokens.append((op, op))
                    i += len(op)
                    atom_start = i
                    break
                else:
                    i += 1
                continue
            i += 1
        if closers:
            raise BLSyntaxError(f"This condition is missing a closing '{closers[-1]}'.", line)
        flush(len(cond))
        return tokens

    @staticmethod
    def _append_line_to_block_out(block_out: _BlockOutput, line: _Line) -> None:
        text = line.text.lstrip()
        uses_macros = False
        if "$(" in text:
            for macro_name in Compile._iter_macro_names(line):
                block_out.macros.add(macro_name)
                uses_macros = True
        block_out.lines.append("$" + text if uses_macros else text)

    # Build a vanilla `{...}` clause forwarding each of `macros` from the current function's
    # own macro arguments into the function being called.
    @staticmethod
    def _macros_forwarder(macros: set[str]) -> str:
        if not macros:
            return ""
        macro_args = ", ".join(f'"{m}": "$({m})"' for m in sorted(macros))
        return f" {{{macro_args}}}"

    # Yield the name inside each vanilla macro '$(name)' in line, left to right.
    @staticmethod
    def _iter_macro_names(line: _Line) -> Iterator[str]:
        search_from = 0
        while (name_start := line.text.find("$(", search_from)) != -1:
            name_end = line.text.find(")", name_start + 2)
            if name_end == -1:
                raise BLSyntaxError("This line opens a macro with '$(' but never closes it with ')'.", line)
            name = line.text[name_start + 2 : name_end]
            if not name:
                raise BLSyntaxError("This line declares an empty macro '$()'.", line)
            if set(name) - Compile._MACRO_NAME_CHARS:
                raise BLSyntaxError(f"The macro name '{name}' may only use a-z, A-Z, 0-9 and '_'.", line)
            yield name
            search_from = name_end + 1

    # The source line behind line `body_lineno` of a python block's body, or its header when unknown.
    # Body line k is span[k]: the body is the span's cleaned lines joined with newlines.
    @staticmethod
    def _python_line(span: list[_Line], body_lineno: int | None) -> _Line:
        return span[body_lineno] if body_lineno is not None and 0 < body_lineno < len(span) else span[0]

    # Execute a python: block and return the lines it emits re-indented to the block's depth and anchored at its header.
    def _handle_python_block(self, block_in: _BlockInput, span: list[_Line]) -> list[_Line]:
        head = span[0]
        body = textwrap.dedent("\n".join(ln.text for ln in span[1:]))

        if self._pack.options.no_python:
            raise BLSyntaxError("This Python block is disabled due to your compile parameters.", head)
        self._compiled.ran_python = True
        emitter = _PythonEmitter(self._indent, block_in.depth)
        local_path = self._source.local_path
        scope = self._compiled.python_scope
        scope["cmd"] = emitter.cmd
        scope["blk"] = emitter.blk
        function_id = block_in.source_function_id  # empty outside any function
        scope.update(
            SOURCE_FILEPATH=local_path,
            FUNCTION_NAME=block_in.source_function_name or None,
            FUNCTION_ID=function_id or None,
            OUTPUT_FILEPATH=self._function_filepath(function_id) if function_id else None,
            HELPER_ID=block_in.function_name or None,
            SIBLING_ID_PREFIX=self._sibling_id_prefix(),
            PACK_NAME=self._pack.name,
            PACK_FORMAT=self._pack.format,
            BLOCKLIGHT_VERSION=_BL_VERSION_STRING,
        )
        filename = f"{local_path}:{head.lineno} python: block"
        try:
            exec(compile(body, filename, "exec"), scope)
        except SyntaxError as err:
            raise BLPythonError(
                f"This Python block is invalid: {err.msg}.", self._python_line(span, err.lineno)
            ) from err
        except Exception as err:
            tb_lineno = None
            tb = err.__traceback__
            while tb is not None:  # deepest frame still inside this block's own code
                if tb.tb_frame.f_code.co_filename == filename:
                    tb_lineno = tb.tb_lineno
                tb = tb.tb_next
            message = f"This Python block raised {type(err).__name__}: {err}."
            raise BLPythonError(message, self._python_line(span, tb_lineno)) from err

        return list(_iter_clean_lines((head.lineno, raw_line) for raw_line in emitter.lines))


def main() -> None:
    if sys.version_info < _MIN_PYTHON:
        required = ".".join(str(part) for part in _MIN_PYTHON)
        raise SystemExit(f"Blocklight {_BL_VERSION_STRING} requires Python {required} or newer.")

    # parse CLI args
    parser = argparse.ArgumentParser(
        prog="blocklight",
        description="A blazing fast mcfunction microcompiler. Run Blocklight from your datapack's root directory (the \
                     directory containing pack.mcmeta).",
    )
    parser.add_argument("--dry-run", action="store_true", help="test compile without writing any files to disk")
    parser.add_argument("--force", action="store_true", help="ignore compiler optimizations and recompile all files")
    parser.add_argument("--no-python", action="store_true", help="reject `python` blocks")
    parser.add_argument("--no-symlink", action="store_true", help="reject read and write of symlinked files.")
    parser.add_argument("--safe", action="store_true", help="safely compile a datapack if you do not trust the author")
    parser.add_argument("--version", action="version", version=f"Blocklight {_BL_VERSION_STRING}")
    args = parser.parse_args()
    options = CompilerOptions(
        no_python=args.no_python or args.safe,
        no_symlink=args.no_symlink or args.safe,
        dry_run=args.dry_run,
        force=args.force,
    )

    # Compile
    start_time = time.monotonic()  # timer starts after argparse for branding reasons :)
    result = Pack(options).compile()
    report(result, time.monotonic() - start_time)
    if result.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
