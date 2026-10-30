# Load/tick function tags, the manifest, output files and the _bl setup function, across repeated compiles.

import io
import json
import ntpath
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import blocklight
from tests.harness import SOURCE_FILE

_LOAD_TAG = "data/minecraft/tags/function/load.json"
_TICK_TAG = "data/minecraft/tags/function/tick.json"
_MANIFEST = ".blocklight-manifest.json"
_SETUP_FUNCTION = "data/_bl/function/load.mcfunction"
_OUTPUT_A = "data/test/function/main/a.mcfunction"
_LOAD_A = "load function a\n    say a\n"
_LOAD_TICK_A = "load tick function a\n    say a\n"
_PLAIN_A = "function a\n    say a\n"

# Skips where file permissions aren't enforced (Windows, root)
needs_posix_permissions = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="needs POSIX permissions enforced for this user",
)


# Chdir into an empty datapack directory
@pytest.fixture(autouse=True)
def pack_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "pack.mcmeta").write_text('{"pack": {"min_format": 107}}', encoding="utf-8")
    monkeypatch.chdir(pack)
    return pack


# Build whatever bl files are on disk
def _build(options: blocklight.CompilerOptions | None = None) -> blocklight.BuildResult:
    Path("data").mkdir(exist_ok=True)  # discovery needs data/ even with no bl files
    return blocklight.Pack(options or blocklight.CompilerOptions()).compile()


# Compile whatever bl files are on disk. Returns the logged errors.
def _recompile(options: blocklight.CompilerOptions | None = None) -> list[blocklight.BLError]:
    return _build(options).errors


# Compile with `source` as the contents of SOURCE_FILE. Returns the logged errors.
def _compile(source: str, options: blocklight.CompilerOptions | None = None) -> list[blocklight.BLError]:
    _write(SOURCE_FILE, source)
    return _recompile(options)


# Fails the test on any compile error
def _assert_ok(errors: list[blocklight.BLError]) -> None:
    assert errors == [], [str(error) for error in errors]


# The single error in `errors`, which must be a BLFileError
def _single_file_error(errors: list[blocklight.BLError]) -> blocklight.BLError:
    assert [type(error) for error in errors] == [blocklight.BLFileError], [str(error) for error in errors]
    return errors[0]


# Write `contents` to `path`, creating parent folders
def _write(path: str, contents: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(contents, encoding="utf-8")


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _read_json(path: str) -> Any:
    return json.loads(_read(path))


# The 'values' list of a function tag file
def _values(path: str) -> Any:
    return _read_json(path)["values"]


def test_creates_tag_files_with_setup_function_first():
    _assert_ok(_compile(_LOAD_TICK_A))
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]
    assert _values(_TICK_TAG) == ["test:main/a"]


def test_tag_file_created_only_when_needed():
    _assert_ok(_compile(_LOAD_A))
    assert not Path(_TICK_TAG).exists()


def test_user_entries_and_fields_are_kept():
    user_entry = {"id": "other:x", "required": False}
    _write(_LOAD_TAG, json.dumps({"replace": False, "values": ["other:y", user_entry]}))
    _assert_ok(_compile(_LOAD_A))
    assert _read_json(_LOAD_TAG) == {"replace": False, "values": ["other:y", user_entry, "_bl:load", "test:main/a"]}


def test_previous_entries_are_removed():
    _assert_ok(_compile(_LOAD_TICK_A))
    _write(_TICK_TAG, json.dumps({"values": ["test:main/a", "other:y"]}))
    _assert_ok(_compile(_PLAIN_A))
    assert _values(_LOAD_TAG) == ["_bl:load"]
    assert _values(_TICK_TAG) == ["other:y"]


def test_previous_entries_are_removed_in_object_form():
    _assert_ok(_compile(_LOAD_A))
    _write(_LOAD_TAG, json.dumps({"values": ["_bl:load", {"id": "test:main/a", "required": True}]}))
    _assert_ok(_compile(_PLAIN_A))
    assert _values(_LOAD_TAG) == ["_bl:load"]


def test_entry_listed_by_user_is_managed_by_blocklight():
    _write(_LOAD_TAG, json.dumps({"values": [{"id": "test:main/a", "required": False}, "other:y"]}))
    _assert_ok(_compile(_LOAD_A))
    assert _values(_LOAD_TAG) == ["other:y", "_bl:load", "test:main/a"]
    _assert_ok(_compile(_PLAIN_A))
    assert _values(_LOAD_TAG) == ["other:y", "_bl:load"]


