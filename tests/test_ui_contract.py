import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "frontend" / "src" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "frontend" / "src" / "main.jsx").read_text(encoding="utf-8")


class MobileChatUiContractTests(unittest.TestCase):
    def test_mobile_viewport_supports_virtual_keyboard_resize(self):
        self.assertIn("interactive-widget=resizes-content", HTML)
        self.assertIn("visual-viewport-height", CSS)
        self.assertIn("visual-viewport-height", MAIN)

    def test_mobile_composer_remains_in_layout_and_inside_safe_area(self):
        self.assertIn(".chat-composer", CSS)
        self.assertIn("env(safe-area-inset-bottom)", CSS)
        self.assertIn("position:sticky", CSS)

    def test_long_message_media_tables_and_code_cannot_expand_page(self):
        self.assertIn("overflow-x:hidden", CSS)
        self.assertIn(".chat-message-content table", CSS)
        self.assertIn("overflow-x:auto", CSS)
        self.assertIn(".chat-message-content img", CSS)
        self.assertIn("overflow-wrap:anywhere", CSS)

    def test_tablet_layout_has_portrait_and_landscape_safeguards(self):
        self.assertIn("@media(min-width:701px) and (max-width:1050px)", CSS)
        self.assertIn("grid-template-columns:minmax(190px,34%)", CSS)
        self.assertIn("@media(max-width:700px) and (orientation:landscape)", CSS)

    def test_chat_status_retry_history_search_and_mobile_menu_close_exist(self):
        self.assertIn("Abud sedang memproses", MAIN)
        self.assertIn("Merekam suara", MAIN)
        self.assertIn("Coba lagi", MAIN)
        self.assertIn("Cari percakapan", MAIN)
        self.assertIn("setMobileOpen(false)", MAIN)
        self.assertIn("aria-current", MAIN)


if __name__ == "__main__":
    unittest.main()
