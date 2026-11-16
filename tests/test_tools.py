import unittest
from app import tools


class AgentToolTests(unittest.TestCase):
    def test_calculate(self):
        result = tools.execute_tool(
            "calculate", {"expression": "12 * (3 + 2)"}, {}
        )
        self.assertEqual(result["result"], 60)

    def test_calculator_rejects_code(self):
        with self.assertRaises(Exception):
            tools.calculate("__import__('os').system('id')")

    def test_unknown_tool_rejected(self):
        with self.assertRaises(ValueError):
            tools.execute_tool("run_shell", {}, {})

    def test_guild_write_requires_admin(self):
        context = {
            "user_id": "123",
            "guild_id": "456",
            "context_type": "guild",
            "can_manage_guild_memory": False,
        }
        with self.assertRaises(PermissionError):
            tools.validate_memory_scope("guild", context, write=True)

    def test_global_memory_owner_only(self):
        context = {"user_id": "123"}
        with self.assertRaises(PermissionError):
            tools.validate_memory_scope("global", context, write=True)


if __name__ == "__main__":
    unittest.main()
