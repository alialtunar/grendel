# gauntlet demo tape — render with: vhs demo/gauntlet.tape
#
# Produces demo/gauntlet.gif (out-of-band; the gif is NOT committed).
# Uses a demo-safe target (a local Ollama / fake target) so no paid API key is needed.

Output demo/gauntlet.gif

Set Shell "bash"
Set FontSize 16
Set Width 1200
Set Height 700
Set Theme "Dracula"
Set Padding 20

# --- List the bundled attack packs ----------------------------------------
Type "gauntlet list --packs"
Enter
Sleep 2s

# --- Run the gauntlet with the live TUI scoreboard (the hero shot) ---------
Type "gauntlet run --target demo --tui"
Enter
Sleep 6s

# --- Render a Markdown report from the saved run record --------------------
Type "gauntlet report --run runs/latest.json --format md"
Enter
Sleep 3s

# --- Diff two runs to show regression tracking -----------------------------
Type "gauntlet diff runs/baseline.json runs/latest.json"
Enter
Sleep 3s
