# Blocklight - Vanilla mcfunction with structure

## This will be the best mcfunction compiler you've ever used
Well, "best" is relative. There are probably hundreds of mcfunction compilers that will make raycasters or adventure map triggers really easy to implement. The issue comes when you push a little outside the capabilities of your compiler and try to do something no one has done before: you end up writing vanilla mcfunction syntax anyways. Stop fighting your tools.

Blocklight robustly solves these problems:
- Multiple functions within one file.
- Flow control within functions using conditional blocks (if, elif, while, etc).
- Execution context modification using modifier blocks (as, at, in, positioned, etc).
- Function macros are usable across an ENTIRE function, including from within internal blocks.
- Return commands return across their ENTIRE function, including from within internal blocks.

Outside of some syntactic sugar, this is everything. I promise you won't miss a thing.

## You already know the syntax
Blocklight stays out of your way. It's really fast. It's really intuitive. Your datapack will almost certainly still work after any Minecraft update. And the syntax is essentially just vanilla functions but more intuitive.

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

## This compiler will (probably) never break
Blocklight enforces the minimum amount of command syntax it can. The compiler has no idea what any command is or does. That's intentional. The world doesn't need another outdated, unmaintained command compiler refusing to build because the latest `/particle` syntax changed.


© 2026 by Quinn James. Licensed under [GNU GPL v3](LICENSE)