# Times full compiles of a large pack built from N copies of the example pack's bl sources, one namespace per copy.
# Not collected by pytest. Run from the repo root: `python3 -m tests.benchmark [--copies 200] [--reps 7]`.

import argparse
import json
import os
import shutil
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import blocklight

_EXAMPLE_PACK = Path(__file__).resolve().parent.parent / "example_datapack"
_EXAMPLE_SOURCES = _EXAMPLE_PACK / "data" / "bl_example" / "blocklight"
_MANIFEST = Path(blocklight.Pack._MANIFEST_FILENAME)  # pyright: ignore[reportPrivateUsage]


# Fill `pack` with pack.mcmeta and `copies` namespaces, each holding every example bl source.
def _build_pack(pack: Path, copies: int) -> int:
    shutil.copy(_EXAMPLE_PACK / "pack.mcmeta", pack)
    for i in range(copies):
        shutil.copytree(_EXAMPLE_SOURCES, pack / "data" / f"ns{i}" / "blocklight")
    return sum(1 for _ in pack.glob("data/*/blocklight/**/*.bl"))


# Compile the pack in the working directory and print its receipt. Returns elapsed milliseconds.
def _compile(options: blocklight.CompilerOptions) -> float:
    start = time.perf_counter()
    result = blocklight.Pack(options).compile()
    elapsed = time.perf_counter() - start
    print("  ", end="")
    blocklight.report(result, elapsed)  # untimed
    if result.errors:
        raise SystemExit(f"Benchmark compile failed: {[str(error) for error in result.errors]}")
    return elapsed * 1000


# Drop every source hash from the manifest so the next compile recompiles all sources.
def _invalidate_source_hashes() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    for entry in manifest["sources"].values():
        entry.pop("source_hash", None)
    _MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")


# Delete every compiled output, tag and the manifest, leaving only pack.mcmeta and bl sources.
def _delete_outputs() -> None:
    for path in Path("data").glob("**/*"):
        if path.is_file() and path.suffix in (".mcfunction", ".json"):
            path.unlink()
    _MANIFEST.unlink(missing_ok=True)


# Median milliseconds of `reps` compiles, running `setup` (untimed) before each.
def _median_ms(options: blocklight.CompilerOptions, setup: Callable[[], None], reps: int) -> float:
    times: list[float] = []
    for _ in range(reps):
        setup()
        times.append(_compile(options))
    return statistics.median(times)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Blocklight compiles of a scaled-up example pack.")
    parser.add_argument("--copies", type=int, default=200, help="copies of the example sources (default 200)")
    parser.add_argument("--reps", type=int, default=7, help="compiles per scenario; the median is reported")
    parser.add_argument("--no-symlink", action="store_true", help="compile with symlink checks on")
    args = parser.parse_args()
    options = blocklight.CompilerOptions(no_symlink=args.no_symlink)

    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / "benchmark_pack"  # the receipt names the pack after its folder
        pack.mkdir()
        sources = _build_pack(pack, args.copies)
        previous_cwd = os.getcwd()
        os.chdir(pack)  # contextlib.chdir needs 3.11
        try:
            print(f"{sources} sources, {args.reps} runs per scenario\n")
            print("Prime (fills outputs and manifest):")
            _compile(options)
            scenarios: list[tuple[str, Callable[[], None]]] = [
                ("Cached (source hashes match)", lambda: None),
                ("Recompile all, outputs unchanged", _invalidate_source_hashes),
                ("Compile from scratch", _delete_outputs),
            ]
            medians: list[tuple[str, float]] = []
            for label, setup in scenarios:
                print(f"{label}:")
                medians.append((label, _median_ms(options, setup, args.reps)))
            outputs = sum(1 for _ in Path("data").glob("*/function/**/*.mcfunction"))
            print(f"\nMedians ({sources} sources, {outputs} outputs):")
            for label, median in medians:
                print(f"  {label:34} {median:8.1f} ms")
        finally:
            os.chdir(previous_cwd)


if __name__ == "__main__":
    main()
