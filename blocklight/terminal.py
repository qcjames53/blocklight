import sys
from pathlib import Path

from .compiler import Compiler, CompileHooks


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: blocklight <pack_path>", file=sys.stderr)
        sys.exit(1)

    pack_path = Path(sys.argv[1])

    hooks = CompileHooks(
        on_file_start=lambda path: print(f"Compiling {path.name}..."),
        on_file_done=lambda path, outputs: print(f"  -> {len(outputs)} file(s) written"),
        on_error=lambda path, err: print(f"Error in {path.name}: {err}", file=sys.stderr),
        on_complete=lambda success, failed: print(
            f"\nDone: {success} succeeded, {failed} failed"
        ),
    )

    Compiler(hooks=hooks).compile(pack_path)


if __name__ == "__main__":
    main()
