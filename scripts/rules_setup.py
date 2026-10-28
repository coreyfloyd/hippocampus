#!/usr/bin/env python3
"""Inspect and propose the rules-and-memory part of Hippocampus set-up.

This helper deliberately separates detection and planning from mutation.  The
set-up skill presents the returned plan and calls ``apply`` only after the user
has approved its complete mutation list.  Tests pass fake tool homes; callers
without an explicit mapping receive the user's conventional tool homes.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


TOOLS = {
    "claude-code": {"binary": "claude", "target": "CLAUDE.md"},
    "codex": {"binary": "codex", "target": "AGENTS.md"},
    "openclaw": {"binary": "openclaw", "target": "AGENTS.md"},
}


def default_homes():
    home = pathlib.Path.home()
    return {
        "claude-code": home / ".claude",
        "codex": home / ".codex",
        "openclaw": home / ".openclaw",
    }


def json_file(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def dump_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def toml_value(path, section, key):
    """Read one simple TOML value without parsing or rewriting unrelated TOML."""
    if not path.exists():
        return None
    active = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            active = stripped[1:-1].strip()
        elif active == section and "=" in stripped:
            candidate, value = stripped.split("=", 1)
            if candidate.strip() == key:
                return value.strip().strip('"').strip("'")
    return None


def replace_toml_value(path, section, key, value):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replacement = f"{key} = {str(value).lower()}" if isinstance(value, bool) else f'{key} = "{value}"'
    active = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            active = stripped[1:-1].strip()
        elif active == section and "=" in stripped and stripped.split("=", 1)[0].strip() == key:
            lines[index] = replacement
            break
    else:
        if lines and lines[-1]:
            lines.append("")
        lines.append(f"[{section}]")
        lines.append(replacement)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def nested(mapping, *keys):
    value = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def set_nested(mapping, keys, value):
    current = mapping
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[keys[-1]] = value


def count_files(path):
    if not path.is_dir():
        return 0
    return sum(1 for candidate in path.rglob("*") if candidate.is_file())


def composer_owned(path):
    if not path.exists():
        return True
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
    except (OSError, UnicodeError, IndexError):
        return False
    return first == "<!-- hippocampus-rules: generated; do not hand-edit -->" or (
        first.startswith("<!-- hippocampus-rules: generated from ")
        and first.endswith("; do not hand-edit -->")
    )


def installed(tool, home):
    return (home / "bin" / TOOLS[tool]["binary"]).exists() or bool(shutil.which(TOOLS[tool]["binary"])) or home.exists()


def claude_memory(home):
    settings_path = home / "settings.json"
    settings = json_file(settings_path)
    store = home / "projects"
    custom_directory = settings.get("autoMemoryDirectory")
    if custom_directory:
        candidate = pathlib.Path(custom_directory).expanduser()
        return "customized", settings_path, candidate, []
    enabled = settings.get("autoMemoryEnabled", True)
    state = "off" if enabled is False else "on"
    mutations = [] if state == "off" else [{
        "file": str(settings_path), "setting": "autoMemoryEnabled", "current": enabled, "proposed": False,
    }]
    return state, settings_path, store, mutations


def codex_memory(home):
    config_path = home / "config.toml"
    value = toml_value(config_path, "features", "memories")
    store = home / "memories"
    if value and value not in {"true", "false"}:
        return "customized", config_path, store, []
    state = "on" if value == "true" else "off"
    mutations = [] if state == "off" else [{
        "file": str(config_path), "setting": "features.memories", "current": value, "proposed": False,
    }]
    return state, config_path, store, mutations


def openclaw_memory(home):
    config_path = home / "openclaw.json"
    config = json_file(config_path)
    workspace = nested(config, "agents", "defaults", "workspace") or home / "workspace"
    workspace = pathlib.Path(workspace).expanduser()
    if not workspace.is_absolute():
        workspace = home / workspace
    default_workspace = home / "workspace"
    if workspace != default_workspace:
        return "customized", config_path, workspace / "memory", []
    flush = nested(config, "agents", "defaults", "compaction", "memoryFlush", "enabled")
    dreaming = nested(config, "plugins", "entries", "memory-core", "config", "dreaming", "enabled")
    state = "off" if flush is False and dreaming is False else "on"
    mutations = [] if state == "off" else [
        {"file": str(config_path), "setting": "agents.defaults.compaction.memoryFlush.enabled", "current": flush, "proposed": False},
        {"file": str(config_path), "setting": "plugins.entries.memory-core.config.dreaming.enabled", "current": dreaming, "proposed": False},
    ]
    return state, config_path, workspace / "memory", mutations


def inspect_tools(homes=None):
    homes = {key: pathlib.Path(value) for key, value in (homes or default_homes()).items()}
    rows = []
    for tool in TOOLS:
        home = homes[tool]
        target = home / TOOLS[tool]["target"]
        if tool == "openclaw":
            config = json_file(home / "openclaw.json")
            workspace = nested(config, "agents", "defaults", "workspace") or home / "workspace"
            workspace = pathlib.Path(workspace).expanduser()
            target = (workspace if workspace.is_absolute() else home / workspace) / "AGENTS.md"
            state, settings, store, mutations = openclaw_memory(home)
        elif tool == "claude-code":
            state, settings, store, mutations = claude_memory(home)
        else:
            state, settings, store, mutations = codex_memory(home)
        rows.append({
            "tool": tool,
            "installed": installed(tool, home),
            "target": {"file": str(target), "exists": target.exists(), "ownership": "composer-owned" if composer_owned(target) else "user-owned"},
            "memory": {"state": state, "settings_file": str(settings), "store": {"location": str(store), "file_count": count_files(store), "empty": count_files(store) == 0}},
            "off_mutations": mutations,
        })
    return rows


def approval_payload(plan_value):
    """Return the complete user-reviewable portion of a plan."""
    return {
        "preset": plan_value["preset"],
        "development_root": plan_value["development_root"],
        "tools": [{
            "tool": row["tool"],
            "rules_target": row["rules_target"],
            "memory": row["memory"],
            "memory_mutations": row["memory_mutations"],
        } for row in plan_value["tools"]],
        "mutation_list": plan_value["mutation_list"],
    }


def plan_fingerprint(plan_value):
    payload = json.dumps(approval_payload(plan_value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan(rows, preset, development_root=None, overrides=None, profile=None):
    if preset not in {"standard", "thin"}:
        raise ValueError("preset must be standard or thin")
    overrides = overrides or {}
    result = {"preset": preset, "development_root": str(development_root) if development_root else None, "tools": [], "mutation_list": [], "context_guidance": ["context/devices.md", "context/file-locations.md", "context/people.md", "context/preferences.md"]}
    for row in rows:
        if not row["installed"]:
            continue
        tool = row["tool"]
        choice = overrides.get(tool, {})
        rules_target = choice.get("rules_target", "none" if preset == "standard" else row["target"]["file"])
        memory = choice.get("memory", "native" if preset == "standard" else "off")
        if memory not in {"native", "off"}:
            raise ValueError(f"{tool} memory must be native or off")
        state = row["memory"]["state"]
        mutations = row["off_mutations"] if memory == "off" and state == "on" else []
        flagged = memory == "off" and state == "customized"
        delivery = None
        if development_root:
            delivery = "directory walk from the development root" if tool == "claude-code" else "repository block"
        proposed = {"tool": tool, "rules_target": rules_target, "memory": memory, "memory_mutations": mutations, "memory_change_count": len(row["off_mutations"]), "flagged": flagged, "development_delivery": delivery}
        result["tools"].append(proposed)
        if rules_target != "none" and (not row["target"]["exists"] or row["target"]["ownership"] == "user-owned"):
            result["mutation_list"].append({"kind": "rule target", "file": rules_target, "current": "existing" if row["target"]["exists"] else "absent", "proposed": "compose from context/rules.md"})
        result["mutation_list"].extend({"kind": "memory setting", **mutation} for mutation in mutations)
    if profile:
        profile = pathlib.Path(profile)
        current = None
        if profile.exists():
            current = profile_reader().parse(profile).get("rules")
        expected = {
            "preset": result["preset"],
            "cross_tool_document": "context/rules.md",
            "development_document": "context/development-rules.md",
            "tools": [{"tool": row["tool"], "rules_target": row["rules_target"], "memory": row["memory"]} for row in result["tools"]],
        }
        if result["development_root"]:
            expected["development_root"] = result["development_root"]
        if current != expected:
            result["mutation_list"].append({"kind": "profile", "file": str(profile), "current": "rules section present" if current else "rules section absent", "proposed": "record approved rules and memory choices"})
    result["approval_fingerprint"] = plan_fingerprint(result)
    return result


def write_memory_state(home, tool, state):
    """Test fixture helper for all supported detector states."""
    home = pathlib.Path(home)
    if tool == "claude-code":
        settings = {} if state != "customized" else {"autoMemoryDirectory": str(home / "other-memory")}
        if state != "customized":
            settings["autoMemoryEnabled"] = state == "on"
        dump_json(home / "settings.json", settings)
    elif tool == "codex":
        replace_toml_value(home / "config.toml", "features", "memories", {"on": True, "off": False, "customized": "external"}[state])
    else:
        config = {} if state != "customized" else {"agents": {"defaults": {"workspace": str(home / "other-workspace")}}}
        if state != "customized":
            set_nested(config, ("agents", "defaults", "compaction", "memoryFlush", "enabled"), state == "on")
            set_nested(config, ("plugins", "entries", "memory-core", "config", "dreaming", "enabled"), state == "on")
        dump_json(home / "openclaw.json", config)


def profile_reader():
    path = pathlib.Path(__file__).with_name("validate_profile.py")
    spec = importlib.util.spec_from_file_location("hippocampus_profile_reader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rules_section(plan_value):
    lines = [
        "rules:",
        f"  preset: {plan_value['preset']}",
        "  cross_tool_document: context/rules.md",
        "  development_document: context/development-rules.md",
        "  tools:",
    ]
    if plan_value.get("development_root"):
        lines[3:3] = [f"  development_root: {plan_value['development_root']}"]
    for row in plan_value["tools"]:
        lines.extend((
            f"    - tool: {row['tool']}",
            f"      rules_target: {row['rules_target']}",
            f"      memory: {row['memory']}",
        ))
    return lines


def replace_rules_section(profile, plan_value):
    lines = profile.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("profile has no frontmatter")
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("profile has unterminated frontmatter")
    rewritten = []
    index = 1
    while index < end:
        if lines[index].strip() == "rules:":
            index += 1
            while index < end and (not lines[index].strip() or lines[index].startswith((" ", "\t", "#"))):
                index += 1
            continue
        rewritten.append(lines[index])
        index += 1
    replacement = [line + "\n" for line in rules_section(plan_value)]
    return "".join([lines[0], *rewritten, *replacement, *lines[end:]])


def compose_targets(plan_value, knowledge_root):
    targets = []
    tool_names = {"claude-code": "claude", "codex": "codex", "openclaw": "openclaw"}
    for row in plan_value["tools"]:
        if row["rules_target"] != "none":
            targets.append({
                "tool": tool_names[row["tool"]],
                "scope": "user",
                "file": row["rules_target"],
                "sources": ["context/rules.md"],
            })
    if not targets:
        return
    config = {"knowledge_root": str(knowledge_root), "targets": targets}
    descriptor, name = tempfile.mkstemp(prefix="hippocampus-rules-setup-", suffix=".json")
    os.close(descriptor)
    config_path = pathlib.Path(name)
    try:
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(pathlib.Path(__file__).with_name("compose_rules.py")), "compose", "--config", str(config_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise ValueError(result.stderr.strip() or "rules composer failed")
    finally:
        config_path.unlink(missing_ok=True)


def apply(plan_value, profile, knowledge_root=None, approved=False, approval_fingerprint=None):
    if not approved:
        raise ValueError("complete mutation list requires explicit approval")
    if approval_fingerprint != plan_fingerprint(plan_value):
        raise ValueError("approved mutation list changed; rerun plan and approve the new fingerprint")
    profile = pathlib.Path(profile)
    reader = profile_reader()
    reader.validate(profile)
    values = reader.parse(profile)
    root = pathlib.Path(knowledge_root or values["knowledge_root"]).resolve()
    if root != pathlib.Path(values["knowledge_root"]).resolve():
        raise ValueError("knowledge_root does not match the profile")
    compose_targets(plan_value, root)
    for mutation in plan_value["mutation_list"]:
        if mutation["kind"] != "memory setting":
            continue
        path = pathlib.Path(mutation["file"])
        setting = mutation["setting"]
        if path.suffix == ".json":
            data = json_file(path)
            set_nested(data, tuple(setting.split(".")), mutation["proposed"])
            dump_json(path, data)
        else:
            section, key = setting.rsplit(".", 1)
            replace_toml_value(path, section, key, mutation["proposed"])
    replacement = replace_rules_section(profile, plan_value)
    descriptor, name = tempfile.mkstemp(prefix="hippocampus-profile-", suffix=".md", dir=profile.parent)
    os.close(descriptor)
    candidate = pathlib.Path(name)
    try:
        candidate.write_text(replacement, encoding="utf-8")
        reader.validate(candidate)
        candidate.replace(profile)
    finally:
        candidate.unlink(missing_ok=True)
    return plan_value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "plan", "apply"))
    parser.add_argument("--homes", help="JSON object mapping tool names to homes")
    parser.add_argument("--preset", choices=("standard", "thin"), default="standard")
    parser.add_argument("--development-root")
    parser.add_argument("--overrides", help="JSON object of per-tool approved row choices")
    parser.add_argument("--profile", help="profile to update after approval")
    parser.add_argument("--approve", action="store_true", help="apply the complete displayed mutation list")
    parser.add_argument("--approval-fingerprint", help="fingerprint printed by the approved plan")
    args = parser.parse_args()
    homes = {key: pathlib.Path(value) for key, value in json.loads(args.homes).items()} if args.homes else None
    rows = inspect_tools(homes)
    overrides = json.loads(args.overrides) if args.overrides else None
    value = rows if args.command == "inspect" else plan(rows, args.preset, args.development_root, overrides, args.profile)
    if args.command == "apply":
        if not args.profile:
            parser.error("apply requires --profile")
        if not args.approval_fingerprint:
            parser.error("apply requires --approval-fingerprint from the approved plan")
        try:
            value = apply(
                value,
                args.profile,
                approved=args.approve,
                approval_fingerprint=args.approval_fingerprint,
            )
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
