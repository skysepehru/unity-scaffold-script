#!/usr/bin/env python3
"""
unity-init — Interactive Unity project bootstrapper for macOS.

Run from a parent directory. Creates a project folder, then sets up:
- Git repo + Unity .gitignore
- Optional GitHub repo (via gh CLI)
- Unity project creation (via Unity Hub)
- OpenUPM packages (UniTask, optionally Zenject)
- Directory scaffold with assembly definitions
- Unity settings via batchmode (PlayerSettings, Input System, Rider, URP)
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(SCRIPT_DIR, "templates")

UNITY_HUB_PATH = "/Applications/Unity Hub.app/Contents/MacOS/Unity Hub"
UNITY_GITIGNORE_URL = "https://raw.githubusercontent.com/github/gitignore/main/Unity.gitignore"

EXIT_SUCCESS = 0
EXIT_ALREADY_EXISTS = 2
EXIT_STEP_FAILURE = 3
EXIT_ABORTED = 4


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class InitError(Exception):
    def __init__(self, step: str, message: str):
        self.step = step
        self.message = message
        super().__init__(f"[{step}] {message}")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def load_template(name: str) -> str:
    with open(os.path.join(TEMPLATES_DIR, name)) as f:
        return f.read()


def write_file(path: str, content: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"  [dry-run] WRITE {path}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    print(f"  Created {path}")


def make_dirs(path: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"  [dry-run] MKDIR {path}")
        return
    os.makedirs(path, exist_ok=True)


def run_cmd(cmd: list, step: str, *, cwd=None, fatal=True, timeout=120,
            env=None) -> subprocess.CompletedProcess | None:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        if result.returncode != 0 and fatal:
            stderr = result.stderr.strip() if result.stderr else ""
            raise InitError(step, f"Command failed: {' '.join(cmd)}\n{stderr}")
        return result
    except FileNotFoundError:
        if fatal:
            raise InitError(step, f"Command not found: {cmd[0]}")
        print(f"  WARNING: {cmd[0]} not found, skipping")
        return None
    except subprocess.TimeoutExpired:
        if fatal:
            raise InitError(step, f"Command timed out after {timeout}s: {' '.join(cmd)}")
        print(f"  WARNING: Command timed out: {' '.join(cmd)}")
        return None


def to_kebab_case(pascal: str) -> str:
    """Convert PascalCase to kebab-case. E.g. RhythmRatio -> rhythm-ratio."""
    s = re.sub(r"([A-Z])", r"-\1", pascal).lower().lstrip("-")
    return s


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------


def prompt_text(label: str, *, default=None, validator=None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value:
            if default:
                return default
            print("  Required.")
            continue
        if validator:
            err = validator(value)
            if err:
                print(f"  {err}")
                continue
        return value


def prompt_choice(label: str, choices: list[str], default: str | None = None) -> str:
    choices_str = " / ".join(f"[{c}]" if c == default else c for c in choices)
    while True:
        value = input(f"{label} ({choices_str}): ").strip().lower()
        if not value and default:
            return default
        if value in choices:
            return value
        print(f"  Choose one of: {', '.join(choices)}")


def prompt_yes_no(label: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  Enter y or n.")


def validate_pascal_case(value: str) -> str | None:
    if not re.match(r"^[A-Z][a-zA-Z0-9]+$", value):
        return "Must be PascalCase (e.g. RhythmRatio)"
    return None


def validate_identifier(value: str) -> str | None:
    if not re.match(r"^[A-Za-z][a-zA-Z0-9]+$", value):
        return "Must be a valid identifier (letters and digits, starting with a letter)"
    return None


# ---------------------------------------------------------------------------
# Unity editor discovery
# ---------------------------------------------------------------------------


def find_unity_editors() -> dict[str, str]:
    if not os.path.exists(UNITY_HUB_PATH):
        raise InitError("unity", "Unity Hub not found. Install Unity Hub first.")

    result = run_cmd(
        [UNITY_HUB_PATH, "--", "--headless", "editors", "--installed"], "unity",
    )
    if not result or not result.stdout.strip():
        raise InitError("unity", "No Unity editors installed. Install one via Unity Hub.")

    editors = {}
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line or "installed at" not in line:
            continue
        version = line.split()[0].strip()
        m = re.search(r"installed at\s+(.+)", line)
        if m:
            app_path = m.group(1).strip()
            if app_path.endswith(".app"):
                app_path = os.path.join(app_path, "Contents", "MacOS", "Unity")
            editors[version] = app_path

    if not editors:
        raise InitError("unity", f"Could not parse installed editors from:\n{result.stdout}")
    return editors


def pick_unity_editor(requested_version: str | None) -> tuple[str, str]:
    editors = find_unity_editors()

    if requested_version:
        if requested_version in editors:
            return requested_version, editors[requested_version]
        raise InitError("unity", f"Version {requested_version} not found. "
                        f"Available: {', '.join(editors.keys())}")

    versions = sorted(editors.keys())
    if len(versions) == 1:
        v = versions[0]
        print(f"  Using Unity {v}")
        return v, editors[v]

    print("\n  Installed Unity versions:")
    for i, v in enumerate(versions, 1):
        print(f"    {i}. {v}")
    while True:
        choice = input(f"  Select version [1-{len(versions)}, default={len(versions)}]: ").strip()
        if not choice:
            idx = len(versions) - 1
            break
        if choice.isdigit() and 1 <= int(choice) <= len(versions):
            idx = int(choice) - 1
            break
        print(f"  Enter a number 1-{len(versions)}")

    v = versions[idx]
    print(f"  Using Unity {v}")
    return v, editors[v]


# ---------------------------------------------------------------------------
# Assembly definitions
# ---------------------------------------------------------------------------


def make_asmdef(name: str, root_namespace: str, references: list[str], *,
                editor_only=False, is_test=False) -> str:
    data = {
        "name": name,
        "rootNamespace": root_namespace,
        "references": references,
        "includePlatforms": ["Editor"] if editor_only else [],
        "excludePlatforms": [],
        "allowUnsafeCode": False,
        "overrideReferences": is_test,
        "precompiledReferences": ["nunit.framework.dll"] if is_test else [],
        "autoReferenced": not is_test,
        "defineConstraints": ["UNITY_INCLUDE_TESTS"] if is_test else [],
        "versionDefines": [],
        "noEngineReferences": False,
    }
    return json.dumps(data, indent=4) + "\n"


def strip_zenject_refs(asmdef_json: str) -> str:
    data = json.loads(asmdef_json)
    zenject_refs = {"Zenject", "Zenject.TestFramework"}
    data["references"] = [r for r in data.get("references", []) if r not in zenject_refs]
    return json.dumps(data, indent=4) + "\n"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def step_confirm_folder(project_name: str) -> str:
    """Confirm project folder name with the user. Returns the folder path."""
    recommended = to_kebab_case(project_name) + "-unity"
    print(f"\n  Recommended folder name: {recommended}")
    print("  Convention: kebab-case ending with -unity")

    folder_name = prompt_text("Folder name", default=recommended)
    project_dir = os.path.abspath(folder_name)

    if os.path.exists(os.path.join(project_dir, "Assets")):
        raise InitError("folder", f"Assets/ already exists in {project_dir}. "
                        "This tool is for creating new Unity projects.")

    make_dirs(project_dir)
    return project_dir


def step_git_init(project_dir: str, dry_run: bool) -> None:
    if os.path.exists(os.path.join(project_dir, ".git")):
        print("  Git repo already exists, skipping init")
    elif dry_run:
        print("  [dry-run] git init")
    else:
        run_cmd(["git", "init"], "git-init", cwd=project_dir)

    gitignore_path = os.path.join(project_dir, ".gitignore")
    if os.path.exists(gitignore_path):
        print("  .gitignore already exists, skipping")
        return
    if dry_run:
        print("  [dry-run] Download Unity .gitignore")
        return

    try:
        with urllib.request.urlopen(UNITY_GITIGNORE_URL, timeout=10) as resp:
            content = resp.read().decode("utf-8")
    except Exception:
        print("  WARNING: Could not download Unity .gitignore, using bundled fallback")
        content = load_template("unity.gitignore")

    with open(gitignore_path, "w") as f:
        f.write(content)
    print("  Created .gitignore")


def step_claude_gitignore(project_dir: str, dry_run: bool) -> None:
    gitignore_path = os.path.join(project_dir, ".gitignore")
    append_content = "\n" + load_template("gitignore-append.template")

    if dry_run:
        print("  [dry-run] Append Claude Code entries to .gitignore")
        return

    with open(gitignore_path, "a") as f:
        f.write(append_content)
    print("  Appended Claude Code entries to .gitignore")


def step_github_repo(project_dir: str, dry_run: bool) -> None:
    repo_name = os.path.basename(os.path.abspath(project_dir))
    if dry_run:
        print(f"  [dry-run] gh repo create {repo_name} --private")
        return
    run_cmd(
        ["gh", "repo", "create", repo_name, "--private", "--source", ".", "--push"],
        "github-repo", cwd=project_dir, fatal=False,
    )


def step_git_commit(project_dir: str, message: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] git commit: {message}")
        return
    run_cmd(["git", "add", "-A"], "git-commit", cwd=project_dir)
    result = run_cmd(["git", "diff", "--cached", "--quiet"], "git-commit",
                     cwd=project_dir, fatal=False)
    if result and result.returncode == 0:
        print(f"  Nothing to commit for: {message}")
        return
    run_cmd(["git", "commit", "-m", message], "git-commit", cwd=project_dir)


def step_git_push(project_dir: str, dry_run: bool) -> None:
    if dry_run:
        print("  [dry-run] git push")
        return
    result = run_cmd(["git", "remote"], "git-push", cwd=project_dir, fatal=False)
    if not result or not result.stdout.strip():
        return
    run_cmd(["git", "push"], "git-push", cwd=project_dir, fatal=False)


def step_unity_create(project_dir: str, editor_path: str, dry_run: bool) -> None:
    if dry_run:
        print(f"  [dry-run] Create Unity project at {project_dir}")
        return
    print("  Creating Unity project (this may take a few minutes)...")
    run_cmd(
        [editor_path, "-createProject", project_dir, "-quit", "-batchmode"],
        "unity-create", timeout=300,
    )
    if not os.path.exists(os.path.join(project_dir, "Assets")):
        raise InitError("unity-create", "Unity project creation failed — Assets/ not found")
    print("  Unity project created successfully")


def step_packages(project_dir: str, packages: list[str], dry_run: bool) -> None:
    if dry_run:
        for pkg in packages:
            print(f"  [dry-run] openupm add {pkg}")
        return

    result = run_cmd(["openupm", "--version"], "packages", fatal=False)
    if not result or result.returncode != 0:
        print("  OpenUPM CLI not found, installing via npm...")
        run_cmd(["npm", "install", "-g", "openupm-cli"], "packages")

    for pkg in packages:
        print(f"  Installing {pkg}...")
        run_cmd(["openupm", "add", pkg], "packages", cwd=project_dir, fatal=False)


def step_scaffold(project_dir: str, project_name: str, company: str,
                  zenject: bool, tests: bool, dry_run: bool) -> None:
    assets = os.path.join(project_dir, "Assets")
    project_root = os.path.join(assets, f"_{project_name}")
    core_root = os.path.join(assets, "_Core")

    # --- Directories ---
    dirs = [
        os.path.join(assets, "Plugins"),
        os.path.join(assets, "Settings"),
        os.path.join(project_root, "Shared", "Scripts"),
        os.path.join(project_root, "Editor"),
        os.path.join(core_root, "Shared", "Scripts"),
        os.path.join(core_root, "Editor", "Scripts"),
    ]
    if tests:
        dirs.append(os.path.join(project_root, "Tests", "Editor"))
        dirs.append(os.path.join(project_root, "Tests", "Runtime"))

    print("  Creating directories...")
    for d in dirs:
        make_dirs(d, dry_run)

    # --- Assembly definitions ---
    print("  Creating assembly definitions...")

    asmdefs = [
        (os.path.join(core_root, "Core.asmdef"),
         make_asmdef("Core", f"{company}.Core", [])),

        (os.path.join(core_root, "Editor", "Core.Editor.asmdef"),
         make_asmdef("Core.Editor", f"{company}.Core.Editor", ["Core"], editor_only=True)),

        (os.path.join(project_root, f"{project_name}.asmdef"),
         make_asmdef(project_name, f"{company}.{project_name}", ["Core"])),

        (os.path.join(project_root, "Editor", f"{project_name}.Editor.asmdef"),
         make_asmdef(f"{project_name}.Editor", f"{company}.{project_name}.Editor",
                     [project_name, "Core", "Core.Editor"], editor_only=True)),
    ]

    if tests:
        editor_test = make_asmdef(
            f"{project_name}.Tests.Editor",
            f"{company}.{project_name}.Tests.Editor",
            [project_name, "Core", "Zenject", "Zenject.TestFramework"],
            editor_only=True, is_test=True,
        )
        runtime_test = make_asmdef(
            f"{project_name}.Tests.Runtime",
            f"{company}.{project_name}.Tests.Runtime",
            [project_name, "Core", "UnityEngine.TestRunner", "UnityEditor.TestRunner",
             "Zenject", "Zenject.TestFramework"],
            is_test=True,
        )
        if not zenject:
            editor_test = strip_zenject_refs(editor_test)
            runtime_test = strip_zenject_refs(runtime_test)

        asmdefs.append((
            os.path.join(project_root, "Tests", "Editor",
                         f"{project_name}.Tests.Editor.asmdef"),
            editor_test,
        ))
        asmdefs.append((
            os.path.join(project_root, "Tests", "Runtime",
                         f"{project_name}.Tests.Runtime.asmdef"),
            runtime_test,
        ))

    for path, content in asmdefs:
        write_file(path, content, dry_run)


def _prepare_setup_script(project_dir: str) -> str:
    """Copy ProjectSetup.cs into the project. Returns the path."""
    setup_script = load_template("ProjectSetup.cs")
    editor_dir = os.path.join(project_dir, "Assets", "Editor")
    make_dirs(editor_dir)
    setup_path = os.path.join(editor_dir, "ProjectSetup.cs")
    with open(setup_path, "w") as f:
        f.write(setup_script)
    return setup_path


def _cleanup_setup_script(project_dir: str) -> None:
    """Remove ProjectSetup.cs and its meta if Unity didn't clean up."""
    setup_path = os.path.join(project_dir, "Assets", "Editor", "ProjectSetup.cs")
    for f in [setup_path, setup_path + ".meta"]:
        if os.path.exists(f):
            os.remove(f)
    editor_dir = os.path.dirname(setup_path)
    if os.path.isdir(editor_dir) and not os.listdir(editor_dir):
        os.rmdir(editor_dir)
    editor_meta = editor_dir + ".meta"
    if os.path.exists(editor_meta):
        os.remove(editor_meta)


