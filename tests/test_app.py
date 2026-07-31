import tempfile
import unittest
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("requests", types.ModuleType("requests"))
sys.modules.setdefault("websocket", types.ModuleType("websocket"))

from app import MAPPING_DEFAULTS, collect_files, read_mapping_file, render_content


class NumberedFilesTests(unittest.TestCase):
    def test_orders_mixed_extensions(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("3.gif", "1.png", "2.webp", "note.txt"):
                Path(folder, name).touch()
            files, ignored = collect_files(folder, "number")
            self.assertEqual([path.name for path in files], ["1.png", "2.webp", "3.gif"])

    def test_rejects_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "1.png").touch()
            Path(folder, "3.png").touch()
            with self.assertRaisesRegex(ValueError, "2"):
                collect_files(folder, "number")

    def test_natural_filename_order(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("image10.png", "apple.gif", "image2.png", "Banana.webp"):
                Path(folder, name).touch()
            files, ignored = collect_files(folder, "name")
            self.assertEqual(
                [path.name for path in files],
                ["apple.gif", "Banana.webp", "image2.png", "image10.png"],
            )


class ContentRenderingTests(unittest.TestCase):
    def test_converts_https_markdown_link(self):
        rendered = render_content("사이트: [개드립](https://www.dogdrip.net/)\n끝")
        self.assertIn('<a href="https://www.dogdrip.net/"', rendered)
        self.assertIn(">개드립</a><br>끝", rendered)

    def test_escapes_html_and_rejects_unsafe_link_protocol(self):
        rendered = render_content('<script>x</script> [실행](javascript:alert(1))')
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn('<a href="javascript:', rendered)

    def test_converts_remote_markdown_image(self):
        rendered = render_content('그림: ![샘플 이미지](https://example.com/picture.png)')
        self.assertIn('<img src="https://example.com/picture.png"', rendered)
        self.assertIn('alt="샘플 이미지"', rendered)

    def test_converts_remote_image_with_dimensions(self):
        rendered = render_content('![배너](https://example.com/banner.png){320, 200}')
        self.assertIn('width="320" height="200"', rendered)
        self.assertIn("width:320px;height:200px", rendered)

    def test_caps_image_dimensions(self):
        rendered = render_content('![큰 이미지](https://example.com/large.png){99999, 5000}')
        self.assertIn('width="4096" height="4096"', rendered)

    def test_does_not_convert_local_or_unsafe_image_path(self):
        rendered = render_content('![로컬](C:/images/test.png) ![위험](javascript:alert(1))')
        self.assertNotIn("<img", rendered)

    def test_converts_standalone_dashes_to_horizontal_rule(self):
        rendered = render_content("위 문단\n---\n아래 문단")
        self.assertEqual(rendered, "위 문단<hr>아래 문단")

    def test_preserves_explicit_blank_line_around_rule(self):
        rendered = render_content("위 문단\n\n---\n\n아래 문단")
        self.assertEqual(rendered, "위 문단<br><hr><br>아래 문단")

    def test_does_not_convert_inline_dashes(self):
        rendered = render_content("앞 --- 뒤")
        self.assertEqual(rendered, "앞 --- 뒤")


class MappingConfigTests(unittest.TestCase):
    def test_duplicate_keys_use_last_value(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "settings.ini")
            path.write_text('[mapping]\ntag_selector = input[name="old"]\ntag_selector = input[name="new"]\n', encoding="utf-8")
            mapping = read_mapping_file(path)
            self.assertEqual(mapping["tag_selector"], 'input[name="new"]')
            self.assertEqual(mapping["target_host"], MAPPING_DEFAULTS["target_host"])

    def test_percent_sign_is_not_interpolated(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "settings.ini")
            path.write_text('[mapping]\ncontent_selector = input[data-width="100%"]\n', encoding="utf-8")
            mapping = read_mapping_file(path)
            self.assertEqual(mapping["content_selector"], 'input[data-width="100%"]')


if __name__ == "__main__":
    unittest.main()
