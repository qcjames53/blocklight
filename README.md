# Blocklight - A blazing fast mcfunction microcompiler

Blocklight is a Minecraft Java Edition datapack microcompiler which aims to be quicker, more useful, and syntax-divorced than other datapack compilers. Blocklight solves these core issues and stays out of your way for everything else:

- Multiple functions within one file, each robustly supporting function macros and return commands from ANYWHERE inside the function.
- Flow control within functions using conditional statements (if, elif, while, etc).
- Execution context modification using modifiers (as, at, in, positioned, etc).
- Inline Python for robust pre-compile output (useful for pre-computed loops or complex math)
- Strong focus on speed and optimization (big datapacks usually compile in under 20ms)

## Quick start, aka WHERE IS MY EXE?
1. Install Python on your system from your package manager or https://python.org.
    - Python 3.10 or higher is required.
2. [Download Blocklight 1.0](https://github.com/qcjames53/blocklight/releases/download/v1.0/blocklight.py).
3. Copy `blocklight.py` to your datapack's top level directory (e.g. `my_pack/blocklight.py`).
4. Create your .bl source files in `<pack>/data/<namespace>/blocklight/`.
    - See the [example datapack](https://github.com/qcjames53/blocklight/tree/main/example_datapack) for example source files.
5. Run the compiler in the terminal from your datapack's top level directory with `python3 blocklight.py` (all operating systems) or `./blocklight.py` (secret shortcut for MacOS and Linux).

## I promise this will be the best mcfunction compiler you've ever used
Well, "best" is relative. I promise you'll really enjoy using Blocklight, though. 

There are probably dozens of other mcfunction compilers that will make raycasting or location triggers dead easy. The problem with the alternative compilers is you need to abide by a rigid, opinionated syntax which more or less still has all the drawbacks of vanilla mcfunction once compiled. When you walk a little off the happy path, everything falls apart. Blocklight enforces the minimum syntax required to output a valid datapack. The world doesn't need another outdated, unmaintained command compiler refusing to build because the datapack format updated again and changed the syntax of the `swing` command. Blocklight doesn't even know what a command _is_. That's intentional.

In a similiar vein, we don't need a worse version of Python to help build functions. Need to clear a forest chunk by chunk? Use Python. Need to build a binary search for a specific NBT tag? Use Python. We have a tool that can emit the same command 200 times in a row. It's called Python. If Python can do something at compile-time, let's use it.

## Contributor guidelines
Contributions and issues are more than welcome! I'll try to get to everything as quickly as I can.

When developing changes, please keep these tenets in mind:
1. Mcfunction is not a normal language, so a normal compiler is the wrong tool; blocklight syntax must allow for messy mcfunction cleverness without binding datapack authors to a structured "happy path".
2. The compiler must remain portable, distributable, free, and broadly compatible with future Minecraft updates.
3. Compile operations must remain accurate, idempotent, resource efficient, and output must co-exist peacefully with files the user has hand-created.
4. Failures are recoverable on re-compile, clear to understand, and isolated to a single function where possible.
5. The language model must maintain broadly independent source files.
6. Custom compiler-only behavior should take the form of a one line command or block header with a leading reserved keyword. Indentation indicates block contents.
7. Avoid parsing vanilla command syntax wherever possible. Pass it through. Minecraft updates can easily break things.
8. Don't delete or modify any file unless Blocklight created it. Exceptions (e.g. load/tick tags) must be very robust.
9. Vanilla function macros and vanilla return commands are to be supported everywhere, no exceptions.

---

Thank you very much for reading all of this! I look forward to seeing what you all create! - Quinn

© 2026 by Quinn James. Licensed under [GNU GPL v3](LICENSE)