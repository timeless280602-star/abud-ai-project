"""Unified, read-only ABUD Skill Engine."""

from app.skills.registry import discover_skills, read_skill
from app.skills.matcher import match_skills
from app.skills.permissions import get_skill_permissions

MAX_INSTRUCTIONS_LENGTH = 12000


def list_skills(skills_dir=None):
    return discover_skills(skills_dir)


def get_relevant_skills(message, skills_dir=None, limit=3):
    matches = match_skills(message, skills_dir, limit)
    selected = []

    for match in matches:
        permissions = get_skill_permissions(match["id"])

        if not permissions["read_instructions"]:
            continue

        try:
            skill = read_skill(match["id"], skills_dir)
        except (OSError, ValueError):
            continue

        instructions = skill["instructions"]

        if len(instructions) > MAX_INSTRUCTIONS_LENGTH:
            continue

        selected.append({
            "id": skill["id"],
            "name": skill["name"],
            "description": skill["description"],
            "score": match["score"],
            "instructions": instructions,
            "permissions": permissions,
        })

    return selected
