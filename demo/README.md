# Demo GIF

The hero asset is a [VHS](https://github.com/charmbracelet/vhs)-recorded GIF of the live
grendel CLI session, generated from [`grendel.tape`](grendel.tape).

**The `.gif` is rendered out-of-band and is intentionally NOT committed** — it is a binary
that needs VHS + a real terminal, and the test suite never runs VHS. Regenerate it from the
tape whenever the demo changes.

## Render it

1. Install VHS:

   ```bash
   go install github.com/charmbracelet/vhs@latest
   # or: brew install vhs
   ```

2. Render the gif (writes `demo/grendel.gif`):

   ```bash
   vhs demo/grendel.tape
   ```

## Demo-target prerequisites

`grendel.tape` drives a **demo-safe** target (a local Ollama model or a fake target) so the
recording needs **no paid API key**. Point the `demo` target at your local model in the
grendel config, and have a couple of saved run records (`runs/latest.json`,
`runs/baseline.json`) on hand for the `report` and `diff` steps.
