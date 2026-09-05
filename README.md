# Blocklight - A blazing fast mcfunction microcompiler

## This will be the best mcfunction compiler you've ever used
Well, "best" is relative. There are probably dozens of other mcfunction compilers that will make raycasting or location triggers dead easy. The problem with the alternative compilers is you need to abide by a rigid, opinionated syntax which more or less still has all the drawbacks of vanilla mcfunction once compiled. When you walk a little off the happy path, everything falls apart.

Blocklight is a microcompiler which robustly solves these problems:
- Multiple functions within one file.
- Flow control within functions using conditional blocks (if, elif, while, etc).
- Execution context modification using modifier blocks (as, at, in, positioned, etc).
- Function macros are usable across an ENTIRE function, including from within internal blocks.
- Return commands return across their ENTIRE function, including from within internal blocks.

## You already know the rules
BECAUSE THERE AREN'T ANY.

Sorry about that. Of course there are rules. But Blocklight enforces the minimum syntax it can to output a valid script. The world doesn't need another outdated, unmaintained command compiler refusing to build because the latest `/particle` syntax changed. Blocklight doesn't even know what a command _is_. That's intentional.

```
function aloha:
    if score #is_entering example_var matches 1..:
        say hi!
    else:
        say bye!
```

## Pre-computation and complex math uses a real programming language
We don't need a worse version of Python to help build functions. Need to clear a forest chunk by chunk? Use Python. Need to build a binary search for a specific NBT tag? Use Python. We have a tool that can emit the same command 200 times in a row. It's called Python. If Python can do something at compile-time, let's use it.

```
function clear_chunk:
    python:
        for i in range(16):
            for j in range(16):
                x = f"~{i}" if i != 0 else "~"
                z = f"~{j}" if j != 0 else "~"
                emit(f"fill {x} -63 {z} {x} 319 {z} air")
```


© 2026 by Quinn James. Licensed under [GNU GPL v3](LICENSE)