def _run_unity_phase(project_dir: str, editor_path: str, phase: str,
                     config_path: str, label: str) -> None:
    """Run a single ProjectSetup phase in batchmode."""
    env = os.environ.copy()
    env["UNITY_INIT_CONFIG"] = config_path
    env["UNITY_INIT_PHASE"] = phase

    print(f"  {label} (this may take a few minutes)...")
    result = run_cmd(
        [editor_path, "-projectPath", project_dir, "-batchmode", "-quit",
         "-executeMethod", "ProjectSetup.Run", "-logFile", "-"],
        f"unity-{phase}", timeout=600, env=env, fatal=False,
    )
    if result:
        for line in (result.stdout or "").split("\n"):
            if "[ProjectSetup]" in line:
                print(f"  {line.strip()}")
        if result.returncode != 0:
            print(f"  WARNING: {label} had errors (see above)")
        else:
            print(f"  {label} complete")


def step_unity_settings(project_dir: str, editor_path: str, config: dict,
                        dry_run: bool) -> None:
    """Configure Unity via two batchmode passes.

    Phase 1 (install): installs URP, Rider, Input System packages via PackageManager.
    Phase 2 (configure): sets PlayerSettings, input handler, Rider as editor, URP pipeline.
    Two passes needed because packages must compile before their types are available.
    """
    input_map = {"old": 0, "new": 1, "both": 2}
    setup_config = {
        "projectName": config["project_name"],
        "companyName": config["company"],
        "inputHandler": input_map[config["input_system"]],
    }

    if dry_run:
        print("  [dry-run] Unity batchmode phase 1: install packages")
        print("    URP, Rider" + (", Input System" if config["input_system"] != "old" else ""))
        print("  [dry-run] Unity batchmode phase 2: configure settings")
        print(f"    PlayerSettings: {config['company']} / {config['project_name']}")
        print(f"    Input system: {config['input_system']}")
        print("    Rider as external editor")
        print("    URP pipeline asset")
        return

    _prepare_setup_script(project_dir)

    config_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="unity_init_", delete=False,
    )
    try:
        json.dump(setup_config, config_file)
        config_file.close()

        _run_unity_phase(project_dir, editor_path, "install",
                         config_file.name, "Installing Unity packages")
        _run_unity_phase(project_dir, editor_path, "configure",
                         config_file.name, "Configuring Unity settings")
    finally:
        os.unlink(config_file.name)

    _cleanup_setup_script(project_dir)


