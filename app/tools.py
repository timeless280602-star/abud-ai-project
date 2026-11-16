import ast
import json
import math
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from app import database


# ==============================================
# TOOL DEFINITIONS
# ==============================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Mendapatkan tanggal, waktu, dan zona waktu saat ini."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Menghitung ekspresi matematika seperti penjumlahan, "
                "pengurangan, perkalian, pembagian, pangkat, dan modulo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Ekspresi matematika yang akan dihitung."
                    }
                },
                "required": ["expression"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_abud_status",
            "description": (
                "Memeriksa status database dan statistik sistem Memory Abud."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": (
                "Mencari informasi dalam Personal Memory milik pengguna "
                "atau Guild Memory server yang sedang aktif."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "guild"],
                        "description": "Jenis Memory yang dicari."
                    },
                    "query": {
                        "type": "string",
                        "description": "Kata atau frasa yang ingin dicari."
                    }
                },
                "required": ["scope", "query"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": (
                "Menyimpan informasi penting ke Memory Abud. "
                "Gunakan personal untuk informasi pengguna, guild "
                "untuk informasi server, dan global khusus Bos Bara. "
                "Jangan menyimpan obrolan sementara atau informasi "
                "yang tidak berguna untuk masa depan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "guild", "global"]
                    },
                    "content": {
                        "type": "string",
                        "description": "Informasi penting yang disimpan."
                    },
                    "category": {
                        "type": "string",
                        "description": "Kategori Global Memory, opsional."
                    }
                },
                "required": ["scope", "content"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_memory",
            "description": (
                "Melihat daftar Memory berdasarkan scope yang diminta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "guild", "global"]
                    }
                },
                "required": ["scope"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_memory",
            "description": (
                "Menghapus satu Memory berdasarkan ID dan scope. "
                "Jangan menghapus sebelum pengguna jelas meminta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["personal", "guild", "global"]
                    },
                    "memory_id": {
                        "type": "integer",
                        "minimum": 1
                    }
                },
                "required": ["scope", "memory_id"],
                "additionalProperties": False
            }
        }
    }

]


# Daftar tools dipisahkan tanpa menduplikasi definisi aslinya.
MEMORY_TOOL_NAMES = {
    "search_memory",
    "save_memory",
    "list_memory",
    "delete_memory",
}

GENERAL_TOOLS = [
    tool for tool in TOOLS
    if tool["function"]["name"] not in MEMORY_TOOL_NAMES
    and tool["function"]["name"] != "get_abud_status"
]

MEMORY_TOOLS = [
    tool for tool in TOOLS
    if tool["function"]["name"] in MEMORY_TOOL_NAMES
]


# ==============================================
# SAFE CALCULATOR
# ==============================================

BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow
}

UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg
}


def evaluate_math_node(node):
    if isinstance(node, ast.Expression):
        return evaluate_math_node(node.body)

    if isinstance(node, ast.Constant):
        value = node.value

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Hanya angka yang diperbolehkan.")

        if abs(value) > 1e12:
            raise ValueError("Angka terlalu besar.")

        return value

    if isinstance(node, ast.BinOp):
        operator_type = type(node.op)

        if operator_type not in BINARY_OPERATORS:
            raise ValueError("Operator tidak diperbolehkan.")

        left = evaluate_math_node(node.left)
        right = evaluate_math_node(node.right)

        if operator_type is ast.Pow:
            if abs(right) > 12:
                raise ValueError("Pangkat maksimal 12.")

            if abs(left) > 1e6:
                raise ValueError("Angka dasar terlalu besar.")

        result = BINARY_OPERATORS[operator_type](left, right)

        if not isinstance(result, (int, float)):
            raise ValueError("Hasil perhitungan tidak valid.")

        if not math.isfinite(result) or abs(result) > 1e15:
            raise ValueError("Hasil perhitungan di luar batas.")

        return result

    if isinstance(node, ast.UnaryOp):
        operator_type = type(node.op)

        if operator_type not in UNARY_OPERATORS:
            raise ValueError("Operator tidak diperbolehkan.")

        return UNARY_OPERATORS[operator_type](
            evaluate_math_node(node.operand)
        )

    raise ValueError("Ekspresi mengandung operasi yang tidak diizinkan.")


