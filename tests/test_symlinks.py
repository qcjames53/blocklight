# Symlink refusal under --no-symlink, and the cost of checking: each path is lstat'ed at most once per compile.

import json
import os
from collections import Counter
from pathlib import Path

import pytest

import blocklight
from tests.harness import SOURCE_FILE

_NO_SYMLINK = blocklight.CompilerOptions(no_symlink=True)
_OUTPUT_A = "data/test/function/main/a.mcfunction"
_OUTPUT_B = "data/test/function/main/b.mcfunction"
_LINKED_OUTPUT = "data/test/function/linked/b/b.mcfunction"


# Chdir into an empty datapack directory
@pytest.fixture(autouse=True)
def pack_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pack = tmp_path / "pack"
    (pack / "data").mkdir(parents=True)
    (pack / "pack.mcmeta").write_text('{"pack": {"min_format": 107}}', encoding="utf-8")
    monkeypatch.chdir(pack)
    return pack


# Folder outside the pack for symlinks to point at
@pytest.fixture
def outside(tmp_path: Path) -> Path:
    path = tmp_path / "outside"
    path.mkdir()
    return path


# Make `link` a symlink to `target`, skipping the test where symlinks can't be created (Windows without privilege)
def _symlink(target: Path, link: str) -> None:
    Path(link).parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as err:
        pytest.skip(f"cannot create symlinks here: {err}")


# Write `contents` to `path`, creating parent folders
def _write(path: Path | str, contents: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(contents, encoding="utf-8")


# Compile the pack on disk. Returns each error's message, without the file and line suffix.
def _compile(options: blocklight.CompilerOptions = _NO_SYMLINK) -> list[str]:
    return [error.msg for error in blocklight.Pack(options).compile().errors]


def test_symlinked_source_folder_is_refused_and_siblings_still_compile(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    _write(outside / "b.bl", "function b\n    say b\n")
    _symlink(outside, "data/test/blocklight/linked")
    errors = _compile()
    assert errors == [
        f"Refusing to follow '{os.path.join('data/test/blocklight', 'linked')}': the path contains a symlink."
    ]
    assert Path(_OUTPUT_A).is_file()
    assert not Path(_LINKED_OUTPUT).exists()


def test_symlinked_source_file_is_refused(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    _write(outside / "b.bl", "function b\n    say b\n")
    _symlink(outside / "b.bl", "data/test/blocklight/b.bl")
    errors = _compile()
    assert errors == [
        f"Refusing to read '{os.path.join('data/test/blocklight', 'b.bl')}': the path contains a symlink."
    ]
    assert Path(_OUTPUT_A).is_file()
    assert not Path("data/test/function/b").exists()


def test_writes_through_a_symlinked_output_folder_are_refused(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    _symlink(outside, "data/test/function")
    errors = _compile()
    assert errors == [f"Refusing to write '{_OUTPUT_A}': the path contains a symlink."]
    assert list(outside.iterdir()) == []


def test_symlinked_stale_output_is_not_deleted(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\nfunction b\n    say b\n")
    assert _compile() == []
    target = outside / "b.mcfunction"
    target.write_text(Path(_OUTPUT_B).read_text(encoding="utf-8"), encoding="utf-8")  # carries the header
    os.remove(_OUTPUT_B)
    _symlink(target, _OUTPUT_B)
    _write(SOURCE_FILE, "function a\n    say a\n")
    errors = _compile()
    assert errors == [f"Refusing to delete stale file '{_OUTPUT_B}': the path contains a symlink."]
    assert Path(_OUTPUT_B).is_symlink()
    assert target.is_file()


def test_manifest_path_cannot_delete_outside_the_pack_through_a_symlink(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    (outside / "sub").mkdir()
    victim = outside / "victim.mcfunction"
    victim.write_text(f"# {blocklight.Compile.HEADER_MARKER}\nsay mine", encoding="utf-8")
    _symlink(outside / "sub", "data/test/function/link")
    manifest = {
        "version": list(blocklight._BL_VERSION),  # pyright: ignore[reportPrivateUsage]
        "load": [],
        "tick": [],
        "sources": {SOURCE_FILE: {"outputs": ["data/test/function/link/../victim.mcfunction"]}},
    }
    _write(".blocklight-manifest.json", json.dumps(manifest))
    _compile()
    assert victim.is_file()


def test_links_added_between_compiles_in_one_process_are_caught(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    assert _compile() == []
    os.rename("data/test/function", outside / "function")
    _symlink(outside / "function", "data/test/function")
    _write(SOURCE_FILE, "function a\n    say changed\n")  # unchanged sources reuse their outputs without writing
    assert _compile() == [f"Refusing to write '{_OUTPUT_A}': the path contains a symlink."]


def test_symlinks_are_followed_by_default(outside: Path):
    _write(SOURCE_FILE, "function a\n    say a\n")
    _write(outside / "b.bl", "function b\n    say b\n")
    _symlink(outside, "data/test/blocklight/linked")
    assert _compile(blocklight.CompilerOptions()) == []
    assert Path(_LINKED_OUTPUT).is_file()


def test_each_path_is_checked_at_most_once_per_compile(monkeypatch: pytest.MonkeyPatch):
    for name in ("one", "two", "three"):
        functions = "".join(f"function {name}_{i}\n    if score @s v matches {i}\n        say {i}\n" for i in range(5))
        _write(f"data/test/blocklight/shared/{name}.bl", functions)
    calls: Counter[str] = Counter()
    real_lstat = os.lstat

    def counting_lstat(path: str, *args: object, **kwargs: object) -> os.stat_result:
        calls[os.fspath(path)] += 1
        return real_lstat(path, *args, **kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(os, "lstat", counting_lstat)
    assert _compile() == []
    assert calls, "no symlink checks ran"
    assert max(calls.values()) == 1, [path for path, count in calls.items() if count > 1]
