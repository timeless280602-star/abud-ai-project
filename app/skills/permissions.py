"""Default-deny permission policy for ABUD skills."""

import re

DEFAULT_POLICY = {
    "read_instructions": False,
    "execute_code": False,
    "shell_access": False,
    "network_access": False,
    "filesystem_access": False,
    "database_access": False,
    "tool_access": False,
}

# Hanya skill yang ditinjau dan disetujui boleh diaktifkan.
SKILL_POLICIES = {
    "testing": {
        "read_instructions": True,
    },
}


def get_skill_permissions(skill_id: str) -> dict:
    if not isinstance(skill_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", skill_id
    ):
        raise ValueError("ID skill tidak valid.")

    policy = dict(DEFAULT_POLICY)
    configured = SKILL_POLICIES.get(skill_id, {})

    for permission in DEFAULT_POLICY:
        if permission in configured:
            policy[permission] = configured[permission] is True

    return policy


def is_skill_allowed(skill_id: str) -> bool:
    return get_skill_permissions(skill_id)["read_instructions"]


def can_execute_code(skill_id: str) -> bool:
    return get_skill_permissions(skill_id)["execute_code"]
