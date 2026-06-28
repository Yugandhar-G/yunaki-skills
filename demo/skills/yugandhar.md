---
name: yugandhar
description: Add a new Python module, script, or CLI to an existing repository so it fits in cleanly.
---

# Add a Python module

Use when adding a new module, helper, or command-line entry point to an existing
Python codebase. The goal is code that reads like it was always there.

## Method
1. Find the closest existing module to what you're adding and mirror its shape —
   imports, structure, error style, naming.
2. Keep the module focused: one clear responsibility, a small public surface.
3. If it exposes a command-line entry point, parse arguments explicitly and give
   it a single, testable entry function.
4. Handle failure deliberately at the boundaries; don't let internals crash the
   caller.
5. Add or update a test next to the code before wiring it in.
6. Run the repo's checks (lint, types, tests) and fix whatever they flag.

## Output
A new module that matches the repository's conventions and passes its checks on
the first run.
