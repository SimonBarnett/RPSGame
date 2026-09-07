# Rock / Paper / Scissors — swarm arena

## Run

```
python game.py
python game.py -learn 20
python game.py /learn
RPS_Game.exe /learn 50
```

| flag | effect |
|---|---|
| (none) | live window |
| `-learn 20` or `/learn 20` | headless train 20 games, learn after each |
| `-learn` or `/learn` | train until Ctrl+C |

Escape quits. Alt+Enter fullscreen.

Build with [build_exe.bat](build_exe.bat). First run in an empty folder seeds `strategies/`, `arena/`, `optimizer/metrics/`, and these markdown files next to the exe.

## Compiled vs data

The exe is the binary. Team doctrine is JSON.

- Templates: [strategies/templates/](strategies/templates/)
- Per-team copies: [strategies/types/](strategies/types/)
- Legal set / bans: [strategies/legal.json](strategies/legal.json)
- Knob bounds: [strategies/bounds.json](strategies/bounds.json)
- Motion triangle: [strategies/motion_identity.json](strategies/motion_identity.json)
- Schema: [strategies/SCHEMA.md](strategies/SCHEMA.md)
- Grok brief: [optimizer/grok/](optimizer/grok/)

Drop `strategies/templates/YOUR_ID.json`. Reload clones it to each type. The optimiser tunes those copies.

## Layout

```
game.py          live + -learn / /learn
build_exe.bat    PyInstaller onefile
app_paths.py     frozen paths + first-run seed
arena/           shell, hud, images/, sound/
maths/           boids, voronoi, ping, phys
optimizer/       engine, logger, metrics/, grok/
strategies/      SCHEMA.md, templates/, types/
```

Icon: [rps.ico](rps.ico) (wired into [build_exe.bat](build_exe.bat) as `--icon`).