def calculate(expression):
    if not isinstance(expression, str):
        raise ValueError("Ekspresi harus berupa teks.")

    expression = expression.strip()

    if not expression or len(expression) > 200:
        raise ValueError("Ekspresi kosong atau terlalu panjang.")

    tree = ast.parse(expression, mode="eval")
    result = evaluate_math_node(tree)

    return {
        "expression": expression,
        "result": result
    }


# ==============================================
# MEMORY SEARCH
# ==============================================

def search_memory(scope, query, context):
    if not isinstance(query, str):
        raise ValueError("Query pencarian harus berupa teks.")

    query = query.strip()

    if len(query) < 2 or len(query) > 100:
        raise ValueError("Query harus berisi 2 sampai 100 karakter.")

    user_id = context.get("user_id")
    guild_id = context.get("guild_id")
    context_type = context.get("context_type")

    if scope == "personal":
        if not user_id:
            return {
                "scope": scope,
                "results": [],
                "message": "Identitas pengguna tidak tersedia."
            }

        memories = database.get_memories(user_id, limit=100)

    elif scope == "guild":
        if context_type != "guild" or not guild_id:
            return {
                "scope": scope,
                "results": [],
                "message": "Guild Memory hanya tersedia di dalam server."
            }

        memories = database.get_guild_memories(guild_id, limit=100)

    else:
        raise ValueError("Scope Memory tidak diperbolehkan.")

    keyword = query.casefold()
    matches = []

    for item in memories:
        content = str(item.get("content", ""))

        if keyword in content.casefold():
            matches.append({
                "id": item["id"],
                "content": content[:500]
            })

        if len(matches) >= 5:
            break

    return {
        "scope": scope,
        "results": matches,
        "total_found": len(matches)
    }


# ==============================================
# MEMORY MANAGEMENT TOOLS
# ==============================================

GLOBAL_MEMORY_OWNER_ID = "1357798812168618044"


def validate_memory_scope(scope, context, write=False):
    user_id = context.get("user_id")
    guild_id = context.get("guild_id")

    if not user_id:
        raise ValueError("Identitas pengguna tidak tersedia.")

    if scope == "personal":
        return

    if scope == "guild":
        if context.get("context_type") != "guild" or not guild_id:
            raise ValueError("Guild Memory hanya tersedia di server.")

        if write and not context.get("can_manage_guild_memory", False):
            raise PermissionError(
                "Hanya Server Owner dan Administrator yang boleh "
                "mengubah Guild Memory."
            )
        return

    if scope == "global":
        if str(user_id) != GLOBAL_MEMORY_OWNER_ID:
            raise PermissionError(
                "Global Memory hanya boleh dikelola oleh Bos Bara."
            )
        return

    raise ValueError("Scope Memory tidak valid.")


def save_memory_tool(scope, content, context, category="general"):
    validate_memory_scope(scope, context, write=True)

    if not isinstance(content, str):
        raise ValueError("Isi Memory harus berupa teks.")

    content = content.strip()

    if not content or len(content) > 1000:
        raise ValueError("Isi Memory harus berisi 1 sampai 1000 karakter.")

    user_id = str(context["user_id"])
    guild_id = context.get("guild_id")

    if scope == "personal":
        memory_id = database.save_memory(user_id, content)

    elif scope == "guild":
        memory_id = database.save_guild_memory(
            guild_id,
            content,
            created_by_user_id=user_id
        )

    else:
        category = str(category or "general").strip()[:50] or "general"
        memory_id = database.save_global_memory(
            content,
            category=category,
            created_by_user_id=user_id
        )

    return {
        "event": "memory_saved",
        "scope": scope,
        "memory_id": memory_id,
        "content": content,
        "message": "Memory berhasil disimpan."
    }


