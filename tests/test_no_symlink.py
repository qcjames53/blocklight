# --no-symlink: refuses to follow symlinked directories or read symlinked source files.

import json
import os

import blocklight
from tests.helpers import run_compile, scratch_dir


def _write_pack() -> None:
    with open("pack.mcmeta", "w", encoding="utf-8") as f:
        json.dump({"pack": {"min_format": 1}}, f)


def test_symlinked_file_is_followed_by_default():
    with scratch_dir():
        _write_pack()
        os.makedirs("data/ns/blocklight")
        with open("real.bl", "w", encoding="utf-8") as f:
            f.write("function hello:\n    say hi\n")
        os.symlink(os.path.abspath("real.bl"), "data/ns/blocklight/link.bl")
        result = run_compile(blocklight.CompilerOptions(no_header=True, dry_run=True))
    assert result.errors == []
    assert result.files == {"data/ns/function/link/hello.mcfunction"}


def test_symlinked_file_is_refused_with_no_symlink():
    with scratch_dir():
        _write_pack()
        os.makedirs("data/ns/blocklight")
        with open("real.bl", "w", encoding="utf-8") as f:
            f.write("function hello:\n    say hi\n")
        os.symlink(os.path.abspath("real.bl"), "data/ns/blocklight/link.bl")
        result = run_compile(blocklight.CompilerOptions(no_header=True, dry_run=True, no_symlink=True))
    assert result.files == frozenset()
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLSyntaxError)


def test_symlinked_directory_is_refused_with_no_symlink():
    with scratch_dir():
        _write_pack()
        os.makedirs("real_dir")
        with open("real_dir/hidden.bl", "w", encoding="utf-8") as f:
            f.write("function hello:\n    say hi\n")
        os.makedirs("data/ns/blocklight")
        os.symlink(os.path.abspath("real_dir"), "data/ns/blocklight/linked_dir")
        result = run_compile(blocklight.CompilerOptions(no_header=True, dry_run=True, no_symlink=True))
    assert result.files == frozenset()
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], blocklight.BLSyntaxError)
