# Minimal Minecraft command interpreter for behavior tests. Supports say, tellraw, function, return, execute and
# scoreboard, following Java Edition 26.3 semantics. Anything unsupported raises McrtError.

import re
from collections.abc import Mapping
from typing import NamedTuple, NoReturn, TypeAlias

_INT_MIN = -(2**31)
_INT_MAX = 2**31 - 1
DEFAULT_COMMAND_LIMIT = 65536  # vanilla maxCommandChainLength

# Subcommand -> argument token count. 'positioned as|over' takes 2 instead of 3.
_MODIFIER_ARITY = {
    "align": 1,
    "anchored": 1,
    "as": 1,
    "at": 1,
    "facing": 3,
    "in": 1,
    "on": 1,
    "positioned": 3,
    "rotated": 2,
    "summon": 1,
}
# Stubbed condition kind -> argument token count
_STUB_CONDITION_ARITY = {
    "biome": 4,
    "block": 4,
    "blocks": 10,
    "dimension": 1,
    "entity": 1,
    "loaded": 3,
    "predicate": 1,
}
_SCORE_COMPARISONS = frozenset(("<", "<=", "=", ">", ">="))
_SNBT_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?([bBsSlLfFdD]?)")

SnbtValue: TypeAlias = "str | int | float | list[SnbtValue] | dict[str, SnbtValue]"


# Unsupported or malformed command. Signals a test or interpreter bug, never in-game behavior.
class McrtError(Exception):
    pass


# One line of chat output
class Message(NamedTuple):
    command: str  # "say" or "tellraw"
    text: str  # say message, or raw tellraw JSON component
    context: tuple[str, ...]  # execute modifiers active when sent, outermost first


# Result of a command or a returning function
class Result(NamedTuple):
    success: bool
    value: int


_FAIL = Result(False, 0)


# Unwinds to the enclosing function with its return result
class _Return(Exception):
    def __init__(self, result: Result) -> None:
        self.result = result


# Unwinds to the enclosing function, which returns the callee's result in its place
class _TailCall(Exception):
    def __init__(self, function_id: str, args: dict[str, SnbtValue] | None, context: tuple[str, ...]) -> None:
        self.function_id = function_id
        self.macro_args = args
        self.context = context


# Command failed in-game (e.g. unknown objective)
class _CommandFailed(Exception):
    pass


# Whitespace tokenizer keeping [...], {...} and quoted strings whole
class _Reader:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def done(self) -> bool:
        return self._pos >= len(self._text)

    # Next token without consuming it, or "" at end
    def peek(self) -> str:
        pos = self._pos
        token = "" if self.done() else self.token()
        self._pos = pos
        return token

    def token(self) -> str:
        if self.done():
            raise McrtError(f"Unexpected end of command: '{self._text}'")
        start = i = self._pos
        depth = 0
        quote = ""
        while i < len(self._text):
            ch = self._text[i]
            if quote:
                if ch == "\\":
                    i += 1
                elif ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == " " and depth == 0:
                break
            i += 1
        self._pos = i + 1
        return self._text[start:i]

    def tokens(self, count: int) -> list[str]:
        return [self.token() for _ in range(count)]

    # Unconsumed remainder of the command
    def rest(self) -> str:
        rest = self._text[self._pos :]
        self._pos = len(self._text)
        return rest

    def int(self) -> int:
        token = self.token()
        try:
            return int(token)
        except ValueError:
            raise McrtError(f"Expected an integer but found '{token}' in '{self._text}'") from None