def test_entry_readded_by_user_is_kept():
    _assert_ok(_compile(_LOAD_A))
    _assert_ok(_compile(_PLAIN_A))
    _write(_LOAD_TAG, json.dumps({"values": ["_bl:load", "test:main/a"]}))
    _assert_ok(_compile(_PLAIN_A))
    assert _values(_LOAD_TAG) == ["test:main/a", "_bl:load"]  # Blocklight's own entries are re-appended


@pytest.mark.parametrize("contents", [b"{", b"[]", b'{"values": "test:main/a"}', b"\xff"])  # \xff: invalid UTF-8
def test_malformed_tag_file_is_skipped(contents: bytes):
    Path(_LOAD_TAG).parent.mkdir(parents=True)
    Path(_LOAD_TAG).write_bytes(contents)
    _single_file_error(_compile(_LOAD_TICK_A))
    assert Path(_LOAD_TAG).read_bytes() == contents
    assert _values(_TICK_TAG) == ["test:main/a"]
    assert Path(_OUTPUT_A).is_file()


@needs_posix_permissions
def test_read_only_tag_file_is_skipped_and_left_for_user():
    _assert_ok(_compile(_LOAD_TICK_A))
    os.chmod(_TICK_TAG, 0o444)
    error = _single_file_error(_compile(_LOAD_A))
    assert f"Orphaned entries 'test:main/a' remain in '{_TICK_TAG}'. Please manually clean up this file." in str(error)
    assert _values(_TICK_TAG) == ["test:main/a"]
    os.chmod(_TICK_TAG, 0o644)
    _assert_ok(_compile(_LOAD_A))
    assert _values(_TICK_TAG) == ["test:main/a"]  # left for the user, as the error said


def test_failed_tag_update_lists_every_entry_it_stops_managing():
    _assert_ok(_compile(_LOAD_A + "load function b\n    say b\n"))
    _write(_LOAD_TAG, "{")
    error = _single_file_error(_compile(_PLAIN_A))
    assert f"Orphaned entries 'test:main/a', 'test:main/b' remain in '{_LOAD_TAG}'." in str(error)


def test_failed_tag_update_with_nothing_dropped_has_no_extra_guidance():
    _assert_ok(_compile(_LOAD_A))
    _write(_LOAD_TAG, "{")
    error = _single_file_error(_compile(_LOAD_A))
    assert "Orphaned entries" not in str(error)
    _write(_LOAD_TAG, "{}")
    _assert_ok(_compile(_LOAD_A))
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]  # re-added once the tag is fixed


@pytest.mark.parametrize(
    "manifest",
    [
        "{",
        "[]",
        '{"sources": 1}',
        '{"sources": {"data/test/blocklight/main.bl": []}}',
        '{"sources": {"data/test/blocklight/main.bl": {"outputs": "x"}}}',
        '{"load": "test:main/a"}',
        '{"tick": [1]}',
    ],
)
def test_malformed_manifest_aborts(manifest: str):
    _write(_MANIFEST, manifest)
    error = _single_file_error(_compile(_LOAD_A))
    assert f"Delete '{_MANIFEST}' to rebuild from scratch. Compile aborted." in str(error)
    assert not Path("data/test/function").exists()
    assert not Path(_LOAD_TAG).exists()
    assert _read(_MANIFEST) == manifest


@needs_posix_permissions
def test_read_only_manifest_aborts():
    _assert_ok(_compile(_LOAD_A))
    os.chmod(_MANIFEST, 0o444)
    _single_file_error(_compile(_PLAIN_A))
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]


@pytest.mark.parametrize("manifest", ["", " \n", "{}", '{"sources": {"data/test/blocklight/main.bl": {}}}'])
def test_manifest_fields_may_be_missing(manifest: str):
    _write(_MANIFEST, manifest)
    _assert_ok(_compile(_LOAD_A))
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]


@pytest.mark.parametrize(
    "manifest",
    [
        '{"version": "1.0"}',
        '{"version": [true, 0]}',
        '{"sources": {"data/test/blocklight/main.bl": {"source_hash": 1}}}',
    ],
)
def test_bad_recompile_field_is_logged_and_compile_continues(manifest: str):
    _write(_MANIFEST, manifest)
    error = _single_file_error(_compile(_LOAD_A))
    assert "Recompiling" in str(error)
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]


