"""Blocklight - A blazing fast mcfunction microcompiler"""

import argparse
import hashlib
import json
import os
import shutil
import string
import sys
import textwrap
import threading
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
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


# One line in source tracking original line number
class _Line(NamedTuple):
    text: str
    lineno: int


# One source file's properties stored in the manifest
class _ManifestSourceEntry(NamedTuple):
    source_hash: str
    outputs: frozenset[str]
    needs_recompile: bool


# Manifest file tracking facets of the previous compile
class _Manifest(NamedTuple):
    sources: dict[str, _ManifestSourceEntry]
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


# Source contents and metadata surrounding an input file. The caller has always already read and
# cleaned the lines by the time this gets built (see Compile._read_source), so it just takes them.
@dataclass
class SourceFile:
    local_path: str
    source_lines: list[_Line]
    namespace: str | None = None  # optional; surfaced to `python:` blocks as bl.NAMESPACE


# Compile-time options, owned and parsed by TUI.
@dataclass(frozen=True)
class CompilerOptions:
    no_header: bool = False  # Omit the "Compiled by Blocklight" header comment from each output file
    no_python: bool = False  # Throw an error on `python:` blocks instead of executing them
    no_symlink: bool = False  # Refuse to follow symlinked directories or read symlinked source files
    verify_before_delete: bool = False  # Before deleting a stale output, confirm it has the Blocklight header
    dry_run: bool = False  # Compile in-memory only; do not write any files to disk


# Read-only context threaded through the compilation of one block
@dataclass
class _BlockInput:
    sf: SourceFile
    source_function_name: str  # Name of the top-level function from the function def
    function_name: str  # Name of the output function this block will compile into


# Mutable accumulator built up while compiling one block.
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
        self.PACK_NAME = orchestration.get_pack_name()
        self.PACK_FORMAT = orchestration.get_pack_format()
        self.FUNCTION_NAME = block_in.source_function_name
        self.OUTPUT_FUNCTION_NAME = block_in.function_name
        self.BLOCKLIGHT_VERSION = _BL_VERSION


# Parses CLI args and drives user-facing progress UI
class TUI:
    _SPINNER_FRAMES = "|/-\\"
    _REDRAW_INTERVAL = 1 / 15

    def __init__(self) -> None:
        self._options = CompilerOptions()
        self._errors: list[BLError] = []
        self._lock = threading.Lock()  # guards _errors and the three tick counters below
        self._discovered = 0
        self._processed = 0
        self._written = 0
        self._start_time = 0.0
        self._render_lock = threading.Lock()  # serializes all stderr writes (footer draws + print)
        self._footer_thread: threading.Thread | None = None
        self._footer_stop = threading.Event()
        self._footer_active = False
        self._footer_len = 0  # length of the last-drawn footer, so redraws fully overwrite it
        self._spinner_index = 0

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

    # Thread safe
    def log_error(self, error: BLError) -> None:
        with self._lock:
            self._errors.append(error)
        self.print(f"{type(error).__name__}: {error}")

    # Thread safe
    def get_errors(self) -> list[BLError]:
        with self._lock:
            return list(self._errors)

    # Thread safe
    def tick_discovered(self) -> None:
        with self._lock:
            self._discovered += 1

    # Thread safe
    def tick_processed(self) -> None:
        with self._lock:
            self._processed += 1

    # Thread safe
    def tick_written(self) -> None:
        with self._lock:
            self._written += 1

    # Starts the compile clock and the live footer (if tty).
    def start(self) -> None:
        self._start_time = time.monotonic()
        if not sys.stderr.isatty():
            return
        self._footer_active = True
        self._footer_stop.clear()

        def render_loop() -> None:
            while True:
                with self._render_lock:
                    self._draw_footer()
                if self._footer_stop.wait(self._REDRAW_INTERVAL):
                    return

        self._footer_thread = threading.Thread(target=render_loop, daemon=True)
        self._footer_thread.start()

    def _footer_text(self) -> str:
        with self._lock:
            discovered, processed, written = self._discovered, self._processed, self._written
        spinner = self._SPINNER_FRAMES[self._spinner_index % len(self._SPINNER_FRAMES)]
        self._spinner_index += 1
        elapsed = time.monotonic() - self._start_time
        left = f"{spinner} ({discovered} discovered, {processed} processed, {written} written)"
        right = f"{elapsed:.3f}s "
        width = shutil.get_terminal_size(fallback=(80, 24)).columns
        gap = max(1, width - len(left) - len(right))
        return f"{left}{' ' * gap}{right}"[:width]

    # Caller must hold _render_lock.
    def _draw_footer(self) -> None:
        line = self._footer_text()
        pad = max(0, self._footer_len - len(line))
        sys.stderr.write("\r" + line + (" " * pad))
        sys.stderr.flush()
        self._footer_len = len(line)

    # Prints a line of output, keeping the footer pinned to the bottom line.
    def print(self, message: str) -> None:
        with self._render_lock:
            if self._footer_active:
                sys.stderr.write("\r" + (" " * self._footer_len) + "\r")
                sys.stderr.write(message + "\n")
                self._draw_footer()
            else:
                sys.stderr.write(message + "\n")
            sys.stderr.flush()

    # Stops the footer (if running) and prints the final summary
    def finish(self) -> None:
        if self._footer_active:
            self._footer_stop.set()
            if self._footer_thread is not None:
                self._footer_thread.join()
            self._footer_active = False
            with self._render_lock:
                sys.stderr.write("\r" + (" " * self._footer_len) + "\r")
                sys.stderr.flush()
                self._footer_len = 0
        elapsed = time.monotonic() - self._start_time
        with self._lock:
            written, discovered = self._written, self._discovered
            had_errors = bool(self._errors)
        summary = (
            f"Compiled {orchestration.get_pack_name()} in {elapsed:.3f} seconds. [{written} / {discovered}] output"
        )
        if had_errors:
            summary += " (see above for errors)"
        self.print(summary)


