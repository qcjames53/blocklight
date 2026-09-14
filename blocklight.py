"""Blocklight - A blazing fast mcfunction microcompiler"""

import argparse
import hashlib
import json
import os
import string
import sys
import textwrap
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import InitVar, dataclass, field
from functools import cached_property
from typing import NamedTuple, cast

_BL_VERSION = "1.0.dev"
_MIN_PYTHON = (3, 10)  # Python 3.10 EOL October 2026

_FUNCTION_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits + "_-")
_MACRO_NAME_CHARS = frozenset(string.ascii_letters + string.digits + "_")
_FUNCTION_HEADER_KEYWORDS = frozenset(("root", "load", "tick"))
_MODIFIER_BLOCK_KEYWORDS = frozenset(
    ("align", "anchored", "as", "at", "facing", "in", "on", "positioned", "rotated", "summon")
)
_CONDITION_BLOCK_KEYWORDS = frozenset(("if", "elif", "else", "while"))
_BLOCK_KEYWORDS = _MODIFIER_BLOCK_KEYWORDS | _CONDITION_BLOCK_KEYWORDS | {"python"}
_FILE_WRITE_WORKERS_COUNT = 8
_MANIFEST_FILENAME = ".blocklight-manifest.json"
_HEADER_MARKER = "Compiled by Blocklight"


class _Line(NamedTuple):
    text: str
    lineno: int


class _ManifestEntry(NamedTuple):
    source_hash: str | None
    source_size: int | None
    outputs: frozenset[str]
    needs_recompile: bool


# Manifest file tracking facets of the previous compile
class _Manifest(NamedTuple):
    sources: dict[str, _ManifestEntry]
    load: frozenset[str]
    tick: frozenset[str]


class BLError(SyntaxError):
    def __init__(self, msg: str, line: _Line | None = None):
        super().__init__(msg)
        if line is not None:
            self.lineno = line.lineno
            self.text = line.text


class BLNonFatalError(BLError):  # Nonfatal error, keep compile going in next function.
    pass


class BLFatalError(BLError):  # Fatal error, stop compile of this concurrency.
    pass


class BLSyntaxError(BLNonFatalError):  # Syntax error in function. Other functions in the file continue to compile.
    pass


class BLPythonError(BLNonFatalError):  # Raised while compiling a python: block; recoverable like BLSyntaxError.
    pass


class BLFileError(BLNonFatalError):  # Raised on failures during file operations
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


# Compile-time options, owned and parsed by TUI.
@dataclass(frozen=True)
class CompilerOptions:
    no_header: bool = False  # Omit the "Compiled by Blocklight" header comment from each output file
    no_python: bool = False  # Throw an error on `python:` blocks instead of executing them
    no_symlink: bool = False  # Refuse to follow symlinked directories or read symlinked source files
    verify_before_delete: bool = False  # Before deleting a stale output, confirm it has the Blocklight header
    dry_run: bool = False  # Compile in-memory only; do not write any files to disk


# Read-only context threaded through the compilation of one function.
@dataclass
class _BlockInput:
    sf: SourceFile
    function_name: str


# Mutable accumulator built up while compiling a function body.
@dataclass
class _BlockOutput:
    lines: list[str] = field(default_factory=list[str])  # compiled mcfunction command lines
    macros: set[str] = field(default_factory=set[str])  # vanilla macros the block may use
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


