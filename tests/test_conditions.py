# Every and/or/not combination of up to three score conditions, checked against Python's evaluation of the same
# expression for every input. Each expression compiles as a bare 'if' and an 'if'/'else', with and without macros.

import functools
import itertools
from collections.abc import Iterator

import pytest

from tests.harness import Pack, compile_pack

_PARAMS = ("a", "b", "c")
_OPS = ("and", "or")


# Expression text with '{a}' style placeholders per param
def _negations(text: str) -> Iterator[str]:
    yield text
    yield f"not {text}"


# Leaf placeholder, optionally negated
def _leaves(param: str) -> Iterator[str]:
    return _negations(f"{{{param}}}")


# Every expression over the first `count` params: bare precedence, and each grouping with optional group negation
def _expressions(count: int) -> Iterator[str]:
    params = _PARAMS[:count]
    for leaves in itertools.product(*(_leaves(p) for p in params)):
        if count == 1:
            yield leaves[0]
            continue
        for ops in itertools.product(_OPS, repeat=count - 1):
            if count == 2:
                bare = f"{leaves[0]} {ops[0]} {leaves[1]}"
                yield bare
                yield f"not ({bare})"
                continue
            a, b, c = leaves
            yield f"{a} {ops[0]} {b} {ops[1]} {c}"
            yield f"not ({a} {ops[0]} {b} {ops[1]} {c})"
            for left in _negations(f"({a} {ops[0]} {b})"):
                yield from _negations(f"({left} {ops[1]} {c})")
            for right in _negations(f"({b} {ops[1]} {c})"):
                yield from _negations(f"({a} {ops[0]} {right})")


EXPRESSIONS = [expr for count in (1, 2, 3) for expr in _expressions(count)]
_INPUTS = list(itertools.product((False, True), repeat=len(_PARAMS)))


# Every expression compiled as four functions: bare/else x plain/macro
@functools.cache
def _pack() -> Pack:
    source: list[str] = []
    for index, expr in enumerate(EXPRESSIONS):
        for macro in (False, True):
            value = "$(one)" if macro else "1"
            condition = expr.format(**{p: f"score #{p} v matches {value}" for p in _PARAMS})
            source += [f"function bare_{index}_{int(macro)}", f"    if {condition}", "        say taken"]
            source += [f"function else_{index}_{int(macro)}", f"    if {condition}", "        say taken"]
            source += ["    else", "        say skipped"]
    return compile_pack("\n".join(source) + "\n")


@pytest.mark.parametrize("index", range(len(EXPRESSIONS)), ids=EXPRESSIONS)
def test_condition_combination(index: int) -> None:
    expr = EXPRESSIONS[index]
    pack = _pack()
    for inputs in _INPUTS:
        values = dict(zip(_PARAMS, inputs))
        expected = eval(expr.format(**values))  # Python shares Blocklight's precedence: not > and > or
        scores = {(f"#{p}", "v"): int(value) for p, value in values.items()}
        for macro in (False, True):
            macros = {"one": 1} if macro else None
            bare = pack.call(f"bare_{index}_{int(macro)}", macros=macros, objectives=["v"], scores=scores)
            full = pack.call(f"else_{index}_{int(macro)}", macros=macros, objectives=["v"], scores=scores)
            label = f"{values} macro={macro}"
            assert bare.said == (["taken"] if expected else []), label
            assert full.said == (["taken"] if expected else ["skipped"]), label
