import os
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image as PILImage

from app import (
    App,
    DEFAULT_URL,
    LEGACY_MAPPING_FILENAME,
    LEGACY_PROFILE_DIRECTORY,
    LEGACY_SETTINGS_FILENAME,
    MAPPING_DEFAULTS,
    MAPPING_FILENAME,
    PROFILE_DIRECTORY,
    SETTINGS_FILENAME,
    TagBadgeInput,
    WysiwygEditor,
    build_content_syntax,
    collect_files,
    decode_preview_image,
    matching_image_dimension,
    migrate_legacy_config,
    read_mapping_file,
    render_content,
)


class ImagePreviewTests(unittest.TestCase):
    def test_decodes_webp_and_jpeg_and_scales_preview(self):
        for image_format in ("WEBP", "JPEG"):
            source = PILImage.new("RGB", (800, 400), "red")
            encoded = io.BytesIO()
            source.save(encoded, format=image_format)
            preview = decode_preview_image(encoded.getvalue(), 320, 140)
            self.assertEqual(preview.mode, "RGBA")
            self.assertLessEqual(preview.width, 320)
            self.assertLessEqual(preview.height, 140)

    def test_matches_opposite_dimension_from_original_ratio(self):
        self.assertEqual(matching_image_dimension(400, 1600, 900), 225)
        self.assertEqual(matching_image_dimension(225, 900, 1600), 400)

    def test_rejects_non_positive_ratio_dimensions(self):
        with self.assertRaises(ValueError):
            matching_image_dimension(320, 0, 200)


class TagBadgeInputTests(unittest.TestCase):
    def test_korean_kieuk_does_not_commit_but_actual_comma_does(self):
        import tkinter as tk

        root = tk.Tk()
        root.geometry("300x80+-10000+-10000")
        try:
            value = tk.StringVar()
            widget = TagBadgeInput(root, value)
            widget.pack()
            root.update()
            empty_height = widget.winfo_height()
            widget.input_var.set("그림ㅋ")
            root.update()
            self.assertEqual(widget.tags, [])
            self.assertEqual(widget.input_var.get(), "그림ㅋ")

            widget.input_var.set("그림콘,")
            root.update()
            self.assertEqual(widget.tags, ["그림콘"])
            self.assertEqual(widget.input_var.get(), "")
            self.assertEqual(widget.winfo_height(), empty_height)
            badge = widget.badge_frame.winfo_children()[0]
            tag_label, close_label = badge.winfo_children()
            self.assertEqual(close_label.cget("text"), "X")
            self.assertEqual(close_label.cget("font"), tag_label.cget("font"))
            self.assertEqual(close_label.winfo_rootx() - (tag_label.winfo_rootx() + tag_label.winfo_width()), 2)
        finally:
            root.destroy()


class SimpleVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class DefaultUrlTests(unittest.TestCase):
    def test_reset_default_url_restores_and_saves_address(self):
        app = object.__new__(App)
        app.url = SimpleVar("https://naver.com")
        calls = []
        app.save_settings = lambda: calls.append("saved")
        app.set_status = lambda text: calls.append(text)
        app.write_log = lambda text: calls.append(text)

        app.reset_default_url()

        self.assertEqual(app.url.get(), DEFAULT_URL)
        self.assertEqual(calls[0], "saved")


class SimpleText:
    def __init__(self, value=""):
        self.value = value

    def index(self, _mark):
        return f"1.{len(self.value)}"

    def get(self, _start, _end):
        return ""

    def insert(self, _mark, text):
        self.value += text

    def focus_set(self):
        pass


class SimpleEditor:
    def __init__(self):
        self.value = ""

    def insert_html(self, value):
        self.value += value

    def focus_editor(self):
        pass