def test_extra_manifest_fields_are_cleared():
    _write(_MANIFEST, '{"extra": 1}')
    _assert_ok(_compile(_LOAD_A))
    manifest = _read_json(_MANIFEST)
    assert set(manifest) == {"version", "load", "tick", "sources"}
    assert set(manifest["sources"][SOURCE_FILE]) == {"outputs", "source_hash"}


def test_hash_omitted_when_recompile_needed():
    _assert_ok(_compile(_PLAIN_A))
    assert "source_hash" in _read_json(_MANIFEST)["sources"][SOURCE_FILE]
    errors = _compile(_PLAIN_A + "function b\n    if\n        say b\n")
    assert [type(error) for error in errors] == [blocklight.BLSyntaxError]
    assert "source_hash" not in _read_json(_MANIFEST)["sources"][SOURCE_FILE]


def test_setup_function_creates_reserved_objective():
    _assert_ok(_compile(_PLAIN_A))
    lines = _read(_SETUP_FUNCTION).splitlines()
    assert lines[0].startswith(f"# {blocklight.Compile.HEADER_MARKER}")
    assert lines[1:] == ["scoreboard objectives add _bl dummy"]


def test_setup_function_removed_with_last_source():
    _assert_ok(_compile(_LOAD_A))
    os.remove(SOURCE_FILE)
    _assert_ok(_recompile())
    assert not Path("data/_bl").exists()
    assert _values(_LOAD_TAG) == []


def test_setup_function_never_overwrites_user_file():
    _write(_SETUP_FUNCTION, "say mine")
    _single_file_error(_compile(_LOAD_A))
    assert _read(_SETUP_FUNCTION) == "say mine"
    assert _values(_LOAD_TAG) == ["test:main/a"]
    os.remove(SOURCE_FILE)
    _assert_ok(_recompile())
    assert _read(_SETUP_FUNCTION) == "say mine"


def test_setup_function_path_is_reserved():
    _write("data/_bl/blocklight/x.bl", "root function load\n    say mine\n")
    errors = _recompile()
    assert [(type(error), error.lineno) for error in errors] == [(blocklight.BLFileError, 1)]
    assert "reserved for Blocklight" in str(errors[0])


def test_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]):
    _write(SOURCE_FILE, _LOAD_A)
    result = _build(blocklight.CompilerOptions(dry_run=True))
    _assert_ok(result.errors)
    blocklight.report(result, 0)
    assert "pack: compiled 2 functions (2 new)" in capsys.readouterr().out
    assert not Path("data/test/function").exists()
    assert not Path("data/minecraft").exists()
    assert not Path("data/_bl").exists()
    assert not Path(_MANIFEST).exists()


def test_dry_run_counts_unchanged_and_reports_refusals(capsys: pytest.CaptureFixture[str]):
    _assert_ok(_compile(_PLAIN_A + "function b\n    say b\n"))
    _write("data/test/function/main/b.mcfunction", "say mine")
    _write(SOURCE_FILE, _PLAIN_A + "function b\n    say edited\n")  # an unchanged source would reuse its outputs
    result = _build(blocklight.CompilerOptions(dry_run=True))
    error = _single_file_error(result.errors)
    assert "Refusing to overwrite" in str(error)
    blocklight.report(result, 0)
    out = capsys.readouterr().out
    assert "pack: compiled 2 functions with errors (no changes)" in out  # a, setup function unchanged; b refused


def test_main_exits_1_on_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr(sys, "argv", ["blocklight"])
    _write(SOURCE_FILE, "function a\n    if\n        say a\n")
    with pytest.raises(SystemExit) as exit_info:
        blocklight.main()
    assert exit_info.value.code == 1
    assert "with errors" in capsys.readouterr().out


def test_cached_source_keeps_its_tags():
    _assert_ok(_compile(_LOAD_TICK_A))
    _assert_ok(_compile(_LOAD_TICK_A))
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]
    assert _values(_TICK_TAG) == ["test:main/a"]


