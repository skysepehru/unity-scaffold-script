# unity-scaffold-script

Interactive CLI tool to bootstrap new Unity projects on macOS.

## What it does

Run from a parent directory. It handles everything:

- Project folder creation (recommends kebab-case-unity naming)
- Git init + Unity .gitignore
- Optional GitHub repo creation
- Unity project creation via Unity Hub CLI
- OpenUPM packages (UniTask, optionally Zenject, Unity-MCP)
- Directory scaffold with assembly definitions (Core, Editor, Tests)
- Unity settings via batchmode (PlayerSettings, Input System, Rider, URP)
- Cleanup of Unity-generated defaults
- Opens Unity when done

## Usage

```bash
# Interactive mode
unity-create

# Or run directly
python3 scripts/unity-init.py

# Non-interactive
python3 scripts/unity-init.py --name MyGame --company Acme --input-system both --tests --github
```

## Requirements

- macOS
- Python 3.10+
- Unity Hub + at least one Unity editor installed
- `gh` CLI (for GitHub repo creation)
- `npm` (for OpenUPM CLI auto-install)

## Alias

Add to your `.zshrc`:

```bash
alias unity-create="python3 /path/to/unity-scaffold-script/scripts/unity-init.py"
```
