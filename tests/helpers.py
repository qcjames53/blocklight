# Helpers for unit test suite

import contextlib
import os
import tempfile
import unittest.mock
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import blocklight

NO_HEADER = blocklight.CompilerOptions(no_header=True)


# A snapshot of everything a test typically wants to assert on, taken right after a compile.
class Result(NamedTuple):
    errors: list[blocklight.BLError]
    file_contents: dict[str, str]
    files: frozenset[str]
    load_functions: frozenset[str]
    tick_functions: frozenset[str]


def _snapshot(file_contents: dict[str, str] | None = None) -> Result:
    return Result(
        errors=blocklight.tui.get_errors(),
        file_contents=dict(file_contents) if file_contents is not None else {},
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


# Stubs the lowest-level disk write so a test can inspect compiled output without touching the
# filesystem. Mimics `open(path, "x")`'s exclusive-create semantics (a repeat path raises
# FileExistsError), so real collision-handling code in Orchestration still gets exercised.
@contextlib.contextmanager
def stub_disk_writes() -> Generator[dict[str, str], None, None]:
    written: dict[str, str] = {}

    def fake_write(filepath: str, contents: str) -> None:
        if filepath in written:
            raise FileExistsError(f"'{filepath}' already exists")
        written[filepath] = contents

    with unittest.mock.patch("blocklight.Orchestration._write_bytes_to_disk", fake_write):
        yield written


# Fresh global TUI/Orchestration for test isolation, with a single-worker write pool so writes to
# colliding paths resolve in submission order instead of racing across threads.
def reset_for_test(options: blocklight.CompilerOptions = NO_HEADER) -> None:
    blocklight.reset_globals()
    blocklight.tui.set_options(options)
    blocklight.orchestration._write_executor = ThreadPoolExecutor(max_workers=1)  # pyright: ignore[reportPrivateUsage]


# Compile a single in-memory source string directly, bypassing disk discovery/manifest checks and
# (via stub_disk_writes) the filesystem entirely.
def compile_source(
    source: str,
    *,
    local_path: str = "data/pack/blocklight/main.bl",
    options: blocklight.CompilerOptions = NO_HEADER,
    pack_name: str | None = None,
    pack_format: int | None = None,
    namespace: str | None = None,
) -> Result:
    reset_for_test(options)
    compile_ = blocklight.Compile(local_path, local_path.split("/")[1])
    sf = blocklight.SourceFile(
        local_path=local_path,
        source=source,
        pack_name=pack_name,
        pack_format=pack_format,
        namespace=namespace,
    )
    with stub_disk_writes() as written:
        compile_.compile(sf)
        blocklight.orchestration.wait_for_writes()
    return _snapshot(written)


# Run a full discover-and-compile pass (pack.mcmeta + data/ discovery) in the current directory.
# Writes go to real disk: manifest/staleness tests depend on real persistence across runs.
def run_compile(options: blocklight.CompilerOptions = NO_HEADER) -> Result:
    blocklight.reset_globals()
    blocklight.tui.set_options(options)
    blocklight.orchestration.run()
    return _snapshot()