def test_summary_counts_reused_functions(capsys: pytest.CaptureFixture[str]):
    _assert_ok(_compile(_PLAIN_A + "function b\n    say b\n"))
    result = _build()
    _assert_ok(result.errors)
    blocklight.report(result, 0)
    assert "pack: compiled 3 functions (no changes)" in capsys.readouterr().out  # a and b reused, setup unchanged


# Stand-in for stdout on a color terminal
class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


# BuildResult with `fields` set, as a build that produced them would leave it
def _build_result(**fields: object) -> blocklight.BuildResult:
    result = blocklight.BuildResult()
    for name, value in fields.items():
        assert hasattr(result, name), f"BuildResult has no field '{name}'"
        setattr(result, name, value)
    return result


# Summary `report` prints for `result`, in color if `colors`
def _summary(monkeypatch: pytest.MonkeyPatch, result: blocklight.BuildResult, *, colors: bool) -> str:
    stdout = _Terminal() if colors else io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.delenv("NO_COLOR", raising=False)
    blocklight.report(result, 0.13)
    return stdout.getvalue()


@pytest.mark.parametrize(
    ("result", "summary"),
    [
        (
            _build_result(
                pack_name="pack",
                outputs_new=2,
                outputs_modified=3,
                outputs_unchanged=5,
                outputs_reused=90,
                outputs_deleted=1,
            ),
            "pack: compiled 100 functions (2 new, 3 modified, 1 deleted)",
        ),
        (_build_result(pack_name="pack", outputs_reused=100), "pack: compiled 100 functions (no changes)"),
        (
            _build_result(
                pack_name="pack", errors=[blocklight.BLSyntaxError("bad")], outputs_modified=3, outputs_unchanged=97
            ),
            "pack: compiled 100 functions with errors (3 modified)",
        ),
        (
            _build_result(pack_name="pack", errors=[blocklight.BLSyntaxError("bad")], outputs_unchanged=1),
            "pack: compiled 1 function with errors (no changes)",
        ),
    ],
    ids=["compiled", "no changes", "with errors", "errors only"],
)
def test_summary_line(monkeypatch: pytest.MonkeyPatch, result: blocklight.BuildResult, summary: str):
    assert _summary(monkeypatch, result, colors=False) == f"{summary} 130ms\n"


def test_summary_colors(monkeypatch: pytest.MonkeyPatch):
    result = _build_result(pack_name="pack", outputs_new=2, outputs_modified=3, outputs_deleted=1)
    out = _summary(monkeypatch, result, colors=True)
    # Pack name white, status green, new blue, modified yellow, deleted red, time yellow, punctuation grey
    for text, color in [
        ("pack", 37),
        (": ", 90),
        ("compiled 5 functions", 32),
        ("2 new", 34),
        ("3 modified", 33),
        ("1 deleted", 31),
        (" 130ms", 33),
    ]:
        assert f"\033[{color}m{text}\033[0m" in out, text
    assert re.sub(r"\033\[[\d;]+m", "", out) == "pack: compiled 5 functions (2 new, 3 modified, 1 deleted) 130ms\n"


def test_summary_colors_with_errors(monkeypatch: pytest.MonkeyPatch):
    result = _build_result(pack_name="pack", errors=[blocklight.BLSyntaxError("bad")], outputs_modified=1)
    out = _summary(monkeypatch, result, colors=True)
    for text, color in [("compiled 1 function with errors", 31), ("1 modified", 33)]:
        assert f"\033[{color}m{text}\033[0m" in out, text


@pytest.mark.parametrize(
    ("pack_section", "pack_format"),
    [
        ({"min_format": 107}, 107),
        ({"min_format": [94, 1]}, 94),
        ({"pack_format": 48}, 48),
        ({"supported_formats": [40, 50]}, 40),
        ({"supported_formats": {"min_inclusive": 41, "max_inclusive": 60}}, 41),
    ],
    ids=["min_format", "min_format major.minor", "pack_format", "supported_formats list", "supported_formats object"],
)
def test_pack_format_is_read_from_pack_mcmeta(pack_section: dict[str, object], pack_format: int):
    _write("pack.mcmeta", json.dumps({"pack": pack_section}))
    _assert_ok(_compile("function a\n    python\n        cmd(f'say {PACK_FORMAT}')\n"))
    assert _read(_OUTPUT_A).endswith(f"say {pack_format}")


