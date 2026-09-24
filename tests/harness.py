# Compiles bl source into a temporary datapack and runs the output on the mcrt interpreter.

import contextlib
import os
import tempfile
from collections.abc import Generator, Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

import blocklight
from tests.mcrt import DEFAULT_COMMAND_LIMIT, Machine, McrtError, Message, Result, SnbtValue

NAMESPACE = "test"
PACK_NAME = "pack"
SOURCE_FILE = f"data/{NAMESPACE}/blocklight/main.bl"
_PACK_MCMETA = '{"pack": {"description": "Blocklight test pack", "min_format": 107}}'
_DEFAULT_OPTIONS = blocklight.CompilerOptions()
_RESERVED_OBJECTIVE = "_bl"  # Stands in for compiler-emitted setup until the compiler creates it


# Outcome of one Pack.call
class Run(NamedTuple):
    result: Result | None  # None if the function never returned
    messages: list[Message]
    scores: dict[str, dict[str, int]]  # objective -> holder -> value
    commands_executed: int
    trace: list[str]  # each function entered and line run, indented by call depth

    # Text of each 'say' message, in order
    @property
    def said(self) -> list[str]:
        return [message.text for message in self.messages if message.command == "say"]

    # Score of `holder` on `objective`, or None if unset
    def score(self, holder: str, objective: str) -> int | None:
        return self.scores.get(objective, {}).get(holder)


# Compiled datapack output
class Pack(NamedTuple):
    functions: dict[str, list[str]]  # function id -> command lines, comments and blanks removed
    errors: list[blocklight.BLError]
    load_functions: frozenset[str]  # function ids
    tick_functions: frozenset[str]  # function ids

    # Run `function` after creating `objectives`, setting `scores` and running load functions.
    # A bare name resolves to test:main/<name>, else test:<name>.
    def call(
        self,
        function: str,
        *,
        macros: Mapping[str, SnbtValue] | None = None,
        objectives: Iterable[str] = (),
        scores: Mapping[tuple[str, str], int] | None = None,
        conditions: Mapping[str, bool] | None = None,
        command_limit: int = DEFAULT_COMMAND_LIMIT,
    ) -> Run:
        machine = Machine(self.functions, conditions=conditions, command_limit=command_limit)
        for objective in [_RESERVED_OBJECTIVE, *objectives]:
            machine.scores.setdefault(objective, {})
        for (holder, objective), value in (scores or {}).items():
            machine.scores.setdefault(objective, {})[holder] = value
        for load_function in sorted(self.load_functions):
            machine.call(load_function)
        machine.messages.clear()
        machine.commands_executed = 0
        machine.trace.clear()
        result = machine.call(self.resolve(function), macros)
        return Run(result, machine.messages, machine.scores, machine.commands_executed, machine.trace)

    # Function id of `function`: ids pass through, bare names try test:main/<name> then test:<name>
    def resolve(self, function: str) -> str:
        if ":" in function:
            return function
        for candidate in (f"{NAMESPACE}:main/{function}", f"{NAMESPACE}:{function}"):
            if candidate in self.functions:
                return candidate
        raise McrtError(f"No compiled function named '{function}'")


# Chdir into a fresh temporary directory named PACK_NAME, deleted on exit
@contextlib.contextmanager
def _pack_dir() -> Generator[Path, None, None]:
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        pack_dir = Path(tmp_dir) / PACK_NAME
        pack_dir.mkdir()
        os.chdir(pack_dir)
        try:
            yield pack_dir
        finally:
            os.chdir(original_cwd)


# Function id of a compiled output path relative to the pack root
def _function_id(relative_path: Path) -> str:
    _data, namespace, _function, *rest = relative_path.with_suffix("").parts
    return f"{namespace}:{'/'.join(rest)}"


# Compile `source` (SOURCE_FILE contents, or pack-relative path -> contents) with a full discovery pass
def build(source: str | Mapping[str, str], *, options: blocklight.CompilerOptions = _DEFAULT_OPTIONS) -> Pack:
    sources = {SOURCE_FILE: source} if isinstance(source, str) else source
    with _pack_dir() as pack_dir:
        (pack_dir / "pack.mcmeta").write_text(_PACK_MCMETA, encoding="utf-8")
        for local_path, contents in sources.items():
            path = pack_dir / local_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")

        blocklight.reset_globals()
        blocklight.tui.set_options(options)
        blocklight.orchestration.run()

        functions: dict[str, list[str]] = {}
        for path in sorted((pack_dir / "data").glob("*/function/**/*.mcfunction")):
            lines = path.read_text(encoding="utf-8").split("\n")
            functions[_function_id(path.relative_to(pack_dir))] = [
                line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")
            ]
        return Pack(
            functions=functions,
            errors=blocklight.tui.get_errors(),
            load_functions=frozenset(_function_id(Path(p)) for p in blocklight.orchestration.get_load_functions()),
            tick_functions=frozenset(_function_id(Path(p)) for p in blocklight.orchestration.get_tick_functions()),
        )


# Compiled pack of `source`. Fails the test on any compile error.
def compile_pack(source: str | Mapping[str, str], *, options: blocklight.CompilerOptions = _DEFAULT_OPTIONS) -> Pack:
    pack = build(source, options=options)
    assert pack.errors == [], f"Unexpected compile errors: {[f'{type(e).__name__}: {e}' for e in pack.errors]}"
    return pack


# The single compile error of `source`. Fails the test unless exactly one error is raised.
def compile_error(
    source: str | Mapping[str, str], *, options: blocklight.CompilerOptions = _DEFAULT_OPTIONS
) -> blocklight.BLError:
    pack = build(source, options=options)
    assert len(pack.errors) == 1, f"Expected one compile error, got {[str(e) for e in pack.errors]}"
    return pack.errors[0]