# Parse SNBT text. Numbers drop their type suffix; booleans become 1/0.
def parse_snbt(text: str) -> SnbtValue:
    pos = 0

    def skip_space() -> None:
        nonlocal pos
        while pos < len(text) and text[pos].isspace():
            pos += 1

    def expect(ch: str) -> None:
        nonlocal pos
        skip_space()
        if not text.startswith(ch, pos):
            raise McrtError(f"Expected '{ch}' at {pos} in SNBT '{text}'")
        pos += 1

    def string() -> str:
        nonlocal pos
        skip_space()
        if pos < len(text) and text[pos] in "\"'":
            quote = text[pos]
            pos += 1
            chars: list[str] = []
            while pos < len(text) and text[pos] != quote:
                if text[pos] == "\\":
                    pos += 1
                chars.append(text[pos])
                pos += 1
            expect(quote)
            return "".join(chars)
        start = pos
        while pos < len(text) and (text[pos].isalnum() or text[pos] in "_-.+"):
            pos += 1
        if start == pos:
            raise McrtError(f"Expected a value at {pos} in SNBT '{text}'")
        return text[start:pos]

    def value() -> SnbtValue:
        nonlocal pos
        skip_space()
        if text.startswith("{", pos):
            pos += 1
            compound: dict[str, SnbtValue] = {}
            skip_space()
            if text.startswith("}", pos):
                pos += 1
                return compound
            while True:
                key = string()
                expect(":")
                compound[key] = value()
                skip_space()
                if text.startswith("}", pos):
                    pos += 1
                    return compound
                expect(",")
        if text.startswith("[", pos):
            pos += 1
            items: list[SnbtValue] = []
            skip_space()
            if text.startswith("]", pos):
                pos += 1
                return items
            while True:
                items.append(value())
                skip_space()
                if text.startswith("]", pos):
                    pos += 1
                    return items
                expect(",")
        quoted = pos < len(text) and text[pos] in "\"'"
        raw = string()
        if quoted:
            return raw
        if raw in ("true", "false"):
            return int(raw == "true")
        match = _SNBT_NUMBER.fullmatch(raw)
        if match is None:
            return raw
        number = raw[: len(raw) - len(match.group(1))]
        if match.group(1).lower() in ("f", "d") or any(ch in number for ch in ".eE"):
            return float(number)
        return int(number)

    result = value()
    skip_space()
    if pos != len(text):
        raise McrtError(f"Unexpected '{text[pos:]}' after SNBT value in '{text}'")
    return result


# SNBT text for a macro substitution: strings bare, compounds and lists as SNBT.
def _format_macro_value(value: SnbtValue, nested: bool = False) -> str:
    if isinstance(value, str):
        return repr(value) if nested else value
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key}: {_format_macro_value(item, True)}" for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_format_macro_value(item, True) for item in value) + "]"
    return str(value)


# Wrap to a signed 32-bit int
def _wrap(value: int) -> int:
    return (value - _INT_MIN) % 2**32 + _INT_MIN


# Whether `value` falls in a vanilla int range ("1", "1..", "..1", "1..5")
def _in_range(value: int, range_text: str) -> bool:
    try:
        if ".." not in range_text:
            return value == int(range_text)
        low, high = range_text.split("..")
        return (not low or value >= int(low)) and (not high or value <= int(high))
    except ValueError:
        raise McrtError(f"Malformed range '{range_text}'") from None