def test_pack_and_namespace_names_are_not_restricted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pack = tmp_path / "My Pack"
    pack.mkdir()
    (pack / "pack.mcmeta").write_text('{"pack": {"min_format": 107}}', encoding="utf-8")
    monkeypatch.chdir(pack)
    _write("data/My.NS/blocklight/main.bl", _PLAIN_A)
    result = _build()
    _assert_ok(result.errors)
    assert result.pack_name == "My Pack"
    assert Path("data/My.NS/function/main/a.mcfunction").is_file()


def test_cached_source_recompiles_missing_output():
    _assert_ok(_compile(_LOAD_A))
    os.remove(_OUTPUT_A)
    _assert_ok(_compile(_LOAD_A))
    assert Path(_OUTPUT_A).is_file()
    assert _values(_LOAD_TAG) == ["_bl:load", "test:main/a"]


def test_leftover_output_with_header_is_overwritten():
    _write(_OUTPUT_A, f"# {blocklight.Compile.HEADER_MARKER} old\nsay old")
    _assert_ok(_compile(_PLAIN_A))
    assert _read(_OUTPUT_A).endswith("say a")


def test_empty_file_at_output_path_is_overwritten():
    _write(_OUTPUT_A, "")
    _assert_ok(_compile(_PLAIN_A))
    assert _read(_OUTPUT_A).endswith("say a")


def test_output_without_header_is_not_overwritten():
    _write(_OUTPUT_A, "say mine")
    error = _single_file_error(_compile(_PLAIN_A))
    assert "Refusing to overwrite" in str(error)
    assert _read(_OUTPUT_A) == "say mine"


def test_unchanged_output_is_not_rewritten():
    _assert_ok(_compile(_PLAIN_A))
    os.utime(_OUTPUT_A, ns=(0, 0))
    _assert_ok(_compile(_PLAIN_A))
    assert Path(_OUTPUT_A).stat().st_mtime_ns == 0


def test_force_recompiles_unchanged_source():
    _assert_ok(_compile(_PLAIN_A))
    assert _build().sources_skipped == 1
    result = _build(blocklight.CompilerOptions(force=True))
    _assert_ok(result.errors)
    assert (result.sources_read, result.sources_skipped) == (1, 0)


def test_force_rewrites_outputs_of_unchanged_source():
    _assert_ok(_compile(_PLAIN_A))
    compiled = _read(_OUTPUT_A)
    _write(_OUTPUT_A, f"# {blocklight.Compile.HEADER_MARKER}\nsay stale")
    _assert_ok(_recompile())
    assert _read(_OUTPUT_A).endswith("say stale")  # the source is unchanged, so its outputs are reused
    _assert_ok(_recompile(blocklight.CompilerOptions(force=True)))
    assert _read(_OUTPUT_A) == compiled


@pytest.mark.parametrize(
    ("argv", "options"),
    [
        (["--force"], blocklight.CompilerOptions(force=True)),
        (["--dry-run"], blocklight.CompilerOptions(dry_run=True)),
        (["--safe"], blocklight.CompilerOptions(no_python=True, no_symlink=True)),
    ],
    ids=["force", "dry run", "safe"],
)
def test_flags_parse_to_options(monkeypatch: pytest.MonkeyPatch, argv: list[str], options: blocklight.CompilerOptions):
    received: list[blocklight.CompilerOptions] = []

    # Records the options main() builds instead of compiling
    class _RecordingPack:
        def __init__(self, options: blocklight.CompilerOptions) -> None:
            received.append(options)

        def compile(self) -> blocklight.BuildResult:
            return blocklight.BuildResult()

    monkeypatch.setattr(sys, "argv", ["blocklight", *argv])
    monkeypatch.setattr(blocklight, "Pack", _RecordingPack)
    blocklight.main()
    assert received == [options]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_created_files_are_not_executable():
    previous_umask = os.umask(0o022)
    try:
        _assert_ok(_compile(_LOAD_TICK_A))
    finally:
        os.umask(previous_umask)
    for path in (_OUTPUT_A, _SETUP_FUNCTION, _LOAD_TAG, _TICK_TAG, _MANIFEST):
        assert Path(path).stat().st_mode & 0o777 == 0o644, path


def test_output_no_longer_produced_is_deleted():
    _assert_ok(_compile(_PLAIN_A + "function b\n    say b\n"))
    _assert_ok(_compile(_PLAIN_A))
    assert Path(_OUTPUT_A).is_file()
    assert not Path("data/test/function/main/b.mcfunction").exists()