# Parses CLI args and is the sole recipient of every BLError raised anywhere in the compiler.
# Also carries the `tick_*` hooks that will drive a future progress UI; for now they're no-ops.
class TUI:
    def __init__(self) -> None:
        self._options = CompilerOptions()
        self._errors: list[BLError] = []
        self._lock = threading.Lock()

    def set_options(self, options: CompilerOptions) -> None:
        self._options = options

    def parse_args(self, argv: list[str] | None = None) -> None:
        parser = argparse.ArgumentParser(prog="blocklight", description=__doc__)
        parser.add_argument("--version", action="version", version=f"Blocklight {_BL_VERSION}")
        parser.add_argument(
            "--no-header",
            action="store_true",
            help='omit the "Compiled by Blocklight" header comment from each output file',
        )
        parser.add_argument(
            "--no-python", action="store_true", help="reject 'python:' blocks instead of executing them at compile time"
        )
        parser.add_argument(
            "--no-symlink",
            action="store_true",
            help="refuse to follow symlinked directories or read symlinked source files",
        )
        parser.add_argument(
            "--safe",
            action="store_true",
            help="safely compile a datapack if you do not trust the author",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="test compile without writing any files to disk",
        )
        args = parser.parse_args(argv)
        self.set_options(
            CompilerOptions(
                no_header=args.no_header,
                no_python=args.no_python or args.safe,
                no_symlink=args.no_symlink or args.safe,
                verify_before_delete=args.safe,
                dry_run=args.dry_run,
            )
        )

    def get_no_header(self) -> bool:
        return self._options.no_header

    def get_no_python(self) -> bool:
        return self._options.no_python

    def get_no_symlink(self) -> bool:
        return self._options.no_symlink

    def get_verify_before_delete(self) -> bool:
        return self._options.verify_before_delete

    def get_dry_run(self) -> bool:
        return self._options.dry_run

    # Called from any compile/write thread; thread-safe.
    def log_error(self, error: BLError) -> None:
        with self._lock:
            self._errors.append(error)

    def get_errors(self) -> list[BLError]:
        with self._lock:
            return list(self._errors)

    def tick_discover_source_file(self, local_path: str) -> None:
        pass

    def tick_read_source_file(self, local_path: str) -> None:
        pass

    def tick_discover_output_file(self, filepath: str) -> None:
        pass

    def tick_complete_output_file_compile(self, filepath: str) -> None:
        pass

    def tick_write_output_file(self, filepath: str) -> None:
        pass

    # Prints every held error (fatal first) in whatever way TUI currently sees fit.
    def finish(self) -> None:
        errors = self.get_errors()
        fatal = [e for e in errors if isinstance(e, BLFatalError)]
        other = [e for e in errors if not isinstance(e, BLFatalError)]
        for error in fatal + other:
            print(f"{type(error).__name__}: {error}", file=sys.stderr)


