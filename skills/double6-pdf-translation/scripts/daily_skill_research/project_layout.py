# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""输出路径守卫；保留源项目的拒绝规则。"""
from __future__ import annotations
import json,os
from pathlib import Path
POLICY_PATH="configs/storage_lifecycle_policy.json"

def _without_system_aliases(path: Path) -> Path:
    """Only macOS's fixed filesystem aliases may be traversed for output."""
    absolute = Path(os.path.abspath(path.expanduser()))
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if not cursor.is_symlink():
            continue
        if cursor.as_posix() in {"/tmp", "/var", "/etc"} and cursor.resolve() == Path("/private") / cursor.name:
            continue
        raise ValueError(f"OUTPUT_PATH_SYMLINK: {cursor}")
    # resolve only after checking every component, including ancestors of root.
    return absolute.resolve()

def validate_output_path(value: str | Path, *, root: Path | None = None) -> Path:
    """在创建目录前拒绝误传选项、路径穿越、重复项目嵌套和链接写入。"""
    raw = str(value)
    path = Path(raw).expanduser()
    if not raw.strip() or "\x00" in raw or ".." in path.parts:
        raise ValueError("OUTPUT_PATH_INVALID: empty, NUL or parent traversal")
    if any(part.startswith("-") for part in path.parts):
        raise ValueError("OUTPUT_PATH_OPTION_COMPONENT: option used as an output path")
    absolute = _without_system_aliases(path)
    if root is not None:
        root = _without_system_aliases(root)
        try:
            absolute.relative_to(root)
        except ValueError as exc:
            raise ValueError("OUTPUT_PATH_OUTSIDE_DECLARED_ROOT") from exc
    parts = absolute.parts
    for pos, part in enumerate(parts[:-1]):
        if part == "projects":
            project_id = parts[pos + 1]
            tail = parts[pos + 2:]
            if (tail and tail[0] in {project_id, "projects"}) or any(
                tail[index:index + 2] == ("projects", project_id) for index in range(len(tail) - 1)
            ):
                raise ValueError("OUTPUT_PATH_REPEATED_PROJECT: project root nested twice")
    # A retained exception acknowledges old data; it never grants a new output root.
    for parent in absolute.parents:
        policy_path = parent / POLICY_PATH
        if not policy_path.is_file():
            continue
        layout = json.loads(policy_path.read_text(encoding="utf-8")).get("output_layout", {})
        for entry in layout.get("retained_legacy_paths", []):
            legacy = parent / entry["path"]
            if absolute == legacy or absolute.is_relative_to(legacy):
                raise ValueError(f"OUTPUT_PATH_RETAINED_LEGACY: {entry['path']}")
        break
    return absolute
