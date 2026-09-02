# Blocklight - Vanilla mcfunction with structure

## This will be the best mcfunction compiler you've ever used
Well, "best" is relative. There are probably hundreds of mcfunction compilers that will make raycasters or adventure map triggers really easy to implement. The issue comes when you bowl a little outside the bumpers and try to do something no one has done before. Stop fighting your tools.

## You already know the syntax
Blocklight stays out of your way. It's really fast. It's really intuitive. Your datapack will almost certainly still work after any Minecraft update.

```
function fizzbuzz:
    python:
        bl.eval("#mod_a:__bl = $(i) % 3")
        bl.eval("#mod_b:__bl = $(i) % 5")
    
    if (score #mod_a __bl matches 0) && (score #mod_b __bl matches 0):
        $say $(string_ab)
        return
    if score #mod_a __bl matches 0:
        $say $(string_a)
        return
    if score #mod_b __bl matches 0:
        $say $(string_b)

function fizzbuzz_runner:
    python:
        for i in range(20):
            emit(f'function demo:fizzbuzz with {{"i": {i}, "string_a": "Fizz", "string_b": "Buzz", "string_ab": "Fizzbuzz"}}')
```

## The core tenets
1. **Do one thing and do it WELL**

    Blocklight handles flow control and scoping within a single function, plus the boolean algebra needed to drive these. Every other mcfunction compiler forgets to handle the little things: function macros in if statements, return commands actually returning like a real programming language.

2. **Use Python for anything pre-computed**

    We don't need a worse version of Python. Need to clear a forest chunk by chunk? Use Python. Need to build a binary search for a specific NBT tag? Use Python. We have a tool that can emit the same command 200 times in a row. It's called Python. If Python can do something at compile-time, the compiler should never add a new feature.

3. **Vanilla is sacred**
    
    Never enforce syntax on a vanilla command. Minecraft updates should never break this compiler. The world doesn't need another mcfunction compiler requiring updates to keep up with the latest `/swing` syntax.

4. **Stick to functions**

    Do not try to be the all-in-one datapack wizard tool. How do you compile structure NBT AND custom dimension json AND OpenGL shader language? I mean, you can do it all; it's just a lot of burden for little synergy. Stick to `.bl` source that compiles into `.mcfunction` files.

© 2026 by Quinn James. Licensed under [GNU GPL v3](LICENSE)