def step_cleanup_defaults(project_dir: str, dry_run: bool) -> None:
    """Remove Unity-generated default files that aren't needed."""
    assets = os.path.join(project_dir, "Assets")

    # DefaultVolumeProfile at Assets root
    for name in ["DefaultVolumeProfile.asset", "DefaultVolumeProfile.asset.meta"]:
        path = os.path.join(assets, name)
        if os.path.exists(path):
            if dry_run:
                print(f"  [dry-run] DELETE {path}")
            else:
                os.remove(path)
                print(f"  Deleted {path}")

    # Move UniversalRenderPipelineGlobalSettings to Settings/
    settings_dir = os.path.join(assets, "Settings")
    for name in ["UniversalRenderPipelineGlobalSettings.asset",
                 "UniversalRenderPipelineGlobalSettings.asset.meta"]:
        src = os.path.join(assets, name)
        dst = os.path.join(settings_dir, name)
        if os.path.exists(src):
            if dry_run:
                print(f"  [dry-run] MOVE {src} -> {dst}")
            else:
                os.makedirs(settings_dir, exist_ok=True)
                shutil.move(src, dst)
                print(f"  Moved {name} to Settings/")

    # Empty Editor/ folder at Assets root (created by Unity, not ours)
    editor_dir = os.path.join(assets, "Editor")
    if os.path.isdir(editor_dir):
        # Only delete if empty (or only has .meta files)
        contents = [f for f in os.listdir(editor_dir) if not f.endswith(".meta")]
        if not contents:
            if dry_run:
                print(f"  [dry-run] DELETE {editor_dir}")
            else:
                shutil.rmtree(editor_dir)
                meta = editor_dir + ".meta"
                if os.path.exists(meta):
                    os.remove(meta)
                print(f"  Deleted empty {editor_dir}")