@unittest.skip("Legacy Markdown expectations replaced by HTML-only editor tests")
class ContentToolbarTests(unittest.TestCase):
    def test_builds_link(self):
        self.assertEqual(build_content_syntax("link", text="개드립", url="https://www.dogdrip.net"), "[개드립](https://www.dogdrip.net)")

    def test_builds_image(self):
        self.assertEqual(build_content_syntax("image", text="설명", url="https://example.com/a.png"), "![설명](https://example.com/a.png)")

    def test_builds_image_without_description(self):
        self.assertEqual(build_content_syntax("image", text="", url="https://example.com/a.png"), "![](https://example.com/a.png)")

    def test_link_still_requires_display_text(self):
        with self.assertRaisesRegex(ValueError, "표시 텍스트"):
            build_content_syntax("link", text="", url="https://example.com")

    def test_removes_duplicated_url_schemes(self):
        self.assertEqual(build_content_syntax("link", text="링크", url="https://http://example.com"), "[링크](http://example.com)")
        self.assertEqual(build_content_syntax("image", text="이미지", url="https://https://example.com/a.png"), "![이미지](https://example.com/a.png)")

    def test_builds_sized_image(self):
        self.assertEqual(build_content_syntax("sized_image", text="설명", url="https://example.com/a.png", width="320", height="200"), "![설명](https://example.com/a.png){320,200}")

    def test_rejects_invalid_url(self):
        with self.assertRaisesRegex(ValueError, "http"):
            build_content_syntax("link", text="개드립", url="javascript:alert(1)")

    def test_rejects_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "1~4096"):
            build_content_syntax("sized_image", text="설명", url="https://example.com/a.png", width="0", height="200")

    def test_inserts_rule_on_its_own_line(self):
        app = object.__new__(App)
        app.content_editor = SimpleEditor()
        app.insert_content_syntax("rule")
        self.assertEqual(app.content_editor.value, "<hr>")


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

    def test_reverse_filename_order(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ("image10.png", "image2.png", "apple.gif"):
                Path(folder, name).touch()
            files, _ = collect_files(folder, "name_desc")
            self.assertEqual([path.name for path in files], ["image10.png", "image2.png", "apple.gif"])

    def test_modified_date_order_both_directions(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder, "old.png")
            new = Path(folder, "new.png")
            old.touch()
            new.touch()
            os.utime(old, (1000, 1000))
            os.utime(new, (2000, 2000))
            ascending, _ = collect_files(folder, "mtime")
            descending, _ = collect_files(folder, "mtime_desc")
            self.assertEqual([path.name for path in ascending], ["old.png", "new.png"])
            self.assertEqual([path.name for path in descending], ["new.png", "old.png"])


@unittest.skip("Markdown rendering is intentionally no longer supported")
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


class HtmlOnlyEditorTests(unittest.TestCase):
    def test_toolbar_builds_html_directly(self):
        self.assertEqual(
            build_content_syntax("link", text="DogDrip", url="https://www.dogdrip.net"),
            '<a href="https://www.dogdrip.net" target="_blank">DogDrip</a>',
        )
        self.assertEqual(
            build_content_syntax("image", text="", url="https://example.com/a.webp"),
            '<img src="https://example.com/a.webp" alt="">',
        )
        self.assertIn(
            'width="320" height="200"',
            build_content_syntax("sized_image", text="preview", url="https://example.com/a.jpg", width="320", height="200"),
        )

    def test_plain_markdown_like_text_is_not_interpreted(self):
        source = "[link](https://example.com)\n![](https://example.com/a.png)\n---"
        rendered = render_content(source)
        self.assertEqual(rendered, source.replace("\n", "<br>"))
        self.assertNotIn("<a ", rendered)
        self.assertNotIn("<img ", rendered)
        self.assertNotIn("<hr", rendered)

    def test_image_size_allows_single_dimension(self):
        width_only = build_content_syntax("sized_image", text="", url="https://example.com/a.png", width="320", height="")
        self.assertIn('width="320"', width_only)
        self.assertNotIn("height=", width_only)
        height_only = build_content_syntax("sized_image", text="", url="https://example.com/a.png", width="", height="200")
        self.assertIn('height="200"', height_only)
        self.assertNotIn("width=", height_only)

    def test_html_toolbar_validation_is_preserved(self):
        with self.assertRaises(ValueError):
            build_content_syntax("link", text="", url="https://example.com")
        with self.assertRaises(ValueError):
            build_content_syntax("image", text="preview", url="javascript:alert(1)")
        with self.assertRaises(ValueError):
            build_content_syntax("sized_image", text="preview", url="https://example.com/a.png", width="0", height="200")

    def test_existing_link_can_be_edited(self):
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.geometry("640x400+-10000+-10000")
        try:
            editor = WysiwygEditor(root, '<a href="https://old.example">Old text</a>')
            editor.pack(fill="both", expand=True)
            root.update()
            tag = next(iter(editor.links))
            binding = editor.text.tk.call(editor.text._w, "tag", "bind", tag, "<Button-3>")
            self.assertTrue(binding)
            editor._open_link_edit(tag)
            root.update()
            dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            entries = [widget for widget in descendants(dialog) if isinstance(widget, ttk.Entry)]
            entries[0].delete(0, "end"); entries[0].insert(0, "New text")
            entries[1].delete(0, "end"); entries[1].insert(0, "https://new.example")
            confirm = next(widget for widget in descendants(dialog) if isinstance(widget, ttk.Button) and widget.cget("text") == "확인")
            confirm.invoke()
            root.update()
            self.assertIn('href="https://new.example"', editor.get_html())
            self.assertIn(">New text</a>", editor.get_html())
        finally:
            root.destroy()

    def test_plain_url_paste_creates_hyperlink(self):
        import tkinter as tk

        root = tk.Tk(); root.geometry("640x300+-10000+-10000")
        try:
            editor = WysiwygEditor(root, "")
            editor.pack(fill="both", expand=True); root.update()
            root.clipboard_clear(); root.clipboard_append("https://example.com/page")
            self.assertEqual(editor._paste_rich_html(), "break")
            self.assertEqual(
                editor.get_html(),
                '<a href="https://example.com/page" target="_blank">https://example.com/page</a>',
            )
        finally:
            root.destroy()

    def test_link_copy_and_paste_preserves_hyperlink(self):
        import tkinter as tk

        root = tk.Tk(); root.geometry("640x300+-10000+-10000")
        try:
            editor = WysiwygEditor(root, '<a href="https://example.com">Example</a>')
            editor.pack(fill="both", expand=True); root.update()
            tag = next(iter(editor.links))
            start, end = editor.text.tag_ranges(tag)
            editor.text.tag_add("sel", start, end)
            self.assertEqual(editor._copy_content(), "break")
            editor.text.tag_remove("sel", "1.0", "end")
            editor.text.mark_set("insert", "end-1c")
            self.assertEqual(editor._paste_rich_html(), "break")
            self.assertEqual(editor.get_html().count('<a href="https://example.com"'), 2)
        finally:
            root.destroy()

    def test_image_copy_cut_paste_undo_and_redo(self):
        import tkinter as tk

        encoded = io.BytesIO()
        PILImage.new("RGB", (32, 24), "blue").save(encoded, format="PNG")

        class Response:
            content = encoded.getvalue()
            def raise_for_status(self):
                return None

        root = tk.Tk(); root.geometry("640x400+-10000+-10000")
        try:
            with patch("app.requests.get", return_value=Response()):
                editor = WysiwygEditor(root, '<img src="https://example.com/image.png" alt="sample" width="32">')
                editor.pack(fill="both", expand=True); root.update()
                label = root.nametowidget(next(iter(editor.image_data)))
                editor._select_embed(label)
                self.assertEqual(editor._copy_content(), "break")
                editor.text.mark_set("insert", "end-1c")
                self.assertEqual(editor._paste_rich_html(), "break")
                root.update()
                self.assertEqual(editor.get_html().count("<img "), 2)

                first_label = root.nametowidget(next(iter(editor.image_data)))
                editor._select_embed(first_label)
                self.assertEqual(editor._cut_content(), "break")
                self.assertEqual(editor.get_html().count("<img "), 1)
                editor._undo(); root.update()
                self.assertEqual(editor.get_html().count("<img "), 2)
                editor._redo(); root.update()
                self.assertEqual(editor.get_html().count("<img "), 1)
        finally:
            root.destroy()

    def test_text_changes_are_in_custom_undo_history(self):
        import tkinter as tk

        root = tk.Tk(); root.geometry("640x300+-10000+-10000")
        try:
            editor = WysiwygEditor(root, "")
            editor.pack(fill="both", expand=True); root.update()
            editor.text.insert("insert", "typed text")
            editor._commit_history(force=True)
            editor._undo()
            self.assertEqual(editor.get_html(), "")
            editor._redo()
            self.assertEqual(editor.get_html(), "typed text")
        finally:
            root.destroy()

    def test_editor_background_has_context_menu_and_plain_paste(self):
        import tkinter as tk

        root = tk.Tk(); root.geometry("640x300+-10000+-10000")
        try:
            editor = WysiwygEditor(root, "")
            editor.pack(fill="both", expand=True); root.update()
            self.assertTrue(editor.text.bind("<Button-3>"))
            root.clipboard_clear(); root.clipboard_append("일반 텍스트")
            editor._paste_from_menu()
            self.assertEqual(editor.get_html(), "일반 텍스트")
            editor._undo()
            self.assertEqual(editor.get_html(), "")
        finally:
            root.destroy()


class MappingConfigTests(unittest.TestCase):
    def test_migrates_legacy_browser_profile_directory_with_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            legacy_profile = directory / LEGACY_PROFILE_DIRECTORY
            legacy_profile.mkdir()
            (legacy_profile / "Login Data").write_text("preserved", encoding="utf-8")

            current_profile = migrate_legacy_config(directory, LEGACY_PROFILE_DIRECTORY, PROFILE_DIRECTORY)

            self.assertFalse(legacy_profile.exists())
            self.assertEqual((current_profile / "Login Data").read_text(encoding="utf-8"), "preserved")

    def test_migrates_legacy_json_and_ini_without_changing_content(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            legacy_json = directory / LEGACY_SETTINGS_FILENAME
            legacy_ini = directory / LEGACY_MAPPING_FILENAME
            json_content = '{"url": "https://example.com", "tags": "one,two"}'
            ini_content = '[mapping]\\ntarget_host = example.com\\n'
            legacy_json.write_text(json_content, encoding="utf-8")
            legacy_ini.write_text(ini_content, encoding="utf-8")

            new_json = migrate_legacy_config(directory, LEGACY_SETTINGS_FILENAME, SETTINGS_FILENAME)
            new_ini = migrate_legacy_config(directory, LEGACY_MAPPING_FILENAME, MAPPING_FILENAME)

            self.assertFalse(legacy_json.exists())
            self.assertFalse(legacy_ini.exists())
            self.assertEqual(new_json.read_text(encoding="utf-8"), json_content)
            self.assertEqual(new_ini.read_text(encoding="utf-8"), ini_content)

    def test_existing_new_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            legacy = directory / LEGACY_SETTINGS_FILENAME
            current = directory / SETTINGS_FILENAME
            legacy.write_text("legacy", encoding="utf-8")
            current.write_text("current", encoding="utf-8")

            result = migrate_legacy_config(directory, LEGACY_SETTINGS_FILENAME, SETTINGS_FILENAME)

            self.assertEqual(result.read_text(encoding="utf-8"), "current")
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy")

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
