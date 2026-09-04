import json
import pytest
from blocklight.compiler import Compiler


class CompileResult:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    def assert_file(self, path: str, contents: str) -> None:
        assert path in self.files, f"{path!r} not generated. Got: {sorted(self.files)}"
        assert self.files[path] == contents

    def assert_file_contains(self, path: str, *substrings: str) -> None:
        assert path in self.files, f"{path!r} not generated. Got: {sorted(self.files)}"
        for s in substrings:
            assert s in self.files[path], f"{s!r} not found in {path!r}"

    def assert_only_files(self, *paths: str) -> None:
        assert set(self.files) == set(paths), (
            f"Expected: {sorted(paths)}\nGot:      {sorted(self.files)}"
        )


@pytest.fixture
def compile_bl(tmp_path):
    def _compile(
        filename: str,
        contents: str,
        *,
        namespace: str = "test",
        pack_name: str = "test",
        pack_format: int = 61,
    ) -> CompileResult:
        pack_root = tmp_path / pack_name
        bl_path = pack_root / "data" / namespace / "blocklight" / filename
        bl_path.parent.mkdir(parents=True, exist_ok=True)
        bl_path.write_text(contents)
        (pack_root / "pack.mcmeta").write_text(
            json.dumps({"pack": {"pack_format": pack_format, "description": ""}})
        )

        Compiler().compile(pack_root)

        function_dir = pack_root / "data" / namespace / "function"
        files = (
            {str(f.relative_to(function_dir)): f.read_text()
             for f in sorted(function_dir.rglob("*.mcfunction"))}
            if function_dir.exists() else {}
        )
        return CompileResult(files)

    return _compile
