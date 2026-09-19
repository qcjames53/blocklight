# `if` / `elif` / `else` Design

## Problem
JMC sets its "matched" flag as the first line *inside* the branch's own function body. If that body is a macro call whose macro fails to resolve, the call silently no-ops, the flag never gets set, and `elif`/`else` wrongly fire even though the `if` matched.

## Fix
Each condition directly gates `return run function <branch>` inside a dedicated dispatcher helper. Matching exits the dispatcher immediately, before the branch body runs — nothing the branch does afterward (succeed, fail, silently no-op) can undo that exit, and no later condition ever fires once an earlier one matched. Needs no shared state.

## Dispatcher (2+ branches)
- Chain compiles to its own dispatcher helper function, called unconditionally from the parent: `function <dispatcher>` (or `execute store result/success ... run function <dispatcher>` + `with {macros}` if the chain can return / uses macros — same convention as any other child call).
- Dispatcher body, one line per branch, in source order:
  - `execute if <condN> run return run function <branchN_helper>` for `if` and every `elif`.
  - `return run function <else_helper>` (unconditional, last line, only if `else` present).
- Each condition evaluated at most once; matching one exits the dispatcher immediately via vanilla `return`, before that branch's body runs.

## Bare `if` (no `elif`/`else`)
Skip the holder entirely. Compiles exactly like an existing modifier block: `execute if <cond> run function <helper>`.

## Example compiled output

Source:
```
function example:
    if (score @a var matches 5):
        say a
    elif (score @a var matches 6):
        say b
    else:
        say c
```

`pack:main/example.mcfunction`:
```
function pack:main/example_helper/if_0
```

`pack:main/example_helper/if_0.mcfunction` (dispatcher):
```
execute if score @a var matches 5 run return run function pack:main/example_helper/if_0_helper/if_0
execute if score @a var matches 6 run return run function pack:main/example_helper/if_0_helper/elif_0
return run function pack:main/example_helper/if_0_helper/else_0
```

`.../if_0_helper/if_0.mcfunction`: `say a`
`.../if_0_helper/elif_0.mcfunction`: `say b`
`.../if_0_helper/else_0.mcfunction`: `say c`

Bare `if`, no `elif`/`else` (no dispatcher) — `pack:main/example2.mcfunction`:
```
execute if score @a var matches 5 run function pack:main/example2_helper/if_0
```

Returning branches — source:
```
function example3:
    if (score @a var matches 5):
        return 1
    else:
        return 2
```

`pack:main/example3.mcfunction`:
```
scoreboard players set #_bl_returning _bl 0
execute store result score #_bl_value _bl store success score #_bl_success _bl run function pack:main/example3_helper/if_0
execute if score #_bl_returning _bl matches 1 if score #_bl_success _bl matches 1 run return run scoreboard players get #_bl_value _bl
execute if score #_bl_returning _bl matches 1 if score #_bl_success _bl matches 0 run return fail
```

`pack:main/example3_helper/if_0.mcfunction` (dispatcher — no per-branch return bookkeeping needed):
```
execute if score @a var matches 5 run return run function pack:main/example3_helper/if_0_helper/if_0
return run function pack:main/example3_helper/if_0_helper/else_0
```

`.../if_0_helper/if_0.mcfunction`:
```
scoreboard players set #_bl_returning _bl 1
return 1
```

`.../if_0_helper/else_0.mcfunction`:
```
scoreboard players set #_bl_returning _bl 1
return 2
```

## Condition parsing
- Strip exactly one fully-wrapping outer `(...)` pair; otherwise pass through unchanged.
- If what's left still has top-level `and`/`or`, or a leading `!(`: raise
  `BLSyntaxError("Boolean composition ('and'/'or'/'!') in conditions is not yet implemented.")`.

## Parser changes
- `_compile_lines`: materialize spans to a list, switch to an index-based loop (was a generator `for` loop).
- On `if`: greedily consume following same-depth `elif`* then an optional single `else` into one chain group; hand the group to a new `_compile_if_chain`.
- A standalone `elif`/`else` (not consumed into a chain) is an error: *"An 'elif'/'else' block must immediately follow an 'if' or 'elif' block."*
- Existing per-span validation (body required, trailing `:`, param requirements) is unchanged and runs per span before grouping.

## Return / macro propagation
- Dispatcher aggregates `can_return`/macros across all its branches (plus any macros the condition text itself references). The parent wraps its one call to the dispatcher with the existing `store result`/`store success`/`#_bl_returning` check and `with {macros}` clause — applied once, not per branch.
- No per-branch return-check needed inside the dispatcher: `return run function <branch>` already forwards that branch's own result/success as the dispatcher's, the instant it fires.

## Helper file naming
- Chain (2+ branches): dispatcher is `if_N` (existing `counts["if"]`); its branches nest one level deeper — `if_N_helper/if_0`, `elif_0`, `elif_1`, `else_0` (fresh `counts` dict, same convention as any nested block).
- Bare `if` (no elif/else): no dispatcher — `if_N` is the branch body directly, identical to a modifier block's child.

## Known test fallout
- `tests/example_pack/.../binary_search.bl`: the line-4 `if` will now compile; the function will instead fail on the `!(...) && (...)` line. Update `test_integration.py`'s expected error fragment/line and re-verify `_EXPECTED_MISSING_FILES`.
- `fizzbuzz.bl` still fails to compile (blocked on unimplemented `while`) — no change expected there.
