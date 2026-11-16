"""Read-only registry for ABUD SKILL.md files.

Skill content is treated as untrusted data.
No scripts, shell commands, or external code are executed here.
"""

import re
from pathlib import Path

DEFAULT_SKILLS_DIR = Path("/app/skills")
MAX_SKILLS = 200
MAX_SKILL_FILE_BYTES = 65536
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 500


def _safe_child_directory(root: Path, child: Path) -> bool:
    try:
        child.resolve(strict=True).relative_to(root.resolve(strict=True))
        return child.is_dir() and not child.is_symlink()
    except (OSError, ValueError):
        return False


def _parse_frontmatter(content: str) -> dict:
    lines = content.splitlines()

    if not lines or lines[0].strip() != "---":
        raise ValueError("Frontmatter SKILL.md tidak ditemukan.")

    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("Frontmatter SKILL.md tidak ditutup.")

    metadata = {}

    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        key, separator, value = line.partition(":")
        if not separator:
            continue

        key = key.strip().lower()
        value = value.strip().strip("\"'")

        if key in ("name", "description") and value:
            metadata[key] = value

    name = metadata.get("name", "").strip()
    description = metadata.get("description", "").strip()

    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValueError("Nama skill tidak valid.")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", name):
        raise ValueError("Format nama skill tidak valid.")

    if not description or len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError("Deskripsi skill tidak valid.")

    return {
        "name": name,
        "description": description,
    }


def discover_skills(skills_dir=None) -> list[dict]:
    """Discover valid skill metadata without executing skill content."""
    root = Path(skills_dir or DEFAULT_SKILLS_DIR)

    if not root.exists() or not root.is_dir():
        return []

    try:
        root = root.resolve(strict=True)
        entries = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []

    discovered = []

    for directory in entries:
        if len(discovered) >= MAX_SKILLS:
            break

        if not _safe_child_directory(root, directory):
            continue

        skill_file = directory / "SKILL.md"

        if skill_file.is_symlink() or not skill_file.is_file():
            continue

        try:
            if skill_file.stat().st_size > MAX_SKILL_FILE_BYTES:
                continue

            content = skill_file.read_text(encoding="utf-8")
            metadata = _parse_frontmatter(content)

            discovered.append({
                "id": directory.name,
                "name": metadata["name"],
                "description": metadata["description"],
            })
        except (OSError, UnicodeError, ValueError):
            continue

    return discovered


def read_skill(skill_id: str, skills_dir=None) -> dict:
    """Read a skill after validating its ID and path."""
    if not isinstance(skill_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", skill_id
    ):
        raise ValueError("ID skill tidak valid.")

    root = Path(skills_dir or DEFAULT_SKILLS_DIR).resolve(strict=True)
    directory = root / skill_id

    if not _safe_child_directory(root, directory):
        raise ValueError("Direktori skill tidak valid.")

    skill_file = directory / "SKILL.md"

    if skill_file.is_symlink() or not skill_file.is_file():
        raise FileNotFoundError("SKILL.md tidak ditemukan.")

    if skill_file.stat().st_size > MAX_SKILL_FILE_BYTES:
        raise ValueError("Ukuran SKILL.md melebihi batas.")

    content = skill_file.read_text(encoding="utf-8")
    metadata = _parse_frontmatter(content)

    return {
        "id": skill_id,
        "name": metadata["name"],
        "description": metadata["description"],
        "instructions": content,
    }