# Owns pack.mcmeta/manifest state, discovery, both thread pools, and every datapack-level
# collection (compiled files, load/tick functions, source hashes/outputs, needs_recompile).
class Orchestration:
    def __init__(self) -> None:
        self._pack_name: str = ""
        self._pack_format: int | None = None
        self._previous: _Manifest = _Manifest(sources={}, load=frozenset(), tick=frozenset())
        self._files: set[str] = set()
        self._load_functions: set[str] = set()
        self._tick_functions: set[str] = set()
        self._source_hashes: dict[str, str] = {}
        self._source_outputs: dict[str, set[str]] = {}
        self._needs_recompile: set[str] = set()
        self._write_executor = ThreadPoolExecutor(max_workers=_FILE_WRITE_WORKERS_COUNT)

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
    def get_previous_entry(self, local_path: str) -> _ManifestSourceEntry | None:
        return self._previous.sources.get(local_path)

    def record_source(self, local_path: str, content_hash: str) -> None:
        self._source_hashes[local_path] = content_hash
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
            tui.tick_discovered()
            tui.tick_processed()
            tui.tick_written()
            function_id = self._function_id(output)
            if function_id in self._previous.load:
                self.add_load_function(output)
            if function_id in self._previous.tick:
                self.add_tick_function(output)

    def add_load_function(self, function_output_filepath: str) -> None:
        self._load_functions.add(function_output_filepath)

    def add_tick_function(self, function_output_filepath: str) -> None:
        self._tick_functions.add(function_output_filepath)

    # Validates namespace containment, then writes the file.
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
            tui.tick_written()
            return
        self._write_executor.submit(self._persist_file, filepath, contents, function_def_line, local_path)

    def _persist_file(self, filepath: str, contents: str, function_def_line: _Line, local_path: str) -> None:
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "x", encoding="utf-8") as f:
                f.write(contents)
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
        tui.tick_written()

    def wait_for_writes(self) -> None:
        self._write_executor.shutdown(wait=True)

    # Delete one stale output file.
    # Does not delete anything missing the Blocklight header, since the manifest could be stale or wrong.
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

    # Convert "data/<namespace>/function/<filepath_remainder>.mcfunction" to "<namespace>:<filepath_remainder>"
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

        sources: dict[str, _ManifestSourceEntry] = {}
        sources_raw = raw_dict.get("sources")
        if isinstance(sources_raw, dict):
            for local_path, value in cast(dict[str, object], sources_raw).items():
                if not isinstance(value, dict):
                    continue
                entry = cast(dict[str, object], value)
                source_hash = str(entry.get("source_hash"))  # str cast needed for typing
                sources[local_path] = _ManifestSourceEntry(
                    source_hash=source_hash,
                    outputs=self._str_set(entry.get("outputs")),
                    needs_recompile=bool(entry.get("needs_recompile")),
                )
        return _Manifest(
            sources=sources, load=self._str_set(raw_dict.get("load")), tick=self._str_set(raw_dict.get("tick"))
        )

    # Persist this run's manifest (info on this compile)
    def _write_manifest(self) -> None:
        manifest = {
            "load": sorted(self._function_id(output) for output in self._load_functions),
            "tick": sorted(self._function_id(output) for output in self._tick_functions),
            "sources": {
                local_path: {
                    "source_hash": content_hash,
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
                if not name.endswith(".bl"):
                    continue
                path = os.path.join(root, name)
                if no_symlink and os.path.islink(path):
                    tui.log_error(
                        BLSyntaxError(f"Refusing to read symlinked source file '{path}' (--no-symlink is set).")
                    )
                    continue
                yield path

    # Locate pack.mcmeta and every .bl file under data/<namespace>/blocklight/, compiling each
    # concurrently, then write the manifest.
    def run(self) -> None:
        if not os.path.isfile("pack.mcmeta"):
            raise SystemExit("No pack.mcmeta found in the current directory.")
        with open("pack.mcmeta", encoding="utf-8") as f:
            try:
                pack_meta: dict[str, object] = json.load(f)
            except json.JSONDecodeError as err:
                raise SystemExit(f"pack.mcmeta is not valid JSON: {err}") from err

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

    # Opens and reads the source file, determines if compile is needed, then deletes old output and recompiles
    def run(self) -> None:
        tui.tick_discovered()
        try:
            with open(self.local_path, encoding="utf-8") as f:
                hasher = hashlib.sha256()
                source_lines: list[_Line] = []
                for line in self._iter_clean_lines(enumerate(f, start=1)):
                    hasher.update(line.text.encode("utf-8"))
                    hasher.update(b"\n")
                    source_lines.append(line)
                content_hash = hasher.hexdigest()
        except (OSError, UnicodeDecodeError) as err:
            # No entry gets recorded below, so this source is simply absent from the next
            # manifest and gets a fresh attempt next run regardless of mark_needs_recompile.
            detail = err.strerror if isinstance(err, OSError) and err.strerror else str(err)
            error = BLFileError(f"Failed to read '{self.local_path}': {detail}.")
            error.filename = self.local_path
            tui.log_error(error)
            return
        tui.tick_processed()

        previous_entry = orchestration.get_previous_entry(self.local_path)
        orchestration.record_source(self.local_path, content_hash)

        if (
            previous_entry is not None
            and content_hash == previous_entry.source_hash
            and not previous_entry.needs_recompile
        ):
            orchestration.reuse_previous_outputs(self.local_path)
            tui.tick_written()
            return

        if previous_entry is not None and not tui.get_dry_run():
            for output in previous_entry.outputs:
                orchestration.delete_stale_output(output, self.local_path)

        sf = SourceFile(local_path=self.local_path, source_lines=source_lines, namespace=self.namespace)
        self.compile(sf)
        tui.tick_written()

    # Cleans lines from any (line number, raw text) source. A continued line is only yielded
    # once a non-continuing line ends it.
    @staticmethod
    def _iter_clean_lines(numbered_lines: Iterable[tuple[int, str]]) -> Iterator[_Line]:
        pending: _Line | None = None
        for line_number, raw_line in numbered_lines:
            line = raw_line.rstrip()
            lstrip_line = line.lstrip()

            # Strip comment and whitespace lines
            if lstrip_line.startswith("#") or len(lstrip_line) == 0:
                continue

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

    # Compile every function in `sf`, isolating recoverable errors to the function that raised them.
    def compile(self, sf: SourceFile) -> None:
        try:
            for function_lines in self._iter_spans(sf.source_lines, self._single_indent(sf), 0):
                try:
                    self._compile_function(sf, function_lines)
                except BLNonFatalError as err:
                    orchestration.report_error(sf.local_path, err)
        except BLFatalError as err:
            orchestration.report_error(sf.local_path, err)

    @staticmethod
    def _single_indent(sf: SourceFile) -> str:
        for line in sf.source_lines:
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

    # Convert a minecraft-consumable namespaced function name 
    # "<namespace>:<path/without/extension>" -> "data/<namespace>/function/<path>.mcfunction".
    @staticmethod
    def _function_filepath(function_name: str) -> str:
        namespace, path = function_name.split(":", 1)
        return f"data/{namespace}/function/{path}.mcfunction"

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
        if "root" in seen_keywords:
            function_path = function_name
        else:
            function_path = "/".join([*subdirs, source_file.removesuffix(".bl"), function_name])
        block_in = _BlockInput(sf, function_name, f"{namespace}:{function_path}")
        output_filepath = self._function_filepath(block_in.function_name)
        tui.tick_discovered()

        block_out = _BlockOutput()
        if not tui.get_no_header():
            block_out.lines.append(f"# {_HEADER_MARKER} {_BL_VERSION} (https://github.com/qcjames53/blocklight)")
            block_out.lines.append(
                "# Changes saved to this file will not persist. Please modify the source file instead:"
            )
            block_out.lines.append(f"#     `{sf.local_path}`")
        self._compile_lines(block_in, block_out, lines[1:], 1)
        orchestration.write_output_file(output_filepath, "\n".join(block_out.lines), header, sf.local_path, namespace)
        tui.tick_processed()

        if "load" in seen_keywords:
            orchestration.add_load_function(output_filepath)
        if "tick" in seen_keywords:
            orchestration.add_tick_function(output_filepath)

    # Compile the top-level commands in `lines` (at `depth`) + recursively compile child blocks
    def _compile_lines(self, block_in: _BlockInput, block_out: _BlockOutput, lines: list[_Line], depth: int) -> None:
        counts: dict[str, int] = {}
        for span in self._iter_spans(lines, self._single_indent(block_in.sf), depth):
            line = span[0]
            text = line.text.lstrip()  # right is already stripped
            keyword = text.split(maxsplit=1)[0].removesuffix(":")  # 'python:' / 'else:' carry the colon; others don't
            args = text.partition(" ")[2].removesuffix(":")
            has_keyword = keyword in _BLOCK_KEYWORDS
            has_body = len(span) > 1

            # Handle block commands without body
            if has_keyword and not has_body:
                raise BLSyntaxError(f"This '{keyword}' block has no body.", line)

            # Handle block commands
            elif has_keyword:
                if not text.endswith(":"):
                    raise BLSyntaxError(f"'{keyword}' begins a block and must end with ':'.", line)

                match keyword:
                    case "python":
                        if args != "":
                            raise BLSyntaxError("'python:' blocks do not take arguments.", line)
                        # Execute python (if permitted) and run emitted lines through this method recursively
                        emitted = self._handle_python_block(block_in, span, depth)
                        self._compile_lines(block_in, block_out, emitted, depth)

                    case _ if keyword in _MODIFIER_BLOCK_KEYWORDS:
                        if args == "":
                            raise BLSyntaxError(f"'{keyword}' blocks require arguments.")
                        # Recursively compile this block into <current_function>_helper/<keyword>_<instance_of_this_keyword>.mcfunction
                        tui.tick_discovered()
                        keyword_count = counts.get(keyword, 0)
                        counts[keyword] = keyword_count + 1
                        child_function_name = f"{block_in.function_name}_helper/{keyword}_{keyword_count}"

                        new_block_in = _BlockInput(block_in.sf, block_in.source_function_name, child_function_name)
                        new_block_out = _BlockOutput()
                        self._compile_lines(new_block_in, new_block_out, span[1:], depth + 1)
                        tui.tick_processed()

                        orchestration.write_output_file(
                            self._function_filepath(child_function_name),
                            "\n".join(new_block_out.lines),
                            line,
                            block_in.sf.local_path,
                            child_function_name.split(":", 1)[0],
                        )

                        # Call the recursive block from this function
                        # TODO - respect returns and macros
                        modifier_command = f"execute {keyword} {args} run function {child_function_name}"
                        self._append_line_to_block_out(block_out, _Line(modifier_command, line.lineno))
                    case _:
                        raise BLSyntaxError(f"The '{keyword}' block is not yet implemented.", line)

            # Handle regular commands with body
            elif has_body:
                raise BLSyntaxError("Only block keywords may begin an indented block.", span[1])

            # Handle regular commands
            else:
                self._append_line_to_block_out(block_out, line)

    @staticmethod
    def _append_line_to_block_out(block_out: _BlockOutput, line: _Line) -> None:
        text = line.text.lstrip()
        # Detect if maybe this line contains a return command. False positives are acceptable.
        if not block_out.can_return:
            return_string_location = text.find("return")
            is_return_string_start_okay = return_string_location == 0 or text[return_string_location - 1] == " "
            is_return_string_end_okay = len(text) <= return_string_location + 6 or text[return_string_location + 6] == " "
            if return_string_location != -1 and is_return_string_start_okay and is_return_string_end_okay:
                block_out.can_return = True
        has_macro_dollar = text.startswith("$")
        uses_macros = False
        if "$(" in text:
            for macro_name in Compile._iter_macro_names(line):
                block_out.macros.add(macro_name)
                uses_macros = True
        if has_macro_dollar and not uses_macros:
            raise BLSyntaxError("This line begins with '$' but declares no macro.", line)
        block_out.lines.append("$" + text if not has_macro_dollar and uses_macros else text)


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
    def _handle_python_block(block_in: _BlockInput, span: list[_Line], depth: int) -> list[_Line]:
        sf = block_in.sf
        head = span[0]
        body = textwrap.dedent("\n".join(ln.text for ln in span[1:]))

        if tui.get_no_python():
            raise BLSyntaxError("This Python blocks is disabled due to your compile parameters.", head)
        orchestration.mark_needs_recompile(sf.local_path)
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

        prefix = Compile._single_indent(sf) * depth
        return [
            _Line(prefix + part, head.lineno)
            for command in emitted
            for part in str(command).split("\n")
            if part.strip()
        ]

    @staticmethod
    def _handle_modifier_block(block_in: _BlockInput, span: list[_Line], depth: int) -> list[_Line]:
        pass


def main() -> None:
    if sys.version_info < _MIN_PYTHON:
        required = ".".join(str(part) for part in _MIN_PYTHON)
        raise SystemExit(f"Blocklight {_BL_VERSION} requires Python {required} or newer.")

    tui.parse_args()
    tui.start()
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