def test_deleted_outputs_are_counted(capsys: pytest.CaptureFixture[str]):
    _assert_ok(_compile(_PLAIN_A + "function b\n    say b\n"))
    _write(SOURCE_FILE, _PLAIN_A)
    result = _build()
    _assert_ok(result.errors)
    assert result.outputs_deleted == 1
    blocklight.report(result, 0)
    assert "pack: compiled 2 functions (1 deleted)" in capsys.readouterr().out  # a and setup unchanged, b gone


def test_setup_function_deletion_is_counted():
    _assert_ok(_compile(_PLAIN_A))
    os.remove(SOURCE_FILE)
    result = _build()
    _assert_ok(result.errors)
    assert result.outputs_deleted == 2  # a and the setup function


def test_dry_run_counts_deletions_without_deleting():
    _assert_ok(_compile(_PLAIN_A + "function b\n    say b\n"))
    _write(SOURCE_FILE, _PLAIN_A)
    result = _build(blocklight.CompilerOptions(dry_run=True))
    _assert_ok(result.errors)
    assert result.outputs_deleted == 1
    assert Path("data/test/function/main/b.mcfunction").is_file()


def test_folders_emptied_by_deletes_are_removed():
    _assert_ok(_compile("function a\n    as @a\n        say a\n"))
    assert Path("data/test/function/main/a_helper").is_dir()
    _assert_ok(_compile("function b\n    say b\n"))
    assert not Path("data/test/function/main/a_helper").exists()
    assert Path("data/test/function/main/b.mcfunction").is_file()


def test_duplicate_function_is_not_registered():
    error = _single_file_error(_compile("function a\n    say first\nload function a\n    say second\n"))
    assert "Another function already compiles to" in str(error)
    assert _read(_OUTPUT_A).endswith("say first")
    assert _values(_LOAD_TAG) == ["_bl:load"]


def test_duplicate_function_writes_none_of_its_helpers():
    error = _single_file_error(_compile("function a\n    say first\nfunction a\n    as @s\n        say second\n"))
    assert "Another function already compiles to" in str(error)
    assert error.lineno == 3
    assert not Path("data/test/function/main/a_helper").exists()


def test_collision_between_sources_is_reported_for_both():
    _write("data/test/blocklight/first.bl", "root function shared\n    say first\n")
    _write("data/test/blocklight/second.bl", "\nroot function shared\n    say second\n")
    errors = _recompile()
    assert sorted((error.filename, error.lineno) for error in errors) == [
        ("data/test/blocklight/first.bl", 1),
        ("data/test/blocklight/second.bl", 2),
    ]
    assert all("is also compiled by" in str(error) for error in errors)


def test_root_function_moved_between_sources_is_kept():
    _write("data/test/blocklight/first.bl", "root function shared\n    say first\n")
    _write("data/test/blocklight/second.bl", "function other\n    say other\n")
    _assert_ok(_recompile())
    _write("data/test/blocklight/first.bl", "function other\n    say other\n")
    _write("data/test/blocklight/second.bl", "root function shared\n    say second\n")
    _assert_ok(_recompile())
    assert _read("data/test/function/shared.mcfunction").endswith("say second")


@pytest.mark.parametrize("path", ["data/test/blocklight/Upper.bl", "data/test/blocklight/Sub/x.bl"])
def test_source_path_must_be_lowercase(path: str):
    _write(path, _PLAIN_A)
    errors = _recompile()
    assert [type(error) for error in errors] == [blocklight.BLSyntaxError]
    assert not Path("data/test/function").exists()


def test_windows_source_paths_use_forward_slashes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(os, "sep", "\\")
    monkeypatch.setattr(os.path, "join", ntpath.join)

    # One Windows-style folder holding x.bl
    def walk(top: str, followlinks: bool) -> Iterator[tuple[str, list[str], list[str]]]:
        yield f"{top}\\sub", [], ["x.bl"]

    monkeypatch.setattr(os, "walk", walk)
    pack = blocklight.Pack(blocklight.CompilerOptions())
    paths = list(pack._iter_bl_files("data\\test\\blocklight"))  # pyright: ignore[reportPrivateUsage]
    assert paths == ["data/test/blocklight/sub/x.bl"]
