# Helpers for unit test suite

import contextlib
import io
import os
import tempfile
import unittest.mock
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import blocklight

DEFAULT_OPTIONS = blocklight.CompilerOptions()


# A snapshot of everything a test typically wants to assert on, taken right after a compile.
class Result(NamedTuple):
    errors: list[blocklight.BLError]
    file_contents: dict[str, str]
    raw_file_contents: dict[str, str]
    files: frozenset[str]
    load_functions: frozenset[str]
    tick_functions: frozenset[str]


def build_lines(source: str) -> list[blocklight._Line]:  # pyright: ignore[reportPrivateUsage]
    return list(blocklight.SourceFile._iter_clean_lines(enumerate(source.split("\n"), start=1)))  # pyright: ignore[reportPrivateUsage]


# Builds a SourceFile from an in-memory string instead of a real file: SourceFile.__post_init__
# always reads local_path off disk, so this stubs `open` just for that one read.
def make_source_file(local_path: str, source: str, namespace: str | None = None) -> blocklight.SourceFile:
    def fake_open(filepath: str, mode: str = "r", *args: object, **kwargs: object) -> io.StringIO:
        assert filepath == local_path and mode == "r"
        return io.StringIO(source)

    with unittest.mock.patch("blocklight.open", fake_open, create=True):
        return blocklight.SourceFile(local_path=local_path, namespace=namespace)  # pyright: ignore[reportArgumentType]


# Strips the 3-line Blocklight header (always present on top-level function output) if present,
# so tests can assert on clean body content regardless of it.
def strip_header(content: str) -> str:
    lines = content.split("\n")
    header_lines = blocklight._HEADER_TEXT  # pyright: ignore[reportPrivateUsage]
    if (
        len(lines) >= 3
        and lines[0] == header_lines[0]
        and lines[1] == header_lines[1]
        and lines[2].startswith("#     `")
    ):
        return "\n".join(lines[3:])
    return content


def _snapshot(file_contents: dict[str, str] | None = None) -> Result:
    raw = dict(file_contents) if file_contents is not None else {}
    return Result(
        errors=blocklight.tui.get_errors(),
        file_contents={path: strip_header(content) for path, content in raw.items()},
        raw_file_contents=raw,
        files=blocklight.orchestration.get_files(),
        load_functions=blocklight.orchestration.get_load_functions(),
        tick_functions=blocklight.orchestration.get_tick_functions(),
    )


# Chdir into a fresh, empty directory for the duration of the block. Restores the original cwd
# and deletes the directory (and anything compiled into it) on exit.
@contextlib.contextmanager
def scratch_dir() -> Generator[None, None, None]:
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.chdir(tmp_dir)
        try:
            yield
        finally:
            os.chdir(original_cwd)


# A stand-in for the file object `open(path, "x")` returns, collecting what gets written into
# `written` instead of touching the filesystem.
class _FakeFile:
    def __init__(self, filepath: str, written: dict[str, str]) -> None:
        self._filepath = filepath
        self._written = written

    def __enter__(self) -> "_FakeFile":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def write(self, contents: str) -> None:
        self._written[self._filepath] = self._written.get(self._filepath, "") + contents


# Stubs the lowest-level disk write so a test can inspect compiled output without touching the
# filesystem. Patches `open` and `os.makedirs` as seen from inside blocklight.py (rather than
# stubbing Orchestration._persist_file itself), so that method's real exclusive-create and
# collision-handling logic still gets exercised. Mimics `open(path, "x")`'s exclusive-create
# semantics (a repeat path raises FileExistsError).
@contextlib.contextmanager
def stub_disk_writes() -> Generator[dict[str, str], None, None]:
    written: dict[str, str] = {}

    def fake_open(filepath: str, mode: str = "r", *args: object, **kwargs: object) -> _FakeFile:
        assert mode == "x", f"stub_disk_writes only expects exclusive-create opens, got mode={mode!r}"
        if filepath in written:
            raise FileExistsError(f"'{filepath}' already exists")
        written[filepath] = ""
        return _FakeFile(filepath, written)

    with (
        unittest.mock.patch("blocklight.os.makedirs"),
        unittest.mock.patch("blocklight.open", fake_open, create=True),
    ):
        yield written


# Fresh global TUI/Orchestration for test isolation, with a single-worker write pool so writes to
# colliding paths resolve in submission order instead of racing across threads.
def reset_for_test(options: blocklight.CompilerOptions = DEFAULT_OPTIONS) -> None:
    blocklight.reset_globals()
    blocklight.tui.set_options(options)
    blocklight.orchestration._write_executor = ThreadPoolExecutor(max_workers=1)  # pyright: ignore[reportPrivateUsage]


# Compile a single in-memory source string directly, bypassing disk discovery/manifest checks and
# (via stub_disk_writes) the filesystem entirely.
def compile_source(
    source: str,
    *,
    local_path: str = "data/pack/blocklight/main.bl",
    options: blocklight.CompilerOptions = DEFAULT_OPTIONS,
    pack_name: str | None = None,
    pack_format: int | None = None,
    namespace: str | None = None,
) -> Result:
    reset_for_test(options)
    if pack_name is not None:
        blocklight.orchestration._pack_name = pack_name  # pyright: ignore[reportPrivateUsage]
    if pack_format is not None:
        blocklight.orchestration._pack_format = pack_format  # pyright: ignore[reportPrivateUsage]
    compile_ = blocklight.Compile(local_path, local_path.split("/")[1])
    sf = make_source_file(local_path, source, namespace)
    with stub_disk_writes() as written:
        compile_.compile(sf)
        blocklight.orchestration.wait_for_writes()
    return _snapshot(written)


# Run a full discover-and-compile pass (pack.mcmeta + data/ discovery) in the current directory.
# Writes go to real disk: manifest/staleness tests depend on real persistence across runs.
def run_compile(options: blocklight.CompilerOptions = DEFAULT_OPTIONS) -> Result:
    blocklight.reset_globals()
    blocklight.tui.set_options(options)
    blocklight.orchestration.run()
    return _snapshot()
