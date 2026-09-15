# Output paths must stay inside the source file's own namespace's function directory.

import blocklight
from tests.helpers import reset_for_test, stub_disk_writes

_LINE = blocklight._Line("function evil:", 1)  # pyright: ignore[reportPrivateUsage]


def test_output_path_outside_namespace_is_rejected():
    reset_for_test()
    blocklight.orchestration.write_output_file(
        "data/other_ns/function/evil.mcfunction", "say hi", _LINE, "data/ns/blocklight/x.bl", "ns"
    )
    assert blocklight.orchestration.get_files() == frozenset()
    errors = blocklight.tui.get_errors()
    assert len(errors) == 1
    assert isinstance(errors[0], blocklight.BLFileError)
    assert errors[0].filename == "data/ns/blocklight/x.bl"


def test_output_path_traversal_is_rejected():
    reset_for_test()
    blocklight.orchestration.write_output_file(
        "data/ns/function/../../other_ns/function/evil.mcfunction",
        "say hi",
        _LINE,
        "data/ns/blocklight/x.bl",
        "ns",
    )
    assert blocklight.orchestration.get_files() == frozenset()
    assert len(blocklight.tui.get_errors()) == 1
    assert isinstance(blocklight.tui.get_errors()[0], blocklight.BLFileError)


def test_output_path_inside_namespace_is_accepted():
    reset_for_test()
    with stub_disk_writes() as written:
        blocklight.orchestration.write_output_file(
            "data/ns/function/sub/dir/f.mcfunction", "say hi", _LINE, "data/ns/blocklight/x.bl", "ns"
        )
        blocklight.orchestration.wait_for_writes()
    assert blocklight.tui.get_errors() == []
    assert written == {"data/ns/function/sub/dir/f.mcfunction": "say hi"}
