#!/usr/bin/env python3
"""Inspect and propose the rules-and-memory part of Hippocampus set-up.

This helper deliberately separates detection and planning from mutation.  The
set-up skill presents the returned plan and calls ``apply`` only after the user
has approved its complete mutation list.  Tests pass fake tool homes; callers
without an explicit mapping receive the user's conventional tool homes.
"""
import argparse
import copy
import re
import tomllib
import hashlib
import importlib.util
import json
import pathlib
import shutil
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
    if not path.exists():
        return None
    return nested(tomllib.loads(path.read_text(encoding="utf-8")), *section.split("."), key)


def replace_toml_value(path, section, key, value):
    """Change a boolean token only if TOML parsing proves the exact semantic edit.

    This supports dotted keys, quoted keys, inline tables and comments without
    reserializing or discarding any unrelated configuration.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = tomllib.loads(text)
    current = nested(data, *section.split("."), key)
    if current == value:
        return
    if isinstance(current, bool) and isinstance(value, bool):
        expected = copy.deepcopy(data)
        set_nested(expected, (*section.split("."), key), value)
        for match in re.finditer(r"\b(?:true|false)\b", text):
            candidate = text[:match.start()] + str(value).lower() + text[match.end():]
            try:
                if tomllib.loads(candidate) == expected:
                    path.write_text(candidate, encoding="utf-8")
                    return
            except tomllib.TOMLDecodeError:
                continue
        raise ValueError(f"cannot safely update {section}.{key} in {path}")
    # Only used to build isolated fixtures when the key is absent.
    if current is None:
        literal = str(value).lower() if isinstance(value, bool) else json.dumps(value)
        candidate = text + f"\n[{section}]\n{key} = {literal}\n"
        tomllib.loads(candidate)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(candidate, encoding="utf-8")
        return
    raise ValueError(f"customized TOML setting {section}.{key} in {path}")


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
    if value is not None and not isinstance(value, bool):
        return "customized", config_path, store, []
    state = "on" if value is True else "off"
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
        return "customized", config_path, workspace, []
    flush = nested(config, "agents", "defaults", "compaction", "memoryFlush", "enabled")
    dreaming = nested(config, "plugins", "entries", "memory-core", "config", "dreaming", "enabled")
    state = "off" if flush is False and dreaming is False else "on"
    mutations = [] if state == "off" else [
        {"file": str(config_path), "setting": "agents.defaults.compaction.memoryFlush.enabled", "current": flush, "proposed": False},
        {"file": str(config_path), "setting": "plugins.entries.memory-core.config.dreaming.enabled", "current": dreaming, "proposed": False},
    ]
    return state, config_path, workspace, [m for m in mutations if m["current"] is not False]


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
        if tool == "claude-code" and state != "customized":
            locations = sorted((home / "projects").glob("*/memory"))
            file_count = sum(count_files(location) for location in locations)
        elif tool == "openclaw":
            locations = [store / "MEMORY.md", store / "memory"]
            file_count = int(locations[0].is_file()) + count_files(locations[1])
        else:
            locations = [store]
            file_count = count_files(store)
        rows.append({
            "tool": tool,
            "home": str(home),
            "installed": installed(tool, home),
            "target": {"file": str(target), "exists": target.exists(), "ownership": "composer-owned" if composer_owned(target) else "user-owned"},
            "memory": {"state": state, "settings_file": str(settings), "store": {"location": str(store), "file_count": file_count, "empty": file_count == 0, "locations": [str(location) for location in locations]}},
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
        "file_states": plan_value.get("file_states", {}),
    }


def plan_fingerprint(plan_value):
    payload = json.dumps(approval_payload(plan_value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def plan(rows, preset, development_root=None, overrides=None, profile=None):
    if preset not in {"standard", "thin"}:
        raise ValueError("preset must be standard or thin")
    overrides = overrides or {}
    if profile:
        values = profile_reader().parse(pathlib.Path(profile))
        development_root = development_root or values.get("rules", {}).get("development_root")
    result = {"preset": preset, "development_root": str(development_root) if development_root else None, "tools": [], "mutation_list": [], "context_guidance": ["context/devices.md", "context/file-locations.md", "context/people.md", "context/preferences.md"]}
    result["homes"] = {row["tool"]: row["home"] for row in rows}
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
    if profile:
        root = pathlib.Path(values["knowledge_root"]).resolve()
        composer, writes = target_plan(result, root)
        directories = set()
        for item in writes:
            if item.original == item.desired:
                continue
            parent = item.target.path.parent
            while not parent.exists():
                directories.add(parent)
                parent = parent.parent
            result["mutation_list"].append({
                "kind": "rule target", "file": str(item.target.path),
                "current": digest(item.original), "proposed": digest(item.desired),
                "desired_contents": item.desired.decode("utf-8"),
            })
        for mutation in result["mutation_list"]:
            if mutation["kind"] == "memory setting":
                parent = pathlib.Path(mutation["file"]).parent
                while not parent.exists():
                    directories.add(parent)
                    parent = parent.parent
        result["mutation_list"][0:0] = [
            {"kind": "directory", "file": str(path), "current": "absent", "proposed": "create directory"}
            for path in sorted(directories, key=lambda p: (len(p.parts), str(p)))
        ]
        files = {pathlib.Path(m["file"]) for m in result["mutation_list"] if m["kind"] != "directory"}
        files.update(item.target.path for item in writes)
        files.add(pathlib.Path(profile))
        result["file_states"] = {str(path): digest(path.read_bytes() if path.exists() else None) for path in sorted(files)}
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
        value = {"on": "true", "off": "false", "customized": '"external"'}[state]
        (home / "config.toml").write_text(f"[features]\nmemories = {value}\n", encoding="utf-8")
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


def digest(content):
    return "absent" if content is None else hashlib.sha256(content).hexdigest()


def target_plan(plan_value, knowledge_root):
    path = pathlib.Path(__file__).with_name("compose_rules.py")
    spec = importlib.util.spec_from_file_location("hippocampus_composer", path)
    composer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = composer
    spec.loader.exec_module(composer)
    targets = []
    tool_names = {"claude-code": "claude", "codex": "codex", "openclaw": "openclaw"}
    for row in plan_value["tools"]:
        if row["rules_target"] != "none":
            targets.append({"tool": tool_names[row["tool"]], "scope": "user",
                            "file": row["rules_target"], "sources": ["context/rules.md"]})
    if plan_value["development_root"]:
        dev = pathlib.Path(plan_value["development_root"])
        for tool, filename in (("claude", "CLAUDE.md"), ("codex", "AGENTS.md")):
            targets.append({"tool": tool, "scope": "development", "file": str(dev / filename),
                            "sources": ["context/development-rules.md"]})
    if not targets:
        return composer, []
    with tempfile.TemporaryDirectory(prefix="hippocampus-rules-plan-") as temporary:
        config = pathlib.Path(temporary) / "targets.json"
        config.write_text(json.dumps({"knowledge_root": str(knowledge_root), "targets": targets}))
        try:
            _, parsed = composer.load_config(config)
            return composer, composer.plan(parsed, allow_missing_parents=True)
        except composer.ComposeError as exc:
            raise ValueError(str(exc)) from exc


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
    homes = plan_value.get("homes")
    if not homes:
        raise ValueError("apply requires a profile-backed plan")
    overrides = {row["tool"]: {"rules_target": row["rules_target"], "memory": row["memory"]} for row in plan_value["tools"]}
    fresh = plan(inspect_tools(homes), plan_value["preset"], plan_value["development_root"], overrides, profile)
    if plan_fingerprint(fresh) != approval_fingerprint:
        raise ValueError("approved mutation list changed; rerun plan and approve the new fingerprint")
    composer, writes = target_plan(fresh, root)
    actual_targets = {str(item.target.path): (digest(item.original), digest(item.desired))
                      for item in writes if item.original != item.desired}
    approved_targets = {m["file"]: (m["current"], m["proposed"])
                        for m in fresh["mutation_list"] if m["kind"] == "rule target"}
    if actual_targets != approved_targets:
        raise ValueError("approved mutation list changed; rerun plan and approve the new fingerprint")
    extra_files = {}
    for mutation in fresh["mutation_list"]:
        if mutation["kind"] == "memory setting":
            extra_files.setdefault(pathlib.Path(mutation["file"]), []).append(mutation)
    # Render and validate every settings/profile update before touching targets.
    with tempfile.TemporaryDirectory(prefix="hippocampus-rules-settings-") as temporary:
        for index, (path, mutations) in enumerate(extra_files.items()):
            scratch = pathlib.Path(temporary) / (str(index) + path.suffix)
            if path.exists():
                scratch.write_bytes(path.read_bytes())
            for mutation in mutations:
                if path.suffix == ".json":
                    data = json_file(scratch)
                    set_nested(data, tuple(mutation["setting"].split(".")), mutation["proposed"])
                    dump_json(scratch, data)
                else:
                    section, key = mutation["setting"].rsplit(".", 1)
                    replace_toml_value(scratch, section, key, mutation["proposed"])
            target = composer.Target("codex", "settings", path, [])
            original, mode = composer.preflight_target(target, allow_missing_parents=True)
            writes.append(composer.PlannedWrite(target, original, mode, scratch.read_bytes(), "settings"))
        if any(m["kind"] == "profile" for m in fresh["mutation_list"]):
            candidate = pathlib.Path(temporary) / "profile.md"
            candidate.write_text(replace_rules_section(profile, fresh), encoding="utf-8")
            reader.validate(candidate)
            target = composer.Target("codex", "profile", profile, [])
            original, mode = composer.preflight_target(target)
            writes.append(composer.PlannedWrite(target, original, mode, candidate.read_bytes(), "profile"))
    paths = [item.target.path for item in writes]
    if len(set(paths)) != len(paths):
        raise ValueError("target overlaps profile or memory settings")
    for path, expected in fresh["file_states"].items():
        path = pathlib.Path(path)
        if digest(path.read_bytes() if path.exists() else None) != expected:
            raise ValueError("approved mutation list changed; rerun plan and approve the new fingerprint")
    created = []
    try:
        for mutation in fresh["mutation_list"]:
            if mutation["kind"] == "directory":
                path = pathlib.Path(mutation["file"])
                path.mkdir()
                created.append(path)
        composer.write_all(writes)
    except (OSError, composer.ComposeError) as exc:
        for path in reversed(created):
            path.rmdir()
        raise ValueError(str(exc)) from exc
    return fresh


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