# Owns pack.mcmeta/manifest state, discovery, both thread pools, and every datapack-level
# collection (compiled files, load/tick functions, source hashes/outputs, needs_recompile).
class Orchestration:
    def __init__(self) -> None:
        self._reset_state()

    def _reset_state(self) -> None:
        self._pack_name: str = ""
        self._pack_format: int | None = None
        self._previous: _Manifest = _Manifest(sources={}, load=frozenset(), tick=frozenset())
        self._files: set[str] = set()
        self._load_functions: set[str] = set()
        self._tick_functions: set[str] = set()
        self._source_hashes: dict[str, str | None] = {}
        self._source_sizes: dict[str, int] = {}
        self._source_outputs: dict[str, set[str]] = {}
        self._needs_recompile: set[str] = set()
        self._write_executor = ThreadPoolExecutor(max_workers=_FILE_WRITE_WORKERS_COUNT)

    # --- pack-level getters ---
    def get_pack_name(self) -> str:
        return self._pack_name

    def get_pack_format(self) -> int | None:
        return self._pack_format

    def get_files(self) -> frozenset[str]:
        return frozenset(self._files)

    def get_load_functions(self) -> frozenset[str]:
        return frozenset(self._load_functions)

    def get_tick_functions(self) -> frozenset[str]:
        return frozenset(self._tick_functions)

    # The previous run's record for this source, if any. None means never compiled before (or
    # its manifest entry was dropped/corrupt) -- Compile treats that like any other cache miss.
    def get_previous_entry(self, local_path: str) -> _ManifestEntry | None:
        return self._previous.sources.get(local_path)

    # --- bookkeeping, called by Compile ---
    def record_source(self, local_path: str, content_hash: str | None, content_size: int) -> None:
        self._source_hashes[local_path] = content_hash
        self._source_sizes[local_path] = content_size
        self._source_outputs.setdefault(local_path, set())

    def mark_needs_recompile(self, local_path: str) -> None:
        self._needs_recompile.add(local_path)

    # Attribute, log, and force a recompile of `local_path` next run. The shared shape of every
    # recoverable failure tied to a source (bad output path, write/delete failure, compile error).
    def report_error(self, local_path: str, error: BLError) -> None:
        error.filename = local_path
        tui.log_error(error)
        self.mark_needs_recompile(local_path)

    # Cache-hit path: carries a hash-unchanged source's previous outputs forward.
    def reuse_previous_outputs(self, local_path: str) -> None:
        entry = self._previous.sources.get(local_path)
        if entry is None:
            return
        for output in entry.outputs:
            self._files.add(output)
            self._source_outputs.setdefault(local_path, set()).add(output)
            function_id = self._function_id(output)
            if function_id in self._previous.load:
                self.add_load_function(output)
            if function_id in self._previous.tick:
                self.add_tick_function(output)

    def add_load_function(self, function_output_filepath: str) -> None:
        self._load_functions.add(function_output_filepath)

    def add_tick_function(self, function_output_filepath: str) -> None:
        self._tick_functions.add(function_output_filepath)

    # Validates namespace containment, then writes (for real) or simulates (dry-run) the file.
    def write_output_file(
        self, filepath: str, contents: str, function_def_line: _Line, local_path: str, namespace: str
    ) -> None:
        expected_root = os.path.normpath(f"data/{namespace}/function")
        normalized = os.path.normpath(filepath)
        if normalized != expected_root and not normalized.startswith(expected_root + os.sep):
            err = BLFileError(f"Output path '{filepath}' escapes namespace '{namespace}'.", function_def_line)
            self.report_error(local_path, err)
            return
        if tui.get_dry_run():
            self._files.add(filepath)
            self._source_outputs.setdefault(local_path, set()).add(filepath)
            tui.tick_write_output_file(filepath)
            return
        self._write_executor.submit(self._persist_file, filepath, contents, function_def_line, local_path)

    # Write one compiled file's bytes to disk.
    @staticmethod
    def _write_bytes_to_disk(filepath: str, contents: str) -> None:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "x", encoding="utf-8") as f:
            f.write(contents)

    def _persist_file(self, filepath: str, contents: str, function_def_line: _Line, local_path: str) -> None:
        try:
            # Called on the class, not `self`: a test patching this staticmethod with a plain
            # function would otherwise have it bound as an instance method via `self.`.
            Orchestration._write_bytes_to_disk(filepath, contents)
        except FileExistsError:
            err = BLFileError(f"Another function already compiles to '{filepath}'.", function_def_line)
            self.report_error(local_path, err)
            return
        except OSError as ose:
            err = BLFileError(f"Failed to write '{filepath}': {ose.strerror}.", function_def_line)
            self.report_error(local_path, err)
            return
        # Mutated from many write-pool threads; relies on the GIL for these single-op updates.
        self._files.add(filepath)
        self._source_outputs.setdefault(local_path, set()).add(filepath)
        tui.tick_write_output_file(filepath)

    def wait_for_writes(self) -> None:
        self._write_executor.shutdown(wait=True)

    # Delete one stale output file. Under verify_before_delete (and unless no_header), refuses to
    # delete anything missing the Blocklight header, since the manifest could be stale or wrong.
    def delete_stale_output(self, filepath: str, local_path: str) -> None:
        if not os.path.isfile(filepath):
            return
        if tui.get_verify_before_delete() and not tui.get_no_header():
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read()
            except OSError as err:
                error = BLFileError(f"Failed to verify '{filepath}' before deleting: {err.strerror}.")
                self.report_error(local_path, error)
                return
            if _HEADER_MARKER not in content:
                error = BLFileError(f"Refusing to delete '{filepath}': missing the Blocklight header.")
                self.report_error(local_path, error)
                return
        try:
            os.remove(filepath)
        except OSError as err:
            error = BLFileError(f"Failed to delete stale file '{filepath}': {err.strerror}.")
            self.report_error(local_path, error)

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

        if isinstance(value, list):
            numeric_items = [item for item in cast(list[object], value) if isinstance(item, (int, float))]
            value = min(numeric_items) if numeric_items else None

        if not isinstance(value, int | float):
            tui.log_error(
                BLSyntaxError("pack.mcmeta must declare 'min_format', 'pack_format', or 'supported_formats'.")
            )
            return None
        return int(value)  # truncates a major.minor string to major int

    @staticmethod
    def _str_set(value: object) -> frozenset[str]:
        if not isinstance(value, list):
            return frozenset()
        return frozenset(item for item in cast(list[object], value) if isinstance(item, str))

    # Convert a compiled output filepath ("data/<ns>/function/<rest>.mcfunction") to its function
    # id ("<ns>:<rest>"), e.g. "data/bl_example/function/functions/hello_load.mcfunction" becomes
    # "bl_example:functions/hello_load".
    @staticmethod
    def _function_id(filepath: str) -> str:
        _data, namespace, _function, *rest = filepath.split("/")
        return f"{namespace}:{'/'.join(rest).removesuffix('.mcfunction')}"

    # Load the previous run's manifest, if any. A missing or corrupt manifest is treated as empty.
    def _read_manifest(self) -> _Manifest:
        empty = _Manifest(sources={}, load=frozenset(), tick=frozenset())
        try:
            with open(_MANIFEST_FILENAME, encoding="utf-8") as f:
                raw: object = json.load(f)
        except (OSError, json.JSONDecodeError):
            return empty
        if not isinstance(raw, dict):
            return empty
        raw_dict = cast(dict[str, object], raw)

        sources: dict[str, _ManifestEntry] = {}
        sources_raw = raw_dict.get("sources")
        if isinstance(sources_raw, dict):
            for local_path, value in cast(dict[str, object], sources_raw).items():
                if not isinstance(value, dict):
                    continue
                entry = cast(dict[str, object], value)
                source_hash = entry.get("source_hash")
                if source_hash is not None and not isinstance(source_hash, str):
                    continue
                source_size = entry.get("source_size")
                sources[local_path] = _ManifestEntry(
                    source_hash=source_hash,
                    source_size=source_size if isinstance(source_size, int) else None,
                    outputs=self._str_set(entry.get("outputs")),
                    needs_recompile=bool(entry.get("needs_recompile")),
                )
        return _Manifest(
            sources=sources, load=self._str_set(raw_dict.get("load")), tick=self._str_set(raw_dict.get("tick"))
        )

    # Persist this run's manifest: pack-wide load/tick function ids, plus each compiled source's
    # content hash and size, its outputs, and whether it must always be recompiled next run.
    def _write_manifest(self) -> None:
        manifest = {
            "load": sorted(self._function_id(output) for output in self._load_functions),
            "tick": sorted(self._function_id(output) for output in self._tick_functions),
            "sources": {
                local_path: {
                    "source_hash": content_hash,
                    "source_size": self._source_sizes[local_path],
                    "outputs": sorted(self._source_outputs.get(local_path, set())),
                    "needs_recompile": local_path in self._needs_recompile,
                }
                for local_path, content_hash in self._source_hashes.items()
            },
        }
        with open(_MANIFEST_FILENAME, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)

    # Yield .bl paths under blocklight_dir. With no_symlink, refuses to follow symlinked
    # directories or read symlinked files, logging a recoverable error for each one skipped.
    def _iter_bl_files(self, blocklight_dir: str) -> Iterator[str]:
        no_symlink = tui.get_no_symlink()
        for root, dirs, files in os.walk(blocklight_dir, followlinks=not no_symlink):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            if no_symlink:
                kept_dirs: list[str] = []
                for d in dirs:
                    full = os.path.join(root, d)
                    if os.path.islink(full):
                        tui.log_error(
                            BLSyntaxError(f"Refusing to follow symlinked directory '{full}' (--no-symlink is set).")
                        )
                    else:
                        kept_dirs.append(d)
                dirs[:] = kept_dirs
            # A directory literally named "*.bl" is a candidate too; it fails naturally on open().
            for name in [*files, *(d for d in dirs if d.endswith(".bl"))]:
                if name.startswith(".") or not name.endswith(".bl"):
                    continue
                path = os.path.join(root, name)
                if no_symlink and os.path.islink(path):
                    tui.log_error(
                        BLSyntaxError(f"Refusing to read symlinked source file '{path}' (--no-symlink is set).")
                    )
                    continue
                yield path

    # The one hard precondition for running blocklight at all: a pack.mcmeta in the current
    # directory. Quits the whole program (not just this compile run) if it's missing or unparseable.
    @staticmethod
    def _load_pack_meta() -> dict[str, object]:
        if not os.path.isfile("pack.mcmeta"):
            raise SystemExit("No pack.mcmeta found in the current directory.")
        with open("pack.mcmeta", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as err:
                raise SystemExit(f"pack.mcmeta is not valid JSON: {err}") from err

    # Locate pack.mcmeta and every .bl file under data/<namespace>/blocklight/, compiling each
    # concurrently, then write the manifest.
    def run(self) -> None:
        self._reset_state()

        pack_meta = self._load_pack_meta()
        self._pack_format = self._read_pack_format(pack_meta)
        self._pack_name = os.path.basename(os.getcwd())
        if set(self._pack_name) - _FUNCTION_NAME_CHARS:
            tui.log_error(
                BLSyntaxError(f"The datapack directory name '{self._pack_name}' may only use a-z, 0-9, '_' and '-'.")
            )

        if not os.path.isdir("data"):
            return

        self._previous = self._read_manifest()

        discovered: dict[str, str] = {}  # local_path -> namespace
        for namespace in sorted(os.listdir("data")):
            namespace_dir = os.path.join("data", namespace)
            if not os.path.isdir(namespace_dir):
                continue
            if set(namespace) - _FUNCTION_NAME_CHARS:
                tui.log_error(BLSyntaxError(f"The namespace '{namespace}' may only use a-z, 0-9, '_' and '-'."))
                continue
            blocklight_dir = os.path.join(namespace_dir, "blocklight")
            for local_path in self._iter_bl_files(blocklight_dir):
                discovered[local_path] = namespace

        # Sources present in the last manifest but not found this run: their outputs are orphaned.
        if not tui.get_dry_run():
            for local_path in sorted(set(self._previous.sources) - set(discovered)):
                for output in self._previous.sources[local_path].outputs:
                    self.delete_stale_output(output, local_path)

        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(Compile(local_path, namespace).run): local_path
                for local_path, namespace in discovered.items()
            }
            for future, local_path in futures.items():
                try:
                    future.result()
                except Exception as err:  # a bug or unanticipated failure must not vanish silently
                    self.report_error(local_path, BLFileError(f"Unexpected error while compiling: {err}"))

        self.wait_for_writes()
        if not tui.get_dry_run():
            self._write_manifest()


