# grendel demo tape — render with: vhs demo/grendel.tape
#
# Produces demo/grendel.gif (out-of-band; the gif is NOT committed).
# Uses a demo-safe target (a local Ollama / fake target) so no paid API key is needed.

Output demo/grendel.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"
Set Padding 20

# --- List the bundled attack packs ----------------------------------------
Type "grendel list --packs"
Enter
Sleep 2s

# --- Run the attack packs against the demo target (inline CLI summary) -----
Type "grendel run --target demo"
Enter
Sleep 6s

# --- Render a Markdown report from the saved run record --------------------
Type "grendel report --run runs/latest.json --format md"
Enter
Sleep 3s

# --- Diff two runs to show regression tracking -----------------------------
Type "grendel diff runs/baseline.json runs/latest.json"
Enter
Sleep 3s
