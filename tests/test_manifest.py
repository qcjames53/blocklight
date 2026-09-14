# Manifest-driven incremental compilation: hash-based skip, stale-output and orphan cleanup.

import json
import os

import blocklight
from tests.helpers import run_compile, scratch_dir

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
        return f.read()


def test_first_compile_writes_a_manifest():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    entry = manifest["sources"]["data/ns/blocklight/main.bl"]
    assert entry["outputs"] == [_OUTPUT]
    assert entry["needs_recompile"] is False
    assert isinstance(entry["source_hash"], str) and entry["source_hash"]
    assert entry["source_size"] == len(b"function hello:\n    say hi\n")


def test_manifest_records_load_and_tick_as_global_function_ids():
    with scratch_dir():
        _write_pack()
        _write_source("load function warmup:\n    say hi\ntick function heartbeat:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    assert manifest["load"] == ["ns:main/warmup"]
    assert manifest["tick"] == ["ns:main/heartbeat"]
    assert "load" not in manifest["sources"]["data/ns/blocklight/main.bl"]
    assert "tick" not in manifest["sources"]["data/ns/blocklight/main.bl"]


def test_reused_source_still_registers_as_load_and_tick():
    with scratch_dir():
        _write_pack()
        _write_source("load function warmup:\n    say hi\ntick function heartbeat:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        # Second run: source hash is unchanged, so this exercises the manifest-reuse path.
        result = run_compile(blocklight.CompilerOptions(no_header=True))
    assert result.load_functions == {"data/ns/function/main/warmup.mcfunction"}
    assert result.tick_functions == {"data/ns/function/main/heartbeat.mcfunction"}


def test_unchanged_source_is_skipped_not_rewritten():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say tampered")
        result = run_compile(blocklight.CompilerOptions(no_header=True))
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say tampered"  # untouched: hash matched, so it was skipped, not rewritten


def test_changed_source_deletes_stale_output_and_recompiles():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        _write_source("function hello:\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions(no_header=True))
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say bye"


def test_size_change_skips_hashing_and_still_recompiles():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        new_source = "function hello:\n    say hi there now\n"  # different length
        _write_source(new_source)
        run_compile(blocklight.CompilerOptions(no_header=True))
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
        contents = _read(_OUTPUT)
    entry = manifest["sources"]["data/ns/blocklight/main.bl"]
    assert contents == "say hi there now"
    assert entry["source_hash"] is None  # size alone proved a change; hashing was skipped
    assert entry["source_size"] == len(new_source.encode())


def test_unchanged_size_after_a_skipped_hash_still_reaches_a_cache_hit():
    # The run right after a size change has no hash to compare against (it was never computed),
    # so it must recompile once more before caching resumes -- verify that backfill happens and
    # the file isn't rewritten a third time.
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        _write_source("function hello:\n    say hi there now\n")
        run_compile(blocklight.CompilerOptions(no_header=True))  # size changed: hash skipped
        run_compile(blocklight.CompilerOptions(no_header=True))  # unchanged: backfills a hash
        with open(_MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say tampered")
        result = run_compile(blocklight.CompilerOptions(no_header=True))  # should now cache-hit
        contents = _read(_OUTPUT)
    entry = manifest["sources"]["data/ns/blocklight/main.bl"]
    assert isinstance(entry["source_hash"], str) and entry["source_hash"]
    assert result.errors == []
    assert contents == "say tampered"  # untouched: cache-hit, not recompiled


def test_renamed_function_orphans_the_old_output():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        _write_source("function goodbye:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        old_exists = os.path.exists(_OUTPUT)
        new_exists = os.path.exists("data/ns/function/main/goodbye.mcfunction")
    assert not old_exists
    assert new_exists


def test_removed_source_orphans_its_outputs():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        os.remove("data/ns/blocklight/main.bl")
        run_compile(blocklight.CompilerOptions(no_header=True))
        exists = os.path.exists(_OUTPUT)
    assert not exists


def test_erroring_source_is_recompiled_every_run_even_if_unchanged():
    with scratch_dir():
        _write_pack()
        _write_source("if x:\n    say hi\n")  # not a function header: a whole-file BLFatalError
        result1 = run_compile(blocklight.CompilerOptions(no_header=True))
        result2 = run_compile(blocklight.CompilerOptions(no_header=True))
    assert len(result1.errors) == 1
    assert len(result2.errors) == 1  # reported again, not silently dropped by the hash-match skip


def test_python_block_source_is_recompiled_every_run_even_if_unchanged():
    with scratch_dir():
        _write_pack()
        _write_source('function hello:\n    python:\n        emit("say hi")\n')
        run_compile(blocklight.CompilerOptions(no_header=True))
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
            f.write("root function collide:\n    say from a\n")
        path_b = "data/ns/blocklight/b.bl"
        with open(path_b, "w", encoding="utf-8") as f:
            f.write("root function collide:\n    say from b\n")
        result1 = run_compile(blocklight.CompilerOptions(no_header=True))
        result2 = run_compile(blocklight.CompilerOptions(no_header=True))
    assert len(result1.errors) == 1
    assert len(result2.errors) == 1


def test_safe_mode_refuses_to_delete_output_missing_header():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True))
        with open(_OUTPUT, "w", encoding="utf-8") as f:
            f.write("say not blocklight output")
        _write_source("function hello:\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions(verify_before_delete=True))
        survived = _read(_OUTPUT)
    assert survived == "say not blocklight output"
    assert any(isinstance(e, blocklight.BLFileError) for e in result.errors)


def test_verify_before_delete_is_skipped_with_no_header():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True, verify_before_delete=True))
        _write_source("function hello:\n    say bye\n")
        result = run_compile(blocklight.CompilerOptions(no_header=True, verify_before_delete=True))
        contents = _read(_OUTPUT)
    assert result.errors == []
    assert contents == "say bye"


def test_dry_run_does_not_write_a_manifest():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        run_compile(blocklight.CompilerOptions(no_header=True, dry_run=True))
        exists = os.path.isfile(_MANIFEST)
    assert not exists


def test_corrupt_manifest_is_treated_as_empty():
    with scratch_dir():
        _write_pack()
        _write_source("function hello:\n    say hi\n")
        with open(_MANIFEST, "w", encoding="utf-8") as f:
            f.write("not json")
        result = run_compile(blocklight.CompilerOptions(no_header=True))
    assert result.errors == []
    assert result.files == {_OUTPUT}