# Executes compiled functions against an in-memory scoreboard, recording chat output.
class Machine:
    def __init__(
        self,
        functions: Mapping[str, list[str]],
        *,
        conditions: Mapping[str, bool] | None = None,
        command_limit: int = DEFAULT_COMMAND_LIMIT,
    ) -> None:
        self._functions = functions
        self._conditions = conditions or {}  # stubbed condition text (e.g. "entity @s[tag=a]") -> outcome
        self._command_limit = command_limit
        self.scores: dict[str, dict[str, int]] = {}  # objective -> holder -> value
        self.messages: list[Message] = []
        self.commands_executed = 0
        self.trace: list[str] = []  # each function entered and line run, indented by call depth
        self._depth = 0

    # Run function `function_id`. Returns its return result, or None if it never returned.
    def call(self, function_id: str, args: Mapping[str, SnbtValue] | None = None) -> Result | None:
        return self._call_function(function_id, dict(args) if args is not None else None, ())

    # Run one command at the top level. Returns its result, or None if void.
    def run(self, command: str) -> Result | None:
        try:
            return self._run(command, ())
        except (_Return, _TailCall):
            raise McrtError(f"'return' outside a function: '{command}'") from None

    # Score of `holder` on `objective`, or None if unset
    def score(self, holder: str, objective: str) -> int | None:
        return self.scores.get(objective, {}).get(holder)

    def _call_function(
        self, function_id: str, args: dict[str, SnbtValue] | None, context: tuple[str, ...]
    ) -> Result | None:
        tail_called = False
        indent = "  " * self._depth
        self._depth += 1
        try:
            while True:
                lines = self._instantiate(function_id, args)
                if lines is None:
                    self.trace.append(f"{indent}[{function_id}] failed: missing macro arguments")
                    return _FAIL
                self.trace.append(f"{indent}[{function_id}]")
                try:
                    for line in lines:
                        self.trace.append(f"{indent}  {line}")
                        self._run(line, context)
                except _Return as ret:
                    return ret.result
                except _TailCall as tail:
                    function_id, args, context = tail.function_id, tail.macro_args, tail.context
                    tail_called = True
                    continue
                return _FAIL if tail_called else None  # 'return run function' of a void function fails
        finally:
            self._depth -= 1

    # Function lines with macros substituted, or None if a macro argument is missing
    def _instantiate(self, function_id: str, args: dict[str, SnbtValue] | None) -> list[str] | None:
        if function_id not in self._functions:
            raise McrtError(f"Unknown function '{function_id}'")
        lines: list[str] = []
        for line in self._functions[function_id]:
            if not line.startswith("$"):
                lines.append(line)
                continue
            if args is None:
                return None
            text = line[1:]
            for name in re.findall(r"\$\(([A-Za-z0-9_]+)\)", text):
                if name not in args:
                    return None
                text = text.replace(f"$({name})", _format_macro_value(args[name]))
            lines.append(text)
        return lines

    def _run(self, command: str, context: tuple[str, ...]) -> Result | None:
        self.commands_executed += 1
        if self.commands_executed > self._command_limit:
            raise McrtError(f"Exceeded the command limit of {self._command_limit}")
        name, _, rest = command.partition(" ")
        try:
            if name == "say":
                self.messages.append(Message("say", rest, context))
                return Result(True, 1)
            if name == "tellraw":
                reader = _Reader(rest)
                reader.token()
                self.messages.append(Message("tellraw", reader.rest(), context))
                return Result(True, 1)
            if name == "function":
                return self._call_function(*self._function_target(rest), context)
            if name == "return":
                self._return(rest, context)
            if name == "execute":
                return self._execute(rest, context)
            if name == "scoreboard":
                return self._scoreboard(rest)
        except _CommandFailed:
            return _FAIL
        raise McrtError(f"Unsupported command: '{command}'")

    # Function id and macro arguments of a 'function' command's arguments
    @staticmethod
    def _function_target(rest: str) -> tuple[str, dict[str, SnbtValue] | None]:
        reader = _Reader(rest)
        function_id = reader.token()
        if reader.peek() == "with":
            reader.token()
            if reader.peek() != "" and not reader.peek().startswith("{"):
                raise McrtError(f"Only inline 'with {{...}}' macro arguments are supported: 'function {rest}'")
        if reader.done():
            return function_id, None
        args = parse_snbt(reader.rest())
        if not isinstance(args, dict):
            raise McrtError(f"Macro arguments must be a compound: 'function {rest}'")
        return function_id, args

    # Raises _Return or _TailCall
    def _return(self, rest: str, context: tuple[str, ...]) -> NoReturn:
        if rest == "fail":
            raise _Return(_FAIL)
        if rest.startswith("run "):
            command = rest[len("run ") :]
            if command.startswith("function "):
                raise _TailCall(*self._function_target(command[len("function ") :]), context)
            result = self._run(command, context)
            raise _Return(result if result is not None else _FAIL)
        reader = _Reader(rest)
        raise _Return(Result(True, reader.int()))

    def _execute(self, rest: str, context: tuple[str, ...]) -> Result | None:
        reader = _Reader(rest)
        stores: list[tuple[str, str, str]] = []  # (result|success, holder, objective)
        result: Result | None = None
        while True:
            subcommand = reader.token()
            if subcommand == "run":
                result = self._run_stored(reader.rest(), context, stores)
                break
            if subcommand in _MODIFIER_ARITY:
                arity = _MODIFIER_ARITY[subcommand]
                if subcommand == "positioned" and reader.peek() in ("as", "over"):
                    arity = 2
                context = (*context, f"{subcommand} {' '.join(reader.tokens(arity))}")
            elif subcommand in ("if", "unless"):
                passed = self._condition(reader, context) == (subcommand == "if")
                if reader.done():
                    result = Result(passed, int(passed))
                    break
                if not passed:
                    return _FAIL  # branch ends before 'run'; nothing is stored
            elif subcommand == "store":
                kind, target, holder, objective = reader.tokens(4)
                if kind not in ("result", "success") or target != "score":
                    raise McrtError(f"Only 'store result|success score' is supported: 'execute {rest}'")
                self._objective(objective)
                stores.append((kind, holder, objective))
            else:
                raise McrtError(f"Unsupported execute subcommand '{subcommand}': 'execute {rest}'")
            if reader.done():
                raise McrtError(f"Execute chain ends without 'run' or a condition: 'execute {rest}'")
        self._store(stores, result)
        return result

    # Run `command` under `stores`. A 'return' reports its result to `stores` before unwinding.
    def _run_stored(self, command: str, context: tuple[str, ...], stores: list[tuple[str, str, str]]) -> Result | None:
        if not stores:
            return self._run(command, context)
        try:
            return self._run(command, context)
        except _Return as ret:
            self._store(stores, ret.result)
            raise
        except _TailCall as tail:
            result = self._call_function(tail.function_id, tail.macro_args, tail.context)
            result = result if result is not None else _FAIL
            self._store(stores, result)
            raise _Return(result) from None

    # Write `result` to each store target. A void result stores nothing.
    def _store(self, stores: list[tuple[str, str, str]], result: Result | None) -> None:
        if result is None:
            return
        for kind, holder, objective in stores:
            self._objective(objective)[holder] = result.value if kind == "result" else int(result.success)

    # Evaluates an 'if'/'unless' test as if it were 'if'
    def _condition(self, reader: _Reader, context: tuple[str, ...]) -> bool:
        kind = reader.token()
        if kind == "score":
            holder, objective, operator = reader.tokens(3)
            value = self._objective(objective).get(holder)
            if operator == "matches":
                range_text = reader.token()
                return value is not None and _in_range(value, range_text)
            if operator not in _SCORE_COMPARISONS:
                raise McrtError(f"Unsupported score comparison '{operator}'")
            other_holder, other_objective = reader.tokens(2)
            other = self._objective(other_objective).get(other_holder)
            if value is None or other is None:
                return False
            return {
                "<": value < other,
                "<=": value <= other,
                "=": value == other,
                ">": value > other,
                ">=": value >= other,
            }[operator]
        if kind == "function":
            result = self._call_function(reader.token(), None, context)  # macro functions fail without args
            return result is not None and result.success and result.value != 0
        if kind in _STUB_CONDITION_ARITY:
            text = " ".join([kind, *reader.tokens(_STUB_CONDITION_ARITY[kind])])
            if text not in self._conditions:
                raise McrtError(f"No stubbed outcome for condition '{text}'")
            return self._conditions[text]
        raise McrtError(f"Unsupported condition '{kind}'")

    # Holder -> score map of `objective`. Raises _CommandFailed if it does not exist.
    def _objective(self, objective: str) -> dict[str, int]:
        if objective not in self.scores:
            raise _CommandFailed
        return self.scores[objective]

    def _scoreboard(self, rest: str) -> Result:
        reader = _Reader(rest)
        group, action = reader.tokens(2)
        if group == "objectives" and action == "add":
            name = reader.token()
            reader.rest()  # criteria and display name
            if name in self.scores:
                raise _CommandFailed
            self.scores[name] = {}
            return Result(True, len(self.scores))
        if group == "objectives" and action == "remove":
            name = reader.token()
            self._objective(name)
            del self.scores[name]
            return Result(True, len(self.scores))
        if group != "players":
            raise McrtError(f"Unsupported scoreboard command: 'scoreboard {rest}'")

        holder = reader.token()
        if action == "reset":
            objectives = [self._objective(reader.token())] if not reader.done() else list(self.scores.values())
            for scores in objectives:
                scores.pop(holder, None)
            return Result(True, 1)

        scores = self._objective(reader.token())
        if action == "get":
            if holder not in scores:
                raise _CommandFailed
            return Result(True, scores[holder])
        if action in ("set", "add", "remove"):
            amount = reader.int()
            current = scores.get(holder, 0)
            scores[holder] = _wrap({"set": amount, "add": current + amount, "remove": current - amount}[action])
            return Result(True, scores[holder])
        if action == "operation":
            operator, source_holder, source_objective = reader.tokens(3)
            source_scores = self._objective(source_objective)
            if source_holder not in source_scores:
                raise McrtError(f"Operation source '{source_holder} {source_objective}' has no score")
            target, source = scores.get(holder, 0), source_scores[source_holder]
            if operator == "><":
                scores[holder], source_scores[source_holder] = source, target
                return Result(True, source)
            operations = {
                "=": source,
                "+=": target + source,
                "-=": target - source,
                "*=": target * source,
                "/=": target // source if source else target,  # floorDiv; unchanged on division by zero
                "%=": target % source if source else target,  # floorMod; unchanged on division by zero
                "<": min(target, source),
                ">": max(target, source),
            }
            if operator not in operations:
                raise McrtError(f"Unsupported scoreboard operation '{operator}'")
            scores[holder] = _wrap(operations[operator])
            return Result(True, scores[holder])
        raise McrtError(f"Unsupported scoreboard command: 'scoreboard {rest}'")
