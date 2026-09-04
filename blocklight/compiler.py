from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class CompileHooks:
    on_file_start: Callable[[Path], None] = field(default=lambda _: None)
    on_file_done: Callable[[Path, list[Path]], None] = field(default=lambda _p, _o: None)
    on_error: Callable[[Path, Exception], None] = field(default=lambda _p, _e: None)
    on_complete: Callable[[int, int], None] = field(default=lambda _s, _f: None)


class Compiler:
    def __init__(self, hooks: CompileHooks | None = None) -> None:
        self.hooks = hooks or CompileHooks()

    def compile(self, pack_path: Path) -> None:
        bl_files = sorted(pack_path.rglob("blocklight/*.bl"))
        success, failed = 0, 0
        for bl_file in bl_files:
            try:
                self.hooks.on_file_start(bl_file)
                output_files = self.compile_file(bl_file)
                self.hooks.on_file_done(bl_file, output_files)
                success += 1
            except Exception as e:
                self.hooks.on_error(bl_file, e)
                failed += 1
        self.hooks.on_complete(success, failed)

    def compile_file(self, bl_file: Path) -> list[Path]:
        raise NotImplementedError
