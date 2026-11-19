"""Pure helpers for the public guild-install link."""
import re
from urllib.parse import urlencode

# Discord permission bit positions, restricted to the features shipped by ABUD.
# Administrator, Manage Guild, Mention Everyone, Ban/Kick are not requested.
PERMISSION_BITS = (4, 6, 10, 11, 13, 14, 15, 16, 20, 21, 28, 35, 36, 38)
INSTALL_PERMISSIONS = sum(1 << bit for bit in PERMISSION_BITS)

def invite_url(application_id):
    if not isinstance(application_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", application_id) or int(application_id) >= 2**64:
        raise ValueError("Invalid bot application ID")
    return "https://discord.com/oauth2/authorize?" + urlencode({
        "client_id": application_id,
        "scope": "bot applications.commands",
        "permissions": str(INSTALL_PERMISSIONS),
        "integration_type": "0",
    })
