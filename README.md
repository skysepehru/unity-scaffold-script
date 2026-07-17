# unity-scaffold-script

Interactive CLI tool to bootstrap new Unity projects on macOS. One command takes you from an empty folder to an open Unity editor with git, packages, an assembly-definition scaffold, and sensible project settings already in place.

## What it does

Run it from the parent directory where you want the new project folder created. It walks through each step (or runs unattended with flags):

- **Project folder** creation (recommends `kebab-case` naming)
- **`.gitignore`** — writes a Unity-tuned `.gitignore` (optionally with Claude Code entries), independent of git init
- **Git** init + initial commit
- **GitHub** repo creation and push (optional, via `gh`)
- **Unity project** creation via the Unity Hub CLI
- **Packages** from OpenUPM — UniTask, optionally Zenject and [Unity-MCP](https://github.com/IvanMurzak/Unity-MCP)
- **Directory scaffold** with assembly definitions (Core, Editor, Tests)
- **Unity settings** applied in batchmode: PlayerSettings, Input System, Rider, URP
- **Cleanup** of Unity-generated defaults
- **Opens Unity** when done

## Usage

```bash
# Interactive mode — prompts for everything
python3 scripts/unity-init.py

# Non-interactive — pass --name and --company to skip prompts
python3 scripts/unity-init.py --name MyGame --company Acme --input-system both --tests --github

# Preview without making changes
python3 scripts/unity-init.py --name MyGame --company Acme --dry-run
```

Providing both `--name` and `--company` switches the script into non-interactive mode; any other flags override their defaults. Without them, it runs interactively.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--name` | Project name (PascalCase) | prompt |
| `--company` | Company/username for namespaces | prompt |
| `--input-system {old,new,both}` | Which Unity input system to enable | `both` |
| `--gitignore` / `--no-gitignore` | Write a Unity `.gitignore` | on |
| `--claude-gitignore` / `--no-claude-gitignore` | Add Claude Code entries to `.gitignore` | off |
| `--git` / `--no-git` | Initialize a git repo | on |
| `--github` / `--no-github` | Create a GitHub repo and push | off |
| `--zenject` / `--no-zenject` | Install Zenject | off |
| `--tests` / `--no-tests` | Include test assemblies | on |
| `--unity-mcp` / `--no-unity-mcp` | Install Unity-MCP | off |
| `--editor-version` | Unity editor version to use | auto-pick |
| `--skip-packages` | Skip OpenUPM package installation | — |
| `--skip-unity-create` | Skip Unity project creation | — |
| `--dry-run` | Print actions without executing | — |

## Requirements

- macOS
- Python 3.10+
- Unity Hub + at least one Unity editor installed
- [`gh`](https://cli.github.com/) CLI (for GitHub repo creation)
- `npm` (for OpenUPM CLI auto-install)

## Alias

Add to your `.zshrc` for a quick `unity-create` command:

```bash
alias unity-create="python3 /path/to/unity-scaffold-script/scripts/unity-init.py"
```
