# pack.mcmeta reading and Orchestration._read_pack_format / Orchestration.run / Compile.run

import json
import os
import unittest.mock

import pytest

import blocklight
from tests.helpers import reset_for_test, run_compile, scratch_dir

_DRY_RUN = blocklight.CompilerOptions(no_header=True, dry_run=True)


def _write_pack(pack_meta: dict[str, object]) -> None:
    with open("pack.mcmeta", "w", encoding="utf-8") as f:
        json.dump(pack_meta, f)


def _write_source(namespace: str, relative_path: str, source: str) -> None:
    path = os.path.join("data", namespace, "blocklight", relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)


def test_read_pack_format_prefers_min_format():
    reset_for_test()
    value = blocklight.orchestration._read_pack_format(  # pyright: ignore[reportPrivateUsage]
        {"pack": {"min_format": 5, "pack_format": 99}}
    )
    assert value == 5
    assert blocklight.tui.get_errors() == []


def test_read_pack_format_falls_back_to_pack_format():
    reset_for_test()
    value = blocklight.orchestration._read_pack_format(  # pyright: ignore[reportPrivateUsage]
        {"pack": {"pack_format": 12}}
    )
    assert value == 12
    assert blocklight.tui.get_errors() == []


def test_read_pack_format_uses_smallest_supported_format():
    reset_for_test()
    value = blocklight.orchestration._read_pack_format(  # pyright: ignore[reportPrivateUsage]
        {"pack": {"supported_formats": [15, 4, 9]}}
    )
    assert value == 4
    assert blocklight.tui.get_errors() == []


def test_read_pack_format_truncates_a_float():
    reset_for_test()
    value = blocklight.orchestration._read_pack_format(  # pyright: ignore[reportPrivateUsage]
        {"pack": {"min_format": 7.9}}
    )
    assert value == 7
    assert blocklight.tui.get_errors() == []


def test_read_pack_format_missing_is_recoverable():
    reset_for_test()
    value = blocklight.orchestration._read_pack_format(  # pyright: ignore[reportPrivateUsage]
        {"pack": {"description": "no format here"}}
    )
    assert value is None
    errors = blocklight.tui.get_errors()
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLSyntaxError)


def test_missing_pack_mcmeta_exits():
    with scratch_dir(), pytest.raises(SystemExit):
        run_compile(_DRY_RUN)


def test_invalid_json_pack_mcmeta_exits():
    with scratch_dir():
        with open("pack.mcmeta", "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with pytest.raises(SystemExit):
            run_compile(_DRY_RUN)


def test_invalid_pack_name_is_recoverable():
    with scratch_dir():
        os.makedirs("Invalid Name")
        os.chdir("Invalid Name")
        _write_pack({"pack": {"min_format": 1}})
        result = run_compile(_DRY_RUN)
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLSyntaxError)


def test_invalid_namespace_is_skipped_but_others_still_compile():
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        _write_source("Bad Namespace", "main.bl", "function hello:\n    say hi\n")
        _write_source("good_ns", "main.bl", "function hello:\n    say hi\n")
        result = run_compile(_DRY_RUN)
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLSyntaxError)
    assert result.files == {"data/good_ns/function/main/hello.mcfunction"}


def test_dry_run_does_not_write_output_files_to_disk():
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        _write_source("ns", "main.bl", "function hello:\n    say hi\n")
        result = run_compile(_DRY_RUN)
    # get_files() reflects what *would* be compiled, but nothing should actually touch disk.
    assert result.files == {"data/ns/function/main/hello.mcfunction"}
    assert not os.path.exists("data/ns/function/main/hello.mcfunction")


def test_no_data_directory_produces_no_files_or_errors():
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        result = run_compile(_DRY_RUN)
    assert result.errors == []
    assert result.files == frozenset()


def test_discovers_and_compiles_multiple_namespaces_and_files():
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        _write_source("ns_a", "one.bl", "function foo:\n    say foo\n")
        _write_source("ns_b", "nested/two.bl", "root function bar:\n    say bar\n")
        result = run_compile(_DRY_RUN)
    assert result.errors == []
    assert result.files == {
        "data/ns_a/function/one/foo.mcfunction",
        "data/ns_b/function/bar.mcfunction",
    }


def test_unreadable_source_file_is_a_bl_file_error():
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        # A directory named like a source file matches the glob but can't be opened as one.
        os.makedirs(os.path.join("data", "ns", "blocklight", "oops.bl"))
        result = run_compile(_DRY_RUN)
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLFileError)


def test_unanticipated_compile_error_is_reported_not_swallowed():
    # A truly unexpected exception (a bug, not a modeled BLError) must still surface as an error
    # instead of vanishing, since Orchestration.run()'s compile-pool futures are never awaited
    # for their result otherwise.
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        _write_source("ns", "main.bl", "function hello:\n    say hi\n")
        with unittest.mock.patch("blocklight.hashlib.sha256", side_effect=RuntimeError("boom")):
            result = run_compile(_DRY_RUN)
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLFileError)
    assert "boom" in str(result.errors[0])


def test_invalid_utf8_source_file_is_a_bl_file_error():
    # A source file that can't even be decoded must surface a clean error, not vanish silently
    # (this exercises the compile thread pool's failure path, not just a direct read).
    with scratch_dir():
        _write_pack({"pack": {"min_format": 1}})
        path = os.path.join("data", "ns", "blocklight", "main.bl")
        os.makedirs(os.path.dirname(path))
        with open(path, "wb") as f:
            f.write(b"function hello:\n    say \xff\xfe\n")
        result = run_compile(_DRY_RUN)
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLFileError)
