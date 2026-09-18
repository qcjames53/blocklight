# Manifest-driven incremental compilation: hash-based skip, stale-output and orphan cleanup.

import json
import os
import unittest.mock

import blocklight
from tests.helpers import reset_for_test, run_compile, scratch_dir, strip_header

_MANIFEST = ".blocklight-manifest.json"
_OUTPUT = "data/ns/function/main/hello.mcfunction"


def _write_pack() -> None:
    with open("pack.mcmeta", "w", encoding="utf-8") as f:
        json.dump({"pack": {"min_format": 1}}, f)


def _write_source(source: str) -> None:
    path = "data/ns/blocklight/main.bl"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return strip_header(f.read())


def test_first_compile_writes_a_manifest():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    entry = manifest["sources"]["data/ns/blocklight/main.bl"]
    assert entry["outputs"] == [_OUTPUT]
    assert entry["needs_recompile"] is False
    assert isinstance(entry["source_hash"], str) and entry["source_hash"]


def test_manifest_records_load_and_tick_as_global_function_ids():
    with scratch_dir():
        _write_pack()
        _write_source("load function warmup\n    say hi\ntick function heartbeat\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    assert manifest["load"] == ["ns:main/warmup"]
    assert manifest["tick"] == ["ns:main/heartbeat"]
    assert "load" not in manifest["sources"]["data/ns/blocklight/main.bl"]
    assert "tick" not in manifest["sources"]["data/ns/blocklight/main.bl"]


def test_reused_source_still_registers_as_load_and_tick():
    with scratch_dir():
        _write_pack()
        _write_source("load function warmup\n    say hi\ntick function heartbeat\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        # Second run: source hash is unchanged, so this exercises the manifest-reuse path.
        result = run_compile(blocklight.CompilerOptions())
    assert result.load_functions == {"data/ns/function/main/warmup.mcfunction"}
    assert result.tick_functions == {"data/ns/function/main/heartbeat.mcfunction"}


def test_unchanged_source_is_skipped_not_rewritten():
    # The dev-build flag forces every source to recompile regardless of the cached hash, so it
    # must be disabled here to exercise the skip path this test is actually about.
    with scratch_dir(), unittest.mock.patch("blocklight._BL_IS_DEV_BUILD", False):
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say tampered")
        result = run_compile(blocklight.CompilerOptions())
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say tampered"  # untouched: hash matched, so it was skipped, not rewritten


def test_changed_source_deletes_stale_output_and_recompiles():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        _write_source("function hello\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions())
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say bye"


def test_comment_only_change_does_not_trigger_recompile():
    # The hash is computed from cleaned lines (comments/blanks already stripped, trailing
    # whitespace rstripped), so a purely cosmetic edit must still cache-hit. As above, the
    # dev-build flag must be disabled or it would force a recompile regardless.
    with scratch_dir(), unittest.mock.patch("blocklight._BL_IS_DEV_BUILD", False):
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say tampered")
        _write_source("# a new comment\nfunction hello\n    say hi   \n\n")
        result = run_compile(blocklight.CompilerOptions())
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say tampered"  # untouched: cleaned lines unchanged despite the cosmetic edit


def test_renamed_function_orphans_the_old_output():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        _write_source("function goodbye\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        old_exists = os.path.exists(_OUTPUT)
        new_exists = os.path.exists("data/ns/function/main/goodbye.mcfunction")
    assert not old_exists
    assert new_exists


def test_removed_source_orphans_its_outputs():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        os.remove("data/ns/blocklight/main.bl")
        run_compile(blocklight.CompilerOptions())
        exists = os.path.exists(_OUTPUT)
    assert not exists


def test_dry_run_does_not_delete_the_stale_output_of_a_renamed_function():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        _write_source("function goodbye\n    say hi\n")
        run_compile(blocklight.CompilerOptions(dry_run=True))
        old_exists = os.path.exists(_OUTPUT)
    assert old_exists  # a real run would delete this; a dry run must leave it alone


def test_dry_run_does_not_delete_the_orphaned_output_of_a_removed_source():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        os.remove("data/ns/blocklight/main.bl")
        run_compile(blocklight.CompilerOptions(dry_run=True))
        exists = os.path.exists(_OUTPUT)
    assert exists  # a real run would orphan-delete this; a dry run must leave it alone


def test_erroring_source_is_recompiled_every_run_even_if_unchanged():
    with scratch_dir():
        _write_pack()
        _write_source("if x:\n    say hi\n")  # not a function header: a whole-file BLFatalError
        result1 = run_compile(blocklight.CompilerOptions())
        result2 = run_compile(blocklight.CompilerOptions())
    assert len(result1.errors) == 1
    assert len(result2.errors) == 1  # reported again, not silently dropped by the hash-match skip


def test_python_block_source_is_recompiled_every_run_even_if_unchanged():
    with scratch_dir():
        _write_pack()
        _write_source('function hello\n    python\n        emit("say hi")\n')
        run_compile(blocklight.CompilerOptions())
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    assert manifest["sources"]["data/ns/blocklight/main.bl"]["needs_recompile"] is True


def test_output_collision_keeps_erroring_after_the_first_run():
    # A source-level BLFileError (e.g. a stale write/collision) must also force a recompile next
    # run, not just BLNonFatalError/BLFatalError raised from inside function compilation.
    with scratch_dir():
        _write_pack()
        path_a = "data/ns/blocklight/a.bl"
        os.makedirs(os.path.dirname(path_a), exist_ok=True)
        with open(path_a, "w", encoding="utf-8") as f:
            f.write("root function collide\n    say from a\n")
        path_b = "data/ns/blocklight/b.bl"
        with open(path_b, "w", encoding="utf-8") as f:
            f.write("root function collide\n    say from b\n")
        result1 = run_compile(blocklight.CompilerOptions())
        result2 = run_compile(blocklight.CompilerOptions())
    assert len(result1.errors) == 1
    assert len(result2.errors) == 1


def test_delete_refuses_output_missing_header():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say not blocklight output")
        _write_source("function hello\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions())
        survived = _read(_OUTPUT)
    assert survived == "say not blocklight output"
    assert any(isinstance(e, blocklight.BLFileError) for e in result.errors)


def test_delete_stale_output_reports_a_verify_read_failure():
    with scratch_dir():
        with open("stale.mcfunction", "w", encoding="utf-8") as f:
            f.write(f"# {blocklight._HEADER_MARKER}\nsay hi\n")  # pyright: ignore[reportPrivateUsage]
        reset_for_test()
        with unittest.mock.patch("blocklight.open", side_effect=OSError(13, "Permission denied")):
            blocklight.orchestration.delete_stale_output("stale.mcfunction", "data/ns/blocklight/x.bl")
        errors = blocklight.tui.get_errors()
        survived = os.path.isfile("stale.mcfunction")
    assert survived  # the verify read failed, so the file must never have reached os.remove
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLFileError)
    assert "Failed to verify 'stale.mcfunction' before deleting" in str(errors[0])


def test_delete_stale_output_reports_a_remove_failure():
    with scratch_dir():
        with open("stale.mcfunction", "w", encoding="utf-8") as f:
            f.write(f"# {blocklight._HEADER_MARKER}\nsay hi\n")  # pyright: ignore[reportPrivateUsage]
        reset_for_test()
        with unittest.mock.patch("blocklight.os.remove", side_effect=OSError(13, "Permission denied")):
            blocklight.orchestration.delete_stale_output("stale.mcfunction", "data/ns/blocklight/x.bl")
        errors = blocklight.tui.get_errors()
        survived = os.path.isfile("stale.mcfunction")
    assert survived  # os.remove failed, so the real file must still be there
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLFileError)
    assert "Failed to delete stale file 'stale.mcfunction'" in str(errors[0])


def test_header_verification_never_blocks_recompiling_own_output():
    # The header is always written now, so the unconditional marker check never blocks a
    # legitimate recompile of blocklight's own output.
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions())
        _write_source("function hello\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions())
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say bye"


def test_dry_run_does_not_write_a_manifest():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        run_compile(blocklight.CompilerOptions(dry_run=True))
        exists = os.path.isfile(_MANIFEST)
    assert not exists


def test_corrupt_manifest_is_treated_as_empty():
    with scratch_dir():
        _write_pack()
        _write_source("function hello\n    say hi\n")
        with open(_MANIFEST, "w", encoding="utf-8") as f:
            f.write("not json")
        result = run_compile(blocklight.CompilerOptions())
    assert result.errors == []
    assert result.files == {_OUTPUT}