def list_memory_tool(scope, context):
    validate_memory_scope(scope, context)

    if scope == "personal":
        memories = database.get_memories(context["user_id"], limit=100)

    elif scope == "guild":
        memories = database.get_guild_memories(
            context["guild_id"], limit=100
        )

    else:
        memories = database.get_global_memories(limit=100)

    return {
        "scope": scope,
        "total": len(memories),
        "memories": [
            {
                "id": item["id"],
                "content": item["content"],
                **(
                    {"category": item["category"]}
                    if scope == "global" else {}
                )
            }
            for item in memories
        ]
    }


def delete_memory_tool(scope, memory_id, context):
    validate_memory_scope(scope, context, write=True)

    try:
        memory_id = int(memory_id)
    except (TypeError, ValueError):
        raise ValueError("Memory ID tidak valid.")

    if memory_id < 1:
        raise ValueError("Memory ID harus lebih besar dari nol.")

    if scope == "personal":
        deleted = database.delete_memory(
            context["user_id"], memory_id
        )

    elif scope == "guild":
        deleted = database.delete_guild_memory(
            context["guild_id"], memory_id
        )

    else:
        deleted = database.delete_global_memory(memory_id)

    if not deleted:
        raise ValueError("Memory tidak ditemukan atau sudah dihapus.")

    return {
        "event": "memory_deleted",
        "scope": scope,
        "memory_id": memory_id,
        "message": "Memory berhasil dihapus."
    }


# ==============================================
# TOOL EXECUTION
# ==============================================

def execute_tool(name, arguments, context):
    if not isinstance(arguments, dict):
        raise ValueError("Parameter tool harus berupa JSON object.")

    if name == "get_current_time":
        now = datetime.now(ZoneInfo("Asia/Jakarta"))

        return {
            "timezone": "Asia/Jakarta",
            "datetime": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day": now.strftime("%A")
        }

    if name == "calculate":
        if set(arguments) != {"expression"}:
            raise ValueError("Parameter calculate tidak valid.")

        return calculate(arguments["expression"])

    if name == "get_abud_status":
        if str((context or {}).get("user_id")) != GLOBAL_MEMORY_OWNER_ID:
            raise PermissionError("Akses status sistem hanya untuk Bos Bara.")

        if arguments:
            raise ValueError("Tool ini tidak menerima parameter.")

        status = database.get_database_status()

        return {
            "status": "online",
            "database": "connected",
            "users": status["users"],
            "conversations": status["conversations"],
            "personal_memories": status["personal_memories"],
            "guilds": status["guilds"],
            "guild_memories": status["guild_memories"],
            "global_memories": status["global_memories"]
        }

    if name == "search_memory":
        if set(arguments) != {"scope", "query"}:
            raise ValueError("Parameter search_memory tidak valid.")

        return search_memory(
            arguments["scope"],
            arguments["query"],
            context
        )

    if name == "save_memory":
        if not {"scope", "content"}.issubset(arguments):
            raise ValueError("Parameter save_memory tidak lengkap.")
        if set(arguments) - {"scope", "content", "category"}:
            raise ValueError("Parameter save_memory tidak valid.")

        return save_memory_tool(
            arguments["scope"],
            arguments["content"],
            context,
            arguments.get("category", "general")
        )

    if name == "list_memory":
        if set(arguments) != {"scope"}:
            raise ValueError("Parameter list_memory tidak valid.")

        return list_memory_tool(arguments["scope"], context)

    if name == "delete_memory":
        if set(arguments) != {"scope", "memory_id"}:
            raise ValueError("Parameter delete_memory tidak valid.")

        return delete_memory_tool(
            arguments["scope"],
            arguments["memory_id"],
            context
        )

    raise ValueError("Tool tidak dikenal atau tidak diizinkan.")


def run_tool(name, arguments, context):
    try:
        result = execute_tool(name, arguments, context)

        return json.dumps(
            {
                "success": True,
                "data": result
            },
            ensure_ascii=False
        )

    except Exception as error:
        return json.dumps(
            {
                "success": False,
                "error": str(error)
            },
            ensure_ascii=False
        )
