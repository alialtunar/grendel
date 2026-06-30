# Demo GIF

The hero asset is a [VHS](https://github.com/charmbracelet/vhs)-recorded GIF of the live
TUI scoreboard, generated from [`gauntlet.tape`](gauntlet.tape).

**The `.gif` is rendered out-of-band and is intentionally NOT committed** — it is a binary
that needs VHS + a real terminal, and the test suite never runs VHS. Regenerate it from the
tape whenever the demo changes.

## Render it

1. Install VHS:

   ```bash
   go install github.com/charmbracelet/vhs@latest
   # or: brew install vhs
   ```

2. Render the gif (writes `demo/gauntlet.gif`):

   ```bash
   vhs demo/gauntlet.tape
   ```

## Demo-target prerequisites

`gauntlet.tape` drives a **demo-safe** target (a local Ollama model or a fake target) so the
recording needs **no paid API key**. Point the `demo` target at your local model in the
gauntlet config, and have a couple of saved run records (`runs/latest.json`,
`runs/baseline.json`) on hand for the `report` and `diff` steps.