def step_unity_open(project_dir: str, editor_path: str, dry_run: bool) -> None:
    if dry_run:
        print("  [dry-run] Open Unity editor")
        return
    subprocess.Popen(
        [editor_path, "-projectPath", project_dir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    print("  Unity editor opening in background")


# ---------------------------------------------------------------------------
# Interactive config
# ---------------------------------------------------------------------------


def gather_config_interactive() -> dict:
    print("\n=== Unity Project Setup ===\n")

    project_name = prompt_text("Project name (PascalCase)", validator=validate_pascal_case)
    company = prompt_text("Company/username (for namespaces)", validator=validate_identifier)

    print()
    input_system = prompt_choice("Input system", ["old", "new", "both"], default="both")
    zenject = prompt_yes_no("Use Zenject?", default=False)
    tests = prompt_yes_no("Include test assemblies?", default=True)

    unity_mcp = prompt_yes_no("Install Unity-MCP? (github.com/IvanMurzak/Unity-MCP)", default=False)
    claude_gitignore = prompt_yes_no("Add Claude Code entries to .gitignore?", default=False)

    print()
    init_git = prompt_yes_no("Initialize a Git repo?", default=True)

    create_github = False
    if init_git:
        create_github = prompt_yes_no("Create GitHub repo?", default=True)

    return {
        "project_name": project_name,
        "company": company,
        "input_system": input_system,
        "zenject": zenject,
        "tests": tests,
        "unity_mcp": unity_mcp,
        "claude_gitignore": claude_gitignore,
        "init_git": init_git,
        "create_github": create_github,
    }


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def run_setup(config: dict, *, editor_version=None, dry_run=False,
              skip_packages=False, skip_unity_create=False) -> None:

    # 0. Confirm folder
    print("\n--- Project Folder ---")
    project_dir = step_confirm_folder(config["project_name"])

    # 1. Git
    use_git = config.get("init_git", True)
    if use_git:
        print("\n--- Git ---")
        step_git_init(project_dir, dry_run)
        if config["claude_gitignore"]:
            step_claude_gitignore(project_dir, dry_run)
        step_git_commit(project_dir, "Initial commit", dry_run)

        if config["create_github"]:
            print("\n--- GitHub ---")
            step_github_repo(project_dir, dry_run)

    # 2. Unity project
    version, editor_path = pick_unity_editor(editor_version)

    if not skip_unity_create:
        print("\n--- Unity Project ---")
        step_unity_create(project_dir, editor_path, dry_run)
        if use_git:
            step_git_commit(project_dir, "Create Unity project", dry_run)

    # 3. Packages (OpenUPM — UniTask, Zenject)
    if not skip_packages:
        print("\n--- Packages (OpenUPM) ---")
        packages = ["com.cysharp.unitask"]
        if config["zenject"]:
            packages.append("com.svermeulen.extenject@9.1.0")
        if config["unity_mcp"]:
            packages.append("com.ivanmurzak.unity.mcp")
        step_packages(project_dir, packages, dry_run)
        if use_git:
            step_git_commit(project_dir, "Install packages", dry_run)

    # 4. Scaffold
    print("\n--- Scaffold ---")
    step_scaffold(
        project_dir, config["project_name"], config["company"],
        config["zenject"], config["tests"], dry_run,
    )
    if use_git:
        step_git_commit(project_dir, "Scaffold project structure", dry_run)

    # 5. Unity settings (batchmode: PlayerSettings, Input System, Rider, URP)
    print("\n--- Unity Settings ---")
    step_unity_settings(project_dir, editor_path, config, dry_run)

    # 6. Clean up Unity defaults
    print("\n--- Cleanup ---")
    step_cleanup_defaults(project_dir, dry_run)
    if use_git:
        step_git_commit(project_dir, "Configure Unity settings", dry_run)

    # 7. Open Unity
    print("\n--- Open Unity ---")
    step_unity_open(project_dir, editor_path, dry_run)

    # 8. Push
    if use_git and config["create_github"]:
        print("\n--- Push ---")
        step_git_push(project_dir, dry_run)

    print("\n=== Done! ===")
    print(f"  Project: {config['project_name']}")
    print(f"  Directory: {project_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive Unity project bootstrapper. "
                    "Run from the parent directory where you want the project folder created.",
    )

    parser.add_argument("--name", help="Project name (PascalCase)")
    parser.add_argument("--company", help="Company/username for namespaces")
    parser.add_argument("--input-system", choices=["old", "new", "both"])
    parser.add_argument("--zenject", action="store_true", default=None)
    parser.add_argument("--no-zenject", dest="zenject", action="store_false")
    parser.add_argument("--tests", action="store_true", default=None)
    parser.add_argument("--no-tests", dest="tests", action="store_false")
    parser.add_argument("--unity-mcp", action="store_true", default=None)
    parser.add_argument("--no-unity-mcp", dest="unity_mcp", action="store_false")
    parser.add_argument("--claude-gitignore", action="store_true", default=None)
    parser.add_argument("--no-claude-gitignore", dest="claude_gitignore", action="store_false")
    parser.add_argument("--git", action="store_true", default=None)
    parser.add_argument("--no-git", dest="git", action="store_false")
    parser.add_argument("--github", action="store_true", default=None)
    parser.add_argument("--no-github", dest="github", action="store_false")
    parser.add_argument("--editor-version", help="Unity editor version to use")

    parser.add_argument("--skip-packages", action="store_true")
    parser.add_argument("--skip-unity-create", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Build config: CLI args → non-interactive, otherwise interactive
    if args.name and args.company:
        config = {
            "project_name": args.name,
            "company": args.company,
            "input_system": args.input_system or "both",
            "zenject": args.zenject if args.zenject is not None else False,
            "tests": args.tests if args.tests is not None else True,
            "unity_mcp": args.unity_mcp if args.unity_mcp is not None else False,
            "claude_gitignore": args.claude_gitignore if args.claude_gitignore is not None else False,
            "init_git": args.git if args.git is not None else True,
            "create_github": args.github if args.github is not None else False,
        }
    else:
        config = gather_config_interactive()
        if args.name:
            config["project_name"] = args.name
        if args.company:
            config["company"] = args.company
        if args.input_system:
            config["input_system"] = args.input_system
        if args.zenject is not None:
            config["zenject"] = args.zenject
        if args.tests is not None:
            config["tests"] = args.tests
        if args.unity_mcp is not None:
            config["unity_mcp"] = args.unity_mcp
        if args.claude_gitignore is not None:
            config["claude_gitignore"] = args.claude_gitignore
        if args.git is not None:
            config["init_git"] = args.git
        if args.github is not None:
            config["create_github"] = args.github

    if args.dry_run:
        print("\n=== DRY RUN ===")

    try:
        run_setup(
            config,
            editor_version=args.editor_version,
            dry_run=args.dry_run,
            skip_packages=args.skip_packages,
            skip_unity_create=args.skip_unity_create,
        )
    except InitError as e:
        print(f"\nERROR [{e.step}]: {e.message}", file=sys.stderr)
        return EXIT_STEP_FAILURE

    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