# One instance per source file, constructed and run inside Orchestration's discovery pool.
class Compile:
    def __init__(self, local_path: str, namespace: str) -> None:
        self.local_path = local_path
        self.namespace = namespace

    # Reads the source file, compares its size (and, unless that alone proves a change, its hash
    # and needs_recompile flag) against the previous manifest, and either reuses the previous
    # outputs or deletes them and recompiles.
    def run(self) -> None:
        tui.tick_discover_source_file(self.local_path)
        try:
            with open(self.local_path, encoding="utf-8") as f:
                source = f.read()
                content_size = os.fstat(f.fileno()).st_size
        except (OSError, UnicodeDecodeError) as err:
            # No entry gets recorded below, so this source is simply absent from the next
            # manifest and gets a fresh attempt next run regardless of mark_needs_recompile.
            detail = err.strerror if isinstance(err, OSError) and err.strerror else str(err)
            error = BLFileError(f"Failed to read '{self.local_path}': {detail}.")
            error.filename = self.local_path
            tui.log_error(error)
            return
        tui.tick_read_source_file(self.local_path)

        previous_entry = orchestration.get_previous_entry(self.local_path)
        # A recorded size that doesn't match already proves the content changed; skip hashing
        # entirely in that case. A missing size (e.g. from an older manifest) just falls back to
        # always hashing, same as before size tracking existed.
        size_definitely_changed = (
            previous_entry is not None
            and previous_entry.source_size is not None
            and previous_entry.source_size != content_size
        )
        content_hash = None if size_definitely_changed else hashlib.sha256(source.encode("utf-8")).hexdigest()
        orchestration.record_source(self.local_path, content_hash, content_size)

        if (
            previous_entry is not None
            and not size_definitely_changed
            and content_hash == previous_entry.source_hash
            and not previous_entry.needs_recompile
        ):
            orchestration.reuse_previous_outputs(self.local_path)
            return

        if previous_entry is not None and not tui.get_dry_run():
            for output in previous_entry.outputs:
                orchestration.delete_stale_output(output, self.local_path)

        sf = SourceFile(
            local_path=self.local_path,
            source=source,
            pack_name=orchestration.get_pack_name(),
            pack_format=orchestration.get_pack_format(),
            namespace=self.namespace,
        )
        self.compile(sf)

    # Compile every function in `sf`, isolating recoverable errors to the function that raised them.
    def compile(self, sf: SourceFile) -> None:
        try:
            for function_lines in self._iter_spans(sf.source_lines, sf.single_indent, 0):
                try:
                    self._compile_function(sf, function_lines)
                except BLNonFatalError as err:
                    orchestration.report_error(sf.local_path, err)
        except BLFatalError as err:
            orchestration.report_error(sf.local_path, err)

    # Yield lists of _Line objects for each command / block encountered at provided depth.
    @staticmethod
    def _iter_spans(lines: list[_Line], single_indent: str, depth: int) -> Iterator[list[_Line]]:
        indent = "" if depth == 0 else single_indent * depth
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

    # Validate a function header and compile its body to an mcfunction file.
    def _compile_function(self, sf: SourceFile, lines: list[_Line]) -> None:
        header = lines[0]
        header_split = header.text.split("function ")
        if len(header_split) <= 1:
            raise BLSyntaxError(
                "This is being interpreted as a function header but does not declare a function. "
                "Double-check indentation.",
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
            raise BLSyntaxError(
                "This function definition does not declare a function name (e.g. 'function foo:')", header
            )
        if sorted(set(function_name) - _FUNCTION_NAME_CHARS):
            raise BLSyntaxError("Function names may only use a-z, 0-9, '_' and '-'", header)

        if len(lines) == 1:  # header only: empty function produces no output
            return

        _data, namespace, _src_root, *subdirs, source_file = sf.local_path.split("/")  # /data/<ns>/blocklight/*/f.bl
        function_dir = f"data/{namespace}/function"
        if "root" in seen_keywords:
            output_filepath = f"{function_dir}/{function_name}.mcfunction"
        else:
            nested_dir = "/".join([*subdirs, source_file.removesuffix(".bl")])
            output_filepath = f"{function_dir}/{nested_dir}/{function_name}.mcfunction"
        tui.tick_discover_output_file(output_filepath)

        block_out = _BlockOutput()
        if not tui.get_no_header():
            block_out.lines.append(f"# {_HEADER_MARKER} {_BL_VERSION} (https://github.com/qcjames53/blocklight)")
            block_out.lines.append(
                "# Changes saved to this file will not persist. Please modify the source file instead:"
            )
            block_out.lines.append(f"#     `{sf.local_path}`")
        self._compile_lines(_BlockInput(sf, function_name), block_out, lines[1:], 1)
        orchestration.write_output_file(output_filepath, "\n".join(block_out.lines), header, sf.local_path, namespace)
        tui.tick_complete_output_file_compile(output_filepath)

        if "load" in seen_keywords:
            orchestration.add_load_function(output_filepath)
        if "tick" in seen_keywords:
            orchestration.add_tick_function(output_filepath)

    # Compile the statements in `lines` at `depth`, appending commands and recording block
    # properties onto `block_out`.
    def _compile_lines(self, block_in: _BlockInput, block_out: _BlockOutput, lines: list[_Line], depth: int) -> None:
        for span in self._iter_spans(lines, block_in.sf.single_indent, depth):
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
                    if tui.get_no_python():
                        raise BLSyntaxError(
                            "This 'python:' block is not allowed because python blocks are disabled (--no-python).",
                            line,
                        )
                    if text != "python:":
                        raise BLSyntaxError("A 'python:' block header takes no arguments.", line)
                    orchestration.mark_needs_recompile(block_in.sf.local_path)  # non-deterministic: always recompile
                    self._compile_lines(block_in, block_out, self._run_python_block(block_in, span, depth), depth)
                else:
                    # TODO create block handling here
                    raise BLSyntaxError(f"The '{keyword}' block is not yet implemented.", line)
            elif has_body:
                raise BLSyntaxError("Only block keywords may begin an indented block.", span[1])

            # Handle regular commands
            else:
                self._append_command(block_out, line)

    # Record one command line's macros and early-return potential, then add it to the block's output.
    @staticmethod
    def _append_command(block_out: _BlockOutput, line: _Line) -> None:
        text = line.text.lstrip()  # right side already stripped

        if not block_out.can_return:  # cheap early-return detection; occasional false positives are acceptable
            loc = text.find("return")
            if loc != -1 and (loc == 0 or text[loc - 1] == " ") and (len(text) <= loc + 6 or text[loc + 6] == " "):
                block_out.can_return = True

        has_dollar = text.startswith("$")
        uses_macro = False
        if "$(" in text:
            for macro_name in Compile._iter_macro_names(line):
                block_out.macros.add(macro_name)
                uses_macro = True
        if not uses_macro and has_dollar:
            raise BLSyntaxError("This line begins with '$' but declares no macro.", line)
        block_out.lines.append("$" + text if uses_macro and not has_dollar else text)

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
            if set(name) - _MACRO_NAME_CHARS:
                raise BLSyntaxError(f"Macro names may only use a-z, A-Z, 0-9 and '_': '$({name})'", line)
            yield name
            search_from = name_end + 1

    # Execute a python: block and return the lines it emits re-indented to `depth` and anchored at the block header.
    @staticmethod
    def _run_python_block(block_in: _BlockInput, span: list[_Line], depth: int) -> list[_Line]:
        sf = block_in.sf
        head = span[0]
        body = textwrap.dedent("\n".join(ln.text for ln in span[1:]))

        emitted: list[str] = []

        def emit(command: object) -> None:
            emitted.append(str(command))

        scope: dict[str, object] = {"emit": emit, "bl": _PythonBlockContext(block_in)}
        try:
            exec(compile(body, f"{sf.local_path}:{head.lineno} python: block", "exec"), scope)
        except SyntaxError as err:
            raise BLPythonError(f"invalid Python in this block: {err.msg}", head) from err
        except Exception as err:
            raise BLPythonError(f"this block raised {type(err).__name__}: {err}", head) from err

        prefix = (sf.single_indent or "") * depth
        return [
            _Line(prefix + part, head.lineno)
            for command in emitted
            for part in str(command).split("\n")
            if part.strip()
        ]


def main() -> None:
    if sys.version_info < _MIN_PYTHON:
        required = ".".join(str(part) for part in _MIN_PYTHON)
        raise SystemExit(f"Blocklight {_BL_VERSION} requires Python {required} or newer.")

    tui.parse_args()
    print("Compiling datapack...")
    orchestration.run()
    tui.finish()


tui = TUI()
orchestration = Orchestration()


# Replaces both globals with fresh instances. Mainly for test isolation between compile runs.
def reset_globals() -> None:
    global tui, orchestration
    tui = TUI()
    orchestration = Orchestration()


if __name__ == "__main__":
    main()
