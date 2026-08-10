import json
import html
import io
import configparser
import ctypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

# Tcl 8.6.13 on Windows can reject PyInstaller's underscore-prefixed library
# directories as well as backslash-form paths. Normalize both before tkinter
# creates its first interpreter. A one-file build only renames its temporary,
# automatically removed extraction directories.
if getattr(sys, "frozen", False) and sys.platform == "win32":
    _bundle_root = getattr(sys, "_MEIPASS", "")
    for _tk_library_var, _bundled_name, _normalized_name in (
        ("TCL_LIBRARY", "_tcl_data", "tcl8.6"),
        ("TK_LIBRARY", "_tk_data", "tk8.6"),
    ):
        _bundled_path = os.path.join(_bundle_root, _bundled_name)
        _normalized_path = os.path.join(_bundle_root, _normalized_name)
        try:
            if os.path.isdir(_bundled_path) and not os.path.exists(_normalized_path):
                os.replace(_bundled_path, _normalized_path)
        except OSError:
            _normalized_path = _bundled_path
        os.environ[_tk_library_var] = _normalized_path.replace("\\", "/")

import tkinter as tk
from pathlib import Path
from html.parser import HTMLParser
from tkinter import filedialog, font as tkfont, messagebox, ttk

import requests
import websocket
from PIL import Image, ImageTk


APP_TITLE = "개드립콘 업로더"
BRAND_TITLE = "DogDrip.Con Uploader"
APP_VERSION = "1.1.1"
DEFAULT_URL = "https://www.dogdrip.net/index.php?mid=dogcon&act=dispDogconWrite"
ONLINE_GUIDE_URL = "https://ssbbrr92.github.io/dogdrip-con-uploader/"
SETTINGS_FILENAME = "dogdrip-con-uploader-settings.json"
MAPPING_FILENAME = "dogdrip-con-uploader.ini"
LEGACY_SETTINGS_FILENAME = "dogcon-uploader-settings.json"
LEGACY_MAPPING_FILENAME = "dogcon-uploader.ini"
PROFILE_DIRECTORY = "dogdrip-con-browser-profile"
LEGACY_PROFILE_DIRECTORY = "dogcon-browser-profile"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
FONT_SIZE_OPTIONS = tuple(range(8, 17)) + (18, 20, 24, 28, 32, 36, 40, 48)
SORT_OPTIONS = {
    "파일 이름": "name",
    "파일 이름 (역순)": "name_desc",
    "수정된 날짜": "mtime",
    "수정된 날짜 (역순)": "mtime_desc",
}
MAPPING_DEFAULTS = {
    "target_host": "dogdrip.net",
    "main_file_name": "dogcon_main_file",
    "extra_file_pattern": "dogcon_file_{index}",
    "content_selector": 'textarea[name="content"], input[name="content"]',
    "editor_selector": 'form [contenteditable="true"]',
    "tag_selector": 'input[name="tags"], input[name="tag"]',
    "title_selector": 'input[name="title"]',
    "price_selector": 'input[name="price"]',
}


def build_content_syntax(kind, text="", url="", width="", height=""):
    text = text.strip()
    url = normalize_url_prefix(url)
    if kind not in {"link", "image", "sized_image"}:
        raise ValueError("지원하지 않는 본문 문법입니다.")
    if kind == "link" and not text:
        raise ValueError("표시 텍스트를 입력해 주세요.")
    if "]" in text or "\n" in text:
        raise ValueError("텍스트에는 ] 문자나 줄바꿈을 사용할 수 없습니다.")
    if not re.fullmatch(r"https?://\S+", url, re.IGNORECASE):
        raise ValueError("주소는 http:// 또는 https://로 시작해야 하며 공백을 포함할 수 없습니다.")
    if kind == "link":
        return f'<a href="{html.escape(url, quote=True)}" target="_blank">{html.escape(text)}</a>'
    if kind == "image":
        return f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(text, quote=True)}">'
    try:
        width_value = int(str(width).strip()) if str(width).strip() else None
        height_value = int(str(height).strip()) if str(height).strip() else None
    except ValueError as exc:
        raise ValueError("가로와 세로는 숫자로 입력해 주세요.") from exc
    if not width_value and not height_value:
        return f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(text, quote=True)}">'
    if any(value is not None and not 1 <= value <= 4096 for value in (width_value, height_value)):
        raise ValueError("가로와 세로는 1~4096 사이로 입력해 주세요.")
    size = (f' width="{width_value}"' if width_value else "") + (f' height="{height_value}"' if height_value else "")
    return f'<img src="{html.escape(url, quote=True)}" alt="{html.escape(text, quote=True)}"{size} data-sized="1">'


def normalize_url_prefix(value):
    value = (value or "").strip()
    match = re.match(r"^((?:https?://){2,})(.*)$", value, re.IGNORECASE)
    if not match:
        return value
    schemes = re.findall(r"https?://", match.group(1), re.IGNORECASE)
    return schemes[-1].lower() + match.group(2)


def open_online_guide():
    """Open the public manual in the user's default browser."""
    return webbrowser.open_new_tab(ONLINE_GUIDE_URL)


def center_toplevel(window, parent, width=None, height=None):
    parent.update_idletasks()
    window.update_idletasks()
    width = width or window.winfo_width() or window.winfo_reqwidth()
    height = height or window.winfo_height() or window.winfo_reqheight()
    x = parent.winfo_x() + (parent.winfo_width() - width) // 2
    y = parent.winfo_y() + (parent.winfo_height() - height) // 2
    x = max(0, min(x, window.winfo_screenwidth() - width))
    y = max(0, min(y, window.winfo_screenheight() - height))
    window.geometry(f"{width}x{height}+{x}+{y}")


def centered_messagebox(parent, kind, title, message):
    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.transient(parent)
    dialog.resizable(False, False)
    dialog.configure(bg="#ffffff")
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    accent = "#c94343" if kind == "showerror" else "#3478f6"
    symbol = "!" if kind == "showerror" else "i"
    content = tk.Frame(dialog, bg="#ffffff", padx=22, pady=20)
    content.pack(fill="both", expand=True)
    tk.Label(content, text=symbol, bg=accent, fg="#ffffff", width=2,
             font=("Arial", 13, "bold"), relief="flat").grid(row=0, column=0, sticky="n", padx=(0, 14))
    tk.Label(content, text=str(message), bg="#ffffff", fg="#26384d", justify="left",
             anchor="w", wraplength=340, font=("맑은 고딕", 10)).grid(row=0, column=1, sticky="nsew")
    button = tk.Button(content, text="확인", command=dialog.destroy, bg="#2e486b", fg="#ffffff",
                       activebackground="#213a5c", activeforeground="#ffffff", relief="flat",
                       borderwidth=0, padx=20, pady=6, font=("맑은 고딕", 9, "bold"), cursor="hand2")
    button.grid(row=1, column=1, sticky="e", pady=(20, 0))
    content.columnconfigure(1, weight=1)

    dialog.update_idletasks()
    center_toplevel(dialog, parent, max(400, min(500, dialog.winfo_reqwidth())), max(150, dialog.winfo_reqheight()))
    dialog.deiconify()
    dialog.update_idletasks()
    previous_grab = parent.grab_current()
    dialog.bind("<Return>", lambda _event: dialog.destroy())
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    dialog.grab_set()
    dialog.lift(parent)
    button.focus_set()
    try:
        parent.wait_window(dialog)
    finally:
        if previous_grab is not None and previous_grab.winfo_exists():
            previous_grab.grab_set()
    return "ok"


def add_tooltip(widget, text):
    state = {"window": None, "after": None, "suppress_until": 0.0}

    def show():
        state["after"] = None
        if (
            state["window"] is not None
            or not widget.winfo_exists()
            or time.monotonic() < state["suppress_until"]
            or not widget.winfo_viewable()
            or widget.winfo_toplevel().state() != "normal"
        ):
            return
        tip = tk.Toplevel(widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(
            tip, text=text, bg="#26384d", fg="#ffffff", padx=8, pady=4,
            font=("맑은 고딕", 9), relief="flat",
        ).pack()
        tip.update_idletasks()
        tip.geometry(f"+{widget.winfo_rootx()}+{widget.winfo_rooty() + widget.winfo_height() + 5}")
        state["window"] = tip

    def enter(_event=None):
        if time.monotonic() < state["suppress_until"]:
            return
        state["after"] = widget.after(450, show)

    def leave(_event=None):
        if state["after"] is not None:
            try:
                widget.after_cancel(state["after"])
            except tk.TclError:
                pass
            state["after"] = None
        if state["window"] is not None:
            try:
                state["window"].destroy()
            except tk.TclError:
                pass
            state["window"] = None

    def press(event=None):
        # 클릭으로 팝다운/팝오버를 연 직후 synthetic Enter가 다시 발생해도
        # 툴팁을 띄우지 않는다.
        state["suppress_until"] = time.monotonic() + 2.0
        leave(event)

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")
    widget.bind("<ButtonPress>", press, add="+")
    widget.winfo_toplevel().bind("<Unmap>", leave, add="+")
    widget.winfo_toplevel().bind("<Destroy>", leave, add="+")


def app_dir():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def migrate_legacy_config(directory, legacy_name, current_name):
    directory = Path(directory)
    legacy_path = directory / legacy_name
    current_path = directory / current_name
    if legacy_path.exists() and not current_path.exists():
        legacy_path.replace(current_path)
    return current_path


def resource_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def read_mapping_file(path):
    """Read a potentially user-edited INI without interpolation or strict duplicate failures."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error, UnicodeError):
        return dict(MAPPING_DEFAULTS)
    mapping = {}
    section = parser["mapping"] if parser.has_section("mapping") else {}
    for key, default in MAPPING_DEFAULTS.items():
        value = section.get(key, default)
        mapping[key] = value.strip() if isinstance(value, str) and value.strip() else default
    return mapping


def natural_key(path):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path.name)]


def parse_tags(value):
    return [tag.strip() for tag in (value or "").split(",") if tag.strip()]


def decode_preview_image(content, max_width, max_height):
    with Image.open(io.BytesIO(content)) as source:
        source.seek(0)
        preview = source.convert("RGBA")
    preview.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return preview


def matching_image_dimension(value, source_dimension, opposite_dimension):
    """Return the opposite image dimension while preserving the original ratio."""
    value = int(value)
    source_dimension = int(source_dimension)
    opposite_dimension = int(opposite_dimension)
    if value < 1 or source_dimension < 1 or opposite_dimension < 1:
        raise ValueError("Image dimensions must be positive.")
    return max(1, round(value * opposite_dimension / source_dimension))


def extract_cf_html(data):
    if not data:
        return ""
    for start_key, end_key in ((b"StartFragment:", b"EndFragment:"), (b"StartHTML:", b"EndHTML:")):
        start_match = re.search(start_key + rb"\s*(\d+)", data)
        end_match = re.search(end_key + rb"\s*(\d+)", data)
        if start_match and end_match:
            return data[int(start_match.group(1)):int(end_match.group(1))].decode("utf-8", "replace")
    return data.decode("utf-8", "replace")


class _ClipboardHtmlSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.output = []; self.anchor_open = False
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = normalize_url_prefix(dict(attrs).get("href", ""))
            if re.fullmatch(r"https?://\S+", href, re.IGNORECASE):
                self.output.append(f'<a href="{html.escape(href, quote=True)}" target="_blank">'); self.anchor_open = True
        elif tag.lower() == "img":
            values = dict(attrs)
            src = normalize_url_prefix(values.get("src", ""))
            if re.fullmatch(r"https?://\S+", src, re.IGNORECASE):
                alt = values.get("alt", "")
                width = values.get("width", "") if str(values.get("width", "")).isdigit() else ""
                height = values.get("height", "") if str(values.get("height", "")).isdigit() else ""
                kind = "sized_image" if width or height else "image"
                self.output.append(build_content_syntax(kind, text=alt, url=src, width=width, height=height))
        elif tag.lower() == "br": self.output.append("<br>")
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.anchor_open: self.output.append("</a>"); self.anchor_open = False
        elif tag.lower() in {"p", "div"}: self.output.append("<br>")
    def handle_data(self, data): self.output.append(html.escape(data))


def sanitize_clipboard_html(source):
    parser = _ClipboardHtmlSanitizer(); parser.feed(source or "")
    if parser.anchor_open: parser.output.append("</a>")
    return "".join(parser.output)


def get_windows_clipboard_html():
    if sys.platform != "win32": return ""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = ctypes.c_void_p
    fmt = user32.RegisterClipboardFormatW("HTML Format")
    if not user32.OpenClipboard(None): return ""
    try:
        handle = user32.GetClipboardData(fmt)
        if not handle: return ""
        kernel32.GlobalLock.restype = ctypes.c_void_p
        pointer = kernel32.GlobalLock(handle)
        if not pointer: return ""
        try: data = ctypes.string_at(pointer, kernel32.GlobalSize(handle))
        finally: kernel32.GlobalUnlock(handle)
        return extract_cf_html(data.rstrip(b"\0"))
    finally: user32.CloseClipboard()


def render_content(text):
    """Escape legacy plain text without interpreting Markdown syntax."""
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return html.escape(normalized).replace("\n", "<br>")


def editor_initial_html(content):
    content = (content or "").strip()
    if re.search(r"<(?:p|div|br|hr|a|img|strong|b|em|i|u|span)\b", content, re.IGNORECASE):
        return content
    return render_content(content)


class _EditorHtmlLoader(HTMLParser):
    """Load the small, supported HTML subset into the Tk text editor."""

    def __init__(self, editor):
        super().__init__(convert_charrefs=True)
        self.editor = editor
        self.formats = set()
        self.alignment = ""
        self.link_tag = ""
        self.stack = []

    @staticmethod
    def _style_values(attrs):
        style = dict(attrs).get("style", "")
        return {
            key.strip().lower(): value.strip().lower()
            for key, value in (item.split(":", 1) for item in style.split(";") if ":" in item)
        }

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "br":
            self.editor.text.insert("insert", "\n", self._active_tags())
            return
        if tag == "hr":
            self.editor._insert_rule()
            return
        if tag == "img":
            self.editor._insert_image(self.get_starttag_text())
            return
        self.stack.append((tag, set(self.formats), self.alignment, self.link_tag))
        values = dict(attrs)
        styles = self._style_values(attrs)
        if tag in {"strong", "b"}:
            self.formats.add("sem_bold")
        elif tag in {"em", "i"}:
            self.formats.add("sem_italic")
        elif tag == "u":
            self.formats.add("sem_underline")
        elif tag == "a":
            href = normalize_url_prefix(values.get("href", ""))
            if re.fullmatch(r"https?://\S+", href, re.IGNORECASE):
                self.link_tag = self.editor._create_link_tag(href)
        if tag == "span":
            size_match = re.match(r"(\d{1,2})(?:px)?$", styles.get("font-size", ""))
            if size_match and 8 <= int(size_match.group(1)) <= 48:
                self.editor._ensure_size_tag(int(size_match.group(1)))
                self.formats = {name for name in self.formats if not name.startswith("sem_size_")}
                self.formats.add(f"sem_size_{size_match.group(1)}")
        if tag in {"p", "div", "span"}:
            alignment = styles.get("text-align", "")
            if alignment in {"left", "center", "right"}:
                self.alignment = f"align_{alignment}"

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                _tag, self.formats, self.alignment, self.link_tag = self.stack[index]
                del self.stack[index:]
                break
        if tag in {"p", "div"} and self.editor.text.index("insert") != "1.0":
            if self.editor.text.get("insert-1c", "insert") != "\n":
                self.editor.text.insert("insert", "\n")

    def handle_data(self, data):
        if data:
            self.editor.text.insert("insert", data, self._active_tags())

    def _active_tags(self):
        return tuple(sorted(self.formats) + ([self.alignment] if self.alignment else []) + ([self.link_tag] if self.link_tag else []))


class WysiwygEditor(tk.Frame):
    def __init__(self, parent, initial_html="", height=150):
        super().__init__(parent, bg="#c7d0dd", height=height)
        self.pack_propagate(False)
        self.initial_html = editor_initial_html(initial_html)
        self.links = {}
        self.embeds = {}
        self.images = []
        self.image_data = {}
        self.counter = 0
        self.html_mode = False
        self.selected_embed = None
        self.internal_clipboard_html = ""
        self.internal_clipboard_text = ""
        self.history = []
        self.history_index = -1
        self.history_after_id = None
        self.history_restoring = True
        self.pending_formats = set()
        self.pending_alignment = ""
        self.base_font_family = "맑은 고딕"
        self.text = tk.Text(
            self, wrap="word", relief="flat", borderwidth=0, highlightthickness=0,
            font=("맑은 고딕", 10), fg="#26384f", bg="#fbfcfe",
            insertbackground="#26384f", insertwidth=2, insertontime=600, insertofftime=300,
            padx=9, pady=8, undo=True, exportselection=False,
        )
        self.text.pack(fill="both", expand=True, padx=1, pady=1)
        self._configure_format_tags()
        self.text.bind("<<Paste>>", self._paste_rich_html, add="+")
        self.text.bind("<<Copy>>", self._copy_content, add="+")
        self.text.bind("<<Cut>>", self._cut_content, add="+")
        self.text.bind("<<Undo>>", self._undo, add="+")
        self.text.bind("<<Redo>>", self._redo, add="+")
        self.text.bind("<Control-KeyPress>", self._handle_control_shortcut, add="+")
        self.text.bind("<KeyPress>", self._remember_typing_index, add="+")
        self.text.bind("<ButtonPress-1>", self._focus_text_from_mouse, add="+")
        self.text.bind("<ButtonRelease-1>", self._restore_text_focus, add="+")
        self.text.bind("<Button-3>", self._show_editor_menu, add="+")
        self.insert_html(self.initial_html)
        self.history_restoring = False
        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self._schedule_history, add="+")
        self._commit_history(force=True)

    def _focus_text_from_mouse(self, _event=None):
        self._clear_embed_selection()
        # 일부 Windows/Tk 조합에서는 TextButton1이 insert 위치만 변경하고
        # 키보드 포커스를 루트 창에 남겨 캐럿이 표시되지 않는다.
        self.text.focus_force()
        self.after_idle(self.text.focus_force)
        self.after(20, self.text.focus_force)
        return None

    def _restore_text_focus(self, _event=None):
        self.text.focus_force()
        self.after_idle(self.text.focus_force)
        self.after(20, self.text.focus_force)
        return None

    def _handle_control_shortcut(self, event):
        """한글 IME 상태에서도 물리 키코드로 편집기 단축키를 처리한다."""
        key = str(getattr(event, "keysym", "")).lower()
        keycode = int(getattr(event, "keycode", 0) or 0)
        if key not in {"a", "b", "i", "u", "c", "x", "v", "z", "y"}:
            key = {
                65: "a", 66: "b", 73: "i", 85: "u", 67: "c", 88: "x",
                86: "v", 90: "z", 89: "y",
            }.get(keycode, "")

        def select_all():
            self.text.tag_add("sel", "1.0", "end-1c")
            self.text.mark_set("insert", "end-1c")
            self.text.see("insert")

        actions = {
            "a": select_all,
            "b": lambda: self.toggle_format("bold"),
            "i": lambda: self.toggle_format("italic"),
            "u": lambda: self.toggle_format("underline"),
            "c": lambda: self._copy_content(event),
            "x": lambda: self._cut_content(event),
            "v": lambda: self._paste_rich_html(event),
            "z": lambda: self._undo(event),
            "y": lambda: self._redo(event),
        }
        action = actions.get(key)
        if action is None:
            return None
        action()
        return "break"

    def _configure_format_tags(self):
        for name in ("sem_bold", "sem_italic", "sem_underline"):
            self.text.tag_configure(name)
        for alignment in ("left", "center", "right"):
            self.text.tag_configure(f"align_{alignment}", justify=alignment)
        for size in FONT_SIZE_OPTIONS:
            self._ensure_size_tag(size)

    def _ensure_size_tag(self, size):
        size = int(size)
        self.text.tag_configure(f"sem_size_{size}")
        for bold in (False, True):
            for italic in (False, True):
                for underline in (False, True):
                    name = self._display_tag_name(bold, italic, underline, size)
                    if hasattr(self, f"_{name}_font"):
                        continue
                    font = tkfont.Font(
                        family=self.base_font_family,
                        size=max(6, round(size * 0.75)),
                        weight="bold" if bold else "normal",
                        slant="italic" if italic else "roman",
                        underline=underline,
                    )
                    self.text.tag_configure(name, font=font)
                    setattr(self, f"_{name}_font", font)

    @staticmethod
    def _display_tag_name(bold, italic, underline, size):
        return f"display_{int(bold)}{int(italic)}{int(underline)}_{size}"

    def _remember_typing_index(self, event):
        if self.html_mode or not self.pending_formats or event.state & 0x4 or event.keysym in {
            "Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "BackSpace", "Delete",
        }:
            return None
        start = str(self.text.index("insert"))
        self.after_idle(lambda: self._apply_pending_to_new_text(start))
        return None

    def _apply_pending_to_new_text(self, start):
        if self.html_mode:
            return
        end = str(self.text.index("insert"))
        if self.text.compare(end, ">", start):
            for tag in self.pending_formats:
                self.text.tag_add(tag, start, end)
            if self.pending_alignment:
                line_start = str(self.text.index(f"{start} linestart"))
                line_end = str(self.text.index(f"{end} lineend+1c"))
                self.text.tag_add(self.pending_alignment, line_start, line_end)
            self._refresh_display_tags(start, end)

    def _refresh_display_tags(self, start="1.0", end="end-1c"):
        for tag in self.text.tag_names():
            if tag.startswith("display_"):
                self.text.tag_remove(tag, start, end)
        index = str(self.text.index(start))
        end_index = str(self.text.index(end))
        while self.text.compare(index, "<", end_index):
            tags = set(self.text.tag_names(index))
            size_tag = next((name for name in tags if name.startswith("sem_size_")), "sem_size_14")
            size = int(size_tag.rsplit("_", 1)[1])
            self._ensure_size_tag(size)
            display = self._display_tag_name(
                "sem_bold" in tags, "sem_italic" in tags, "sem_underline" in tags, size
            )
            next_index = str(self.text.index(f"{index}+1c"))
            self.text.tag_add(display, index, next_index)
            index = next_index

    def toggle_format(self, kind):
        if self.html_mode:
            return "break"
        tag = f"sem_{kind}"
        selection = self._selection_range()
        if selection:
            start, end = selection
            fully_applied = self._range_fully_tagged(tag, start, end)
            if fully_applied:
                self.text.tag_remove(tag, start, end)
            else:
                self.text.tag_add(tag, start, end)
            self._refresh_display_tags(start, end)
            self._commit_history(force=True)
        elif tag in self.pending_formats:
            self.pending_formats.remove(tag)
        else:
            self.pending_formats.add(tag)
        self.focus_editor()
        return "break"

    def _range_fully_tagged(self, tag, start, end):
        index = str(self.text.index(start))
        end_index = str(self.text.index(end))
        if not self.text.compare(index, "<", end_index):
            return False
        while self.text.compare(index, "<", end_index):
            if tag not in self.text.tag_names(index):
                return False
            index = str(self.text.index(f"{index}+1c"))
        return True

    def get_format_state(self):
        """현재 선택 영역에서 공통으로 적용된 툴바 서식을 반환한다."""
        selection = self._selection_range()
        if selection:
            start, end = selection
            positions = []
            index = str(self.text.index(start))
            end_index = str(self.text.index(end))
            while self.text.compare(index, "<", end_index):
                if self.text.get(index, f"{index}+1c") != "\n":
                    positions.append(index)
                index = str(self.text.index(f"{index}+1c"))
        else:
            index = str(self.text.index("insert"))
            if self.text.compare(index, ">", "1.0"):
                index = str(self.text.index(f"{index}-1c"))
            positions = [index]

        def common_tag(tag):
            return bool(positions) and all(tag in self.text.tag_names(position) for position in positions)

        formats = {
            kind: common_tag(f"sem_{kind}")
            for kind in ("bold", "italic", "underline")
        }
        if not selection:
            for kind in formats:
                formats[kind] = formats[kind] or f"sem_{kind}" in self.pending_formats

        sizes = set()
        for position in positions:
            size_tag = next(
                (tag for tag in self.text.tag_names(position) if tag.startswith("sem_size_")),
                "sem_size_14",
            )
            sizes.add(int(size_tag.rsplit("_", 1)[1]))
        if not selection:
            pending_size = next(
                (tag for tag in self.pending_formats if tag.startswith("sem_size_")), None
            )
            if pending_size:
                sizes = {int(pending_size.rsplit("_", 1)[1])}

        alignments = set()
        for position in positions:
            alignment_tag = next(
                (
                    tag
                    for tag in self.text.tag_names(position)
                    if tag in {"align_left", "align_center", "align_right"}
                ),
                "align_left",
            )
            alignments.add(alignment_tag.removeprefix("align_"))
        if not selection and self.pending_alignment.startswith("align_"):
            alignments = {self.pending_alignment.removeprefix("align_")}
        return {
            **formats,
            "size": next(iter(sizes)) if len(sizes) == 1 else None,
            "alignment": next(iter(alignments)) if len(alignments) == 1 else None,
        }

    def set_font_size(self, size):
        if self.html_mode:
            return
        size = int(size)
        if not 8 <= size <= 48:
            raise ValueError("글자 크기는 8~48 사이의 정수로 입력해 주세요.")
        self._ensure_size_tag(size)
        tag = f"sem_size_{size}"
        selection = self._selection_range()
        if selection:
            start, end = selection
            for existing in self.text.tag_names():
                if existing.startswith("sem_size_"):
                    self.text.tag_remove(existing, start, end)
            self.text.tag_add(tag, start, end)
            self._refresh_display_tags(start, end)
            self._commit_history(force=True)
        else:
            self.pending_formats = {name for name in self.pending_formats if not name.startswith("sem_size_")}
            self.pending_formats.add(tag)
        self.focus_editor()

    def set_alignment(self, alignment):
        if self.html_mode or alignment not in {"left", "center", "right"}:
            return
        selection = self._selection_range()
        start, end = selection if selection else ("insert", "insert")
        start = str(self.text.index(f"{start} linestart"))
        end = str(self.text.index(f"{end} lineend+1c"))
        for existing in ("align_left", "align_center", "align_right"):
            self.text.tag_remove(existing, start, end)
        self.text.tag_add(f"align_{alignment}", start, end)
        self.pending_alignment = f"align_{alignment}"
        self._commit_history(force=True)
        self.focus_editor()

    def _paste_rich_html(self, _event=None):
        clipboard_text = self._clipboard_text()
        if self.internal_clipboard_html and clipboard_text == self.internal_clipboard_text:
            self.insert_html(self.internal_clipboard_html)
            self._commit_history(force=True)
            return "break"
        source = get_windows_clipboard_html()
        if source:
            markup = sanitize_clipboard_html(source)
            if "<a " in markup or "<img " in markup:
                self.insert_html(markup)
                self._commit_history(force=True)
                return "break"
        if re.fullmatch(r"https?://\S+", clipboard_text, re.IGNORECASE):
            self.insert_html(build_content_syntax("link", text=clipboard_text, url=clipboard_text))
            self._commit_history(force=True)
            return "break"
        return None

    def _clipboard_text(self):
        try:
            return self.clipboard_get()
        except tk.TclError:
            return ""

    def _set_internal_clipboard(self, markup, plain_text):
        self.internal_clipboard_html = markup
        self.internal_clipboard_text = plain_text
        self.clipboard_clear()
        self.clipboard_append(plain_text)
        self.update_idletasks()

    def _selection_range(self):
        try:
            return str(self.text.index("sel.first")), str(self.text.index("sel.last"))
        except tk.TclError:
            return None

    def _copy_content(self, _event=None):
        if self.selected_embed is not None and self.selected_embed.winfo_exists():
            key = str(self.selected_embed)
            markup = self.embeds.get(key, "")
            if markup:
                self._set_internal_clipboard(markup, markup)
                return "break"
        selection = self._selection_range()
        if selection:
            start, end = selection
            markup = self.get_html(start, end)
            plain = self.text.get(start, end)
            if "<a " in markup or "<img " in markup or "<hr" in markup:
                self._set_internal_clipboard(markup, plain or markup)
                return "break"
            self.internal_clipboard_html = ""
            self.internal_clipboard_text = ""
            self.clipboard_clear()
            self.clipboard_append(plain)
            self.update_idletasks()
            return "break"
        return None

    def _cut_content(self, _event=None):
        if self.selected_embed is not None and self.selected_embed.winfo_exists():
            widget = self.selected_embed
            key = str(widget)
            markup = self.embeds.get(key, "")
            if not markup:
                return "break"
            self._set_internal_clipboard(markup, markup)
            try:
                index = self.text.index(widget)
                self.text.delete(index)
            except tk.TclError:
                pass
            self.embeds.pop(key, None)
            self.image_data.pop(key, None)
            self.selected_embed = None
            if widget.winfo_exists():
                widget.destroy()
            self._commit_history(force=True)
            return "break"
        selection = self._selection_range()
        if selection:
            copied = self._copy_content()
            if copied == "break":
                self.text.delete(*selection)
                self._commit_history(force=True)
                return "break"
        return None

    def _paste_from_menu(self):
        if self._paste_rich_html() == "break":
            return
        value = self._clipboard_text()
        if value:
            self.text.insert("insert", value)
            self._commit_history(force=True)

    def _show_editor_menu(self, event):
        if not self._selection_range():
            self.text.mark_set("insert", self.text.index(f"@{event.x},{event.y}"))
        self._clear_embed_selection()
        menu = tk.Menu(
            self, tearoff=False, bg="#ffffff", fg="#26384d",
            activebackground="#2e486b", activeforeground="#ffffff",
            disabledforeground="#aeb9c7", relief="flat", borderwidth=1,
            font=("맑은 고딕", 9),
        )
        menu.add_command(label="실행 취소", command=self._undo, state="normal" if self.history_index > 0 else "disabled")
        menu.add_command(label="다시 실행", command=self._redo, state="normal" if self.history_index + 1 < len(self.history) else "disabled")
        menu.add_separator()
        selection_state = "normal" if self._selection_range() else "disabled"
        menu.add_command(label="잘라내기", command=self._cut_content, state=selection_state)
        menu.add_command(label="복사", command=self._copy_content, state=selection_state)
        menu.add_command(label="붙여넣기", command=self._paste_from_menu, state="normal" if self._clipboard_text() or get_windows_clipboard_html() else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _schedule_history(self, _event=None):
        self.text.edit_modified(False)
        if self.history_restoring:
            return
        if self.history_after_id is not None:
            self.after_cancel(self.history_after_id)
        self.history_after_id = self.after(450, self._commit_history)

    def _snapshot(self):
        return self.get_html(), str(self.text.index("insert")), self.html_mode

    def _commit_history(self, force=False):
        self.history_after_id = None
        if self.history_restoring:
            return
        snapshot = self._snapshot()
        if not force and self.history and self.history[self.history_index] == snapshot:
            return
        if self.history and self.history[self.history_index][0] == snapshot[0] and self.history[self.history_index][2] == snapshot[2]:
            self.history[self.history_index] = snapshot
            return
        del self.history[self.history_index + 1:]
        self.history.append(snapshot)
        self.history_index = len(self.history) - 1
        if len(self.history) > 100:
            self.history.pop(0)
            self.history_index -= 1

    def _restore_snapshot(self, snapshot):
        source, cursor, html_mode = snapshot
        self.history_restoring = True
        self._clear_embed_selection()
        self.text.delete("1.0", "end")
        self.links.clear(); self.embeds.clear(); self.images.clear(); self.image_data.clear()
        self.html_mode = bool(html_mode)
        if self.html_mode:
            self.text.insert("1.0", source)
        else:
            self.insert_html(source)
        try:
            self.text.mark_set("insert", cursor)
        except tk.TclError:
            self.text.mark_set("insert", "end-1c")
        self.text.edit_reset()
        self.text.edit_modified(False)
        self.history_restoring = False
        self.focus_editor()

    def _undo(self, _event=None):
        if self.history_after_id is not None:
            self.after_cancel(self.history_after_id)
            self.history_after_id = None
            self._commit_history()
        if self.history_index > 0:
            self.history_index -= 1
            self._restore_snapshot(self.history[self.history_index])
        return "break"

    def _redo(self, _event=None):
        if self.history_index + 1 < len(self.history):
            self.history_index += 1
            self._restore_snapshot(self.history[self.history_index])
        return "break"

    def _attributes(self, source):
        return {key.lower(): html.unescape(value) for key, _, value in re.findall(r"([\w-]+)\s*=\s*(['\"])(.*?)\2", source)}

    def _insert_link(self, label, url):
        tag = self._create_link_tag(url)
        self.text.insert("insert", html.unescape(re.sub(r"<[^>]+>", "", label)), (tag,))

    def _create_link_tag(self, url):
        self.counter += 1
        tag = f"wysiwyg_link_{self.counter}"
        self.links[tag] = url
        self.text.tag_configure(tag, foreground="#2878db", underline=True)
        self.text.tag_bind(tag, "<Button-3>", lambda event, link_tag=tag: self._show_link_menu(link_tag, event))
        return tag

    def _show_link_menu(self, tag, event):
        menu = tk.Menu(
            self, tearoff=False, bg="#ffffff", fg="#26384d",
            activebackground="#2e486b", activeforeground="#ffffff",
            relief="flat", borderwidth=1, font=("맑은 고딕", 9),
        )
        menu.add_command(label="링크 수정", command=lambda: self._open_link_edit(tag))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _open_link_edit(self, tag):
        ranges = self.text.tag_ranges(tag)
        if len(ranges) < 2 or tag not in self.links:
            return
        start_index, end_index = str(ranges[0]), str(ranges[1])
        dialog = tk.Toplevel(self.winfo_toplevel())
        dialog.withdraw()
        dialog.title("링크 수정")
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        dialog.configure(bg="#ffffff")
        body = ttk.Frame(dialog, padding=18, style="Card.TFrame")
        body.pack(fill="both", expand=True)
        text_var = tk.StringVar(value=self.text.get(start_index, end_index))
        url_var = tk.StringVar(value=self.links[tag])
        first_entry = None
        for row, (title, variable) in enumerate((("표시 텍스트", text_var), ("링크", url_var))):
            ttk.Label(body, text=title, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            entry = ttk.Entry(body, textvariable=variable, width=48)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            if first_entry is None:
                first_entry = entry
        body.columnconfigure(1, weight=1)

        def apply_link():
            try:
                cleaned_url = normalize_url_prefix(url_var.get())
                build_content_syntax("link", text=text_var.get(), url=cleaned_url)
            except ValueError as exc:
                centered_messagebox(dialog, "showerror", "링크 수정", str(exc))
                return
            new_text = text_var.get().strip()
            self.links[tag] = cleaned_url
            self.text.delete(start_index, end_index)
            self.text.insert(start_index, new_text, (tag,))
            self._commit_history(force=True)
            dialog.destroy()

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="취소", command=dialog.destroy, style="Soft.TButton").pack(side="left")
        ttk.Button(buttons, text="확인", command=apply_link, style="Navy.TButton").pack(side="left", padx=(8, 0))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.bind("<Return>", lambda _event: apply_link())
        dialog.update_idletasks()
        center_toplevel(dialog, self.winfo_toplevel(), 540, 190)
        dialog.deiconify()
        dialog.grab_set()
        first_entry.focus_set()
        first_entry.selection_range(0, "end")

    def _insert_rule(self):
        rule = tk.Frame(self.text, bg="#aeb9c7", height=1, width=620)
        self.text.window_create("insert", window=rule, pady=8)
        self.embeds[str(rule)] = "<hr>"

    def _insert_image(self, source):
        attrs = self._attributes(source)
        src = attrs.get("src", "")
        alt = attrs.get("alt", "이미지")
        width = int(attrs["width"]) if attrs.get("width", "").isdigit() else None
        height = int(attrs["height"]) if attrs.get("height", "").isdigit() else None
        label = tk.Label(self.text, text=f"이미지: {alt}\n{src}", bg="#edf2f8", fg="#53657a", padx=10, pady=8)
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
            if "dcinside.com" in src:
                headers["Referer"] = "https://gall.dcinside.com/"
            response = requests.get(src, timeout=8, headers=headers)
            response.raise_for_status()
            max_width = width or 560
            max_height = height or 140
            preview = decode_preview_image(response.content, max_width, max_height)
            photo = ImageTk.PhotoImage(preview, master=self.text)
            self.images.append(photo)
            label.configure(image=photo, text="")
        except Exception:
            pass
        self.text.window_create("insert", window=label, pady=6)
        escaped_src = html.escape(src, quote=True)
        escaped_alt = html.escape(alt, quote=True)
        size = (f' width="{width}"' if width else "") + (f' height="{height}"' if height else "")
        self.embeds[str(label)] = f'<img src="{escaped_src}" alt="{escaped_alt}"{size}>'
        self.image_data[str(label)] = {"src": src, "alt": alt, "width": width, "height": height}
        label.bind("<Button-1>", lambda event, widget=label: self._select_embed(widget, event))
        label.bind("<Button-3>", lambda event, widget=label: self._show_image_menu(widget, event))
        label.bind("<Control-KeyPress>", self._handle_control_shortcut)

    def _clear_embed_selection(self):
        widget = self.selected_embed
        if widget is not None and widget.winfo_exists():
            widget.configure(highlightthickness=0)
        self.selected_embed = None

    def _select_embed(self, label, _event=None):
        self._clear_embed_selection()
        self.selected_embed = label
        label.configure(highlightbackground="#3478f6", highlightcolor="#3478f6", highlightthickness=2)
        try:
            self.text.mark_set("insert", f"{self.text.index(label)}+1c")
        except tk.TclError:
            pass
        self.text.focus_set()
        return "break"

    def _show_image_menu(self, label, event):
        self._select_embed(label)
        menu = tk.Menu(self, tearoff=False, bg="#ffffff", fg="#26384d", activebackground="#2e486b", activeforeground="#ffffff", relief="flat", borderwidth=1, font=("맑은 고딕", 9))
        menu.add_command(label="이미지 수정", command=lambda: self._open_image_resize(label))
        menu.add_separator()
        menu.add_command(label="복사", command=self._copy_content)
        menu.add_command(label="잘라내기", command=self._cut_content)
        menu.add_command(label="붙여넣기", command=self._paste_from_menu, state="normal" if self._clipboard_text() or get_windows_clipboard_html() else "disabled")
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()

    def _open_image_resize(self, label):
        data = self.image_data.get(str(label))
        if not data: return
        dialog = tk.Toplevel(self.winfo_toplevel()); dialog.withdraw(); dialog.title("이미지 수정"); dialog.transient(self.winfo_toplevel()); dialog.resizable(False, False); dialog.configure(bg="#ffffff")
        body = ttk.Frame(dialog, padding=18, style="Card.TFrame"); body.pack(fill="both", expand=True)
        alt_var = tk.StringVar(value=data.get("alt", "")); url_var = tk.StringVar(value=data.get("src", ""))
        width_var = tk.StringVar(value=str(data.get("width") or ""))
        height_var = tk.StringVar(value=str(data.get("height") or ""))
        keep_ratio_var = tk.BooleanVar(value=False)
        for row, (title, variable) in enumerate((("설명 텍스트", alt_var), ("이미지 URL", url_var))):
            ttk.Label(body, text=title, style="Card.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=6); ttk.Entry(body, textvariable=variable, width=48).grid(row=row, column=1, columnspan=3, sticky="ew", pady=6)
        ratio_check = tk.Checkbutton(
            body, text="원본 비율 맞춤", variable=keep_ratio_var,
            bg="#ffffff", fg="#26384d", activebackground="#ffffff", activeforeground="#26384d",
            selectcolor="#ffffff", highlightthickness=0, borderwidth=0, relief="flat",
            font=("맑은 고딕", 9),
        )
        ratio_check.grid(row=2, column=0, sticky="w", padx=(0, 10), pady=6)
        size_fields = ttk.Frame(body, style="Card.TFrame")
        size_fields.grid(row=2, column=1, columnspan=3, sticky="ew", pady=6)
        for column, (title, variable) in enumerate((("가로", width_var), ("세로", height_var))):
            field = ttk.Frame(size_fields, style="Card.TFrame")
            field.grid(row=0, column=column, sticky="ew", padx=((0, 9) if column == 0 else (9, 0)))
            field.columnconfigure(1, weight=1)
            ttk.Label(field, text=title, style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
            ttk.Entry(field, textvariable=variable, width=16).grid(row=0, column=1, sticky="ew")
            size_fields.columnconfigure(column, weight=1, uniform="image_size")
        preview_frame = tk.Frame(body, bg="#edf2f8", width=520, height=270, relief="flat")
        preview_frame.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(10, 4)); preview_frame.grid_propagate(False)
        preview_box = tk.Canvas(preview_frame, width=520, height=270, bg="#edf2f8", highlightthickness=0)
        preview_box.pack(fill="both", expand=True)
        preview_box.create_text(260, 135, text="이미지를 불러오는 중...", fill="#53657a")
        preview_status = ttk.Label(body, text="", style="Hint.TLabel", anchor="center")
        preview_status.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        preview_refs = []
        preview_cache = {"url": None, "image": None}
        preview_after_id = [None]
        ratio_update_guard = [False]
        def load_preview(show_error=True):
            try:
                url = normalize_url_prefix(url_var.get())
                if preview_cache["url"] != url or preview_cache["image"] is None:
                    headers = {"User-Agent": "Mozilla/5.0"}
                    if "dcinside.com" in url: headers["Referer"] = "https://gall.dcinside.com/"
                    response = requests.get(url, timeout=8, headers=headers); response.raise_for_status()
                    with Image.open(io.BytesIO(response.content)) as source:
                        source.seek(0); original = source.convert("RGBA")
                    preview_cache.update(url=url, image=original)
                else:
                    original = preview_cache["image"]
                width_text, height_text = width_var.get().strip(), height_var.get().strip()
                width = int(width_text) if width_text else None
                height = int(height_text) if height_text else None
                if any(value is not None and not 1 <= value <= 4096 for value in (width, height)):
                    raise ValueError("크기는 1~4096 사이여야 합니다.")
                if width is None and height is None:
                    target_width, target_height = original.size
                else:
                    target_width = width if width is not None else round(original.width * height / original.height)
                    target_height = height if height is not None else round(original.height * width / original.width)
                preview = original.resize((target_width, target_height), Image.Resampling.LANCZOS)
                scale = min(1.0, 500 / target_width, 250 / target_height)
                shown_width = max(1, round(target_width * scale)); shown_height = max(1, round(target_height * scale))
                if (shown_width, shown_height) != preview.size:
                    preview = preview.resize((shown_width, shown_height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(preview, master=self.text)
                preview_refs[:] = [photo]
                preview_box.delete("all")
                preview_box.create_rectangle(0, 0, 520, 270, fill="#edf2f8", outline="")
                preview_box.create_image(260, 135, image=photo, anchor="center")
                preview_box.create_rectangle(260 - shown_width / 2, 135 - shown_height / 2, 260 + shown_width / 2, 135 + shown_height / 2, outline="#c4cedb")
                preview_status.configure(text=f"원본 {original.width}×{original.height}  ·  적용 {target_width}×{target_height}  ·  미리보기 {round(scale * 100)}%")
                if url_var.get() != url:
                    url_var.set(url)
                return photo, width, height
            except Exception as exc:
                if show_error: centered_messagebox(dialog, "showerror", "이미지 수정", f"이미지 미리보기를 불러오지 못했습니다.\n{exc}")
                return None
        def run_scheduled_preview():
            preview_after_id[0] = None
            load_preview(False)
        def schedule_preview(*_args):
            if preview_after_id[0] is not None:
                dialog.after_cancel(preview_after_id[0])
            preview_after_id[0] = dialog.after(450, run_scheduled_preview)
        def sync_ratio(changed_axis):
            if ratio_update_guard[0] or not keep_ratio_var.get():
                return
            if preview_cache["image"] is None or preview_cache["url"] != normalize_url_prefix(url_var.get()):
                if not load_preview(False):
                    return
            original = preview_cache["image"]
            try:
                source_var = width_var if changed_axis == "width" else height_var
                value_text = source_var.get().strip()
                if not value_text:
                    return
                value = int(value_text)
                if not 1 <= value <= 4096:
                    return
                ratio_update_guard[0] = True
                if changed_axis == "width":
                    height_var.set(str(matching_image_dimension(value, original.width, original.height)))
                else:
                    width_var.set(str(matching_image_dimension(value, original.height, original.width)))
            finally:
                ratio_update_guard[0] = False
        def enable_ratio():
            if not keep_ratio_var.get():
                return
            sync_ratio("width" if width_var.get().strip() else "height")
        def apply_size():
            result = load_preview()
            if not result: return
            photo, width, height = result; data.update(src=url_var.get(), alt=alt_var.get().strip(), width=width, height=height)
            escaped_src, escaped_alt = html.escape(data["src"], quote=True), html.escape(data["alt"], quote=True)
            size = (f' width="{width}"' if width else "") + (f' height="{height}"' if height else "")
            self.embeds[str(label)] = f'<img src="{escaped_src}" alt="{escaped_alt}"{size}>'
            self.images.append(photo); label.configure(image=photo, text="")
            self._commit_history(force=True)
            dialog.destroy()
        url_var.trace_add("write", schedule_preview)
        width_var.trace_add("write", lambda *_args: (sync_ratio("width"), schedule_preview()))
        height_var.trace_add("write", lambda *_args: (sync_ratio("height"), schedule_preview()))
        ratio_check.configure(command=enable_ratio)
        buttons = ttk.Frame(body, style="Card.TFrame"); buttons.grid(row=5, column=0, columnspan=4, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="취소", command=dialog.destroy, style="Soft.TButton").pack(side="left", padx=8); ttk.Button(buttons, text="확인", command=apply_size, style="Navy.TButton").pack(side="left")
        dialog.update_idletasks(); center_toplevel(dialog, self.winfo_toplevel(), 600, 560); dialog.deiconify(); dialog.grab_set(); dialog.after(50, lambda: load_preview(False))

    def get_html(self, start="1.0", end="end-1c"):
        if self.html_mode:
            return self.text.get(start, end)
        lines = [[]]
        for event, value, index in self.text.dump(start, end, text=True, window=True):
            if event == "window":
                lines[-1].append((self.embeds.get(value, ""), set(self.text.tag_names(index)), True))
            elif event == "text":
                offset = 0
                for part in re.split("(\n)", value):
                    if not part:
                        continue
                    if part == "\n":
                        lines.append([])
                        offset += 1
                        continue
                    part_index = str(self.text.index(f"{index}+{offset}c"))
                    lines[-1].append((part, set(self.text.tag_names(part_index)), False))
                    offset += len(part)

        rendered_lines = []
        for line in lines:
            pieces = []
            alignment = "left"
            for value, tags, is_markup in line:
                alignment_tag = next((name for name in tags if name.startswith("align_")), "")
                if alignment_tag:
                    alignment = alignment_tag.split("_", 1)[1]
                if is_markup:
                    pieces.append(value)
                    continue
                content = html.escape(value)
                link_tag = next((name for name in tags if name in self.links), "")
                size_tag = next((name for name in tags if name.startswith("sem_size_")), "")
                if "sem_underline" in tags:
                    content = f"<u>{content}</u>"
                if "sem_italic" in tags:
                    content = f"<em>{content}</em>"
                if "sem_bold" in tags:
                    content = f"<strong>{content}</strong>"
                if size_tag:
                    size = size_tag.rsplit("_", 1)[1]
                    content = f'<span style="font-size:{size}px">{content}</span>'
                if link_tag:
                    href = html.escape(self.links[link_tag], quote=True)
                    content = f'<a href="{href}" target="_blank">{content}</a>'
                pieces.append(content)
            line_html = "".join(pieces)
            if alignment != "left":
                line_html = f'<div style="text-align:{alignment}">{line_html}</div>'
            rendered_lines.append(line_html)
        return "<br>".join(rendered_lines)

    def insert_html(self, value):
        if self.html_mode:
            self.text.insert("insert", value)
            return
        loader = _EditorHtmlLoader(self)
        loader.feed(value or "")
        loader.close()
        if self.text.index("insert") != "1.0" and self.text.get("insert-1c", "insert") == "\n":
            self.text.delete("insert-1c", "insert")
        self._refresh_display_tags()

    def focus_editor(self):
        self.text.focus_set()

    def set_html_mode(self, enabled):
        enabled = bool(enabled)
        if enabled == self.html_mode:
            return
        if enabled:
            source = self.get_html()
            self.text.delete("1.0", "end")
            self.text.insert("1.0", source)
            self.html_mode = True
        else:
            source = self.text.get("1.0", "end-1c")
            self.text.delete("1.0", "end")
            self.links.clear()
            self.embeds.clear()
            self.images.clear()
            self.image_data.clear()
            self.html_mode = False
            self.insert_html(source)
        self._commit_history(force=True)
        self.focus_editor()


def collect_files(folder, mode="name"):
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise ValueError("올바른 이미지 폴더를 선택해 주세요.")
    images = [path for path in folder_path.iterdir() if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS]
    if not images:
        raise ValueError("선택한 폴더에 지원하는 이미지가 없습니다.")
    if len(images) > 50:
        raise ValueError(f"이미지는 최대 50개까지 가능합니다. 현재 {len(images)}개입니다.")

    if mode == "name":
        return sorted(images, key=natural_key), []
    if mode == "name_desc":
        return sorted(images, key=natural_key, reverse=True), []
    if mode in {"mtime", "mtime_desc"}:
        return sorted(images, key=lambda path: (path.stat().st_mtime_ns, natural_key(path)), reverse=mode == "mtime_desc"), []

    found = {}
    ignored = []
    for path in images:
        match = re.fullmatch(r"(\d+)", path.stem.strip())
        if not match:
            ignored.append(path.name)
            continue
        number = int(match.group(1))
        if not 1 <= number <= 50:
            ignored.append(path.name)
            continue
        if number in found:
            raise ValueError(f"{number}번 파일이 둘 이상입니다: {found[number].name}, {path.name}")
        found[number] = path.resolve()
    if not found:
        raise ValueError("1.png, 2.gif 같은 번호 이름의 이미지가 없습니다.")
    if 1 not in found:
        raise ValueError("메인 이미지로 사용할 1번 파일이 필요합니다.")
    highest = max(found)
    missing = [str(n) for n in range(1, highest + 1) if n not in found]
    if missing:
        raise ValueError("중간 번호가 비어 있습니다: " + ", ".join(missing))
    return [found[number] for number in sorted(found)], ignored


def find_browser():
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for command in ("chrome.exe", "msedge.exe"):
        located = shutil.which(command)
        if located:
            return Path(located)
    raise FileNotFoundError("Chrome 또는 Edge를 찾지 못했습니다.")


class CdpClient:
    def __init__(self, websocket_url):
        self.ws = websocket.create_connection(websocket_url, timeout=10, origin="http://localhost:9222")
        self.next_id = 0

    def close(self):
        self.ws.close()

    def call(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(self.ws.recv())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(response["error"].get("message", str(response["error"])))
            return response.get("result", {})


class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.window = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event=None):
        if self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() - 8
        self.window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.window,
            text=self.text,
            justify="left",
            bg="#243b5a",
            fg="white",
            relief="solid",
            borderwidth=1,
            font=("맑은 고딕", 9),
            padx=12,
            pady=10,
        )
        label.pack()

    def hide(self, _event=None):
        if self.window:
            self.window.destroy()
            self.window = None


class TagBadgeInput(tk.Frame):
    def __init__(self, parent, variable):
        super().__init__(parent, bg="#ffffff", highlightbackground="#aab4c0", highlightcolor="#3478f6", highlightthickness=1)
        self.variable = variable
        self.tags = []
        self._pointer_reset_count = 0
        self._handling_input_change = False
        self.badge_frame = tk.Frame(self, bg="#ffffff")
        badge_min_height = tkfont.Font(root=self, family="맑은 고딕", size=9, weight="bold").metrics("linespace") + 10
        self.height_spacer = tk.Frame(self, bg="#ffffff", width=1, height=badge_min_height)
        self.height_spacer.pack(side="left", pady=4)
        self.height_spacer.pack_propagate(False)
        self.input_var = tk.StringVar()
        self.entry = tk.Entry(
            self, textvariable=self.input_var, relief="flat", borderwidth=0, highlightthickness=0,
            bg="#ffffff", fg="#26384d", insertbackground="#26384d", font=("맑은 고딕", 10),
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=6, pady=5)
        self.entry.bind("<Return>", self.commit_event)
        self.entry.bind("<BackSpace>", self.remove_last_if_empty)
        self.entry.bind("<KeyRelease>", self.sync_variable)
        self.input_var.trace_add("write", self.handle_input_change)
        self.bind("<Button-1>", lambda _event: self.restore_cursor(), add="+")
        self.badge_frame.bind("<Button-1>", lambda _event: self.restore_cursor(), add="+")
        for tag in parse_tags(variable.get()):
            self.add_badge(tag, sync=False)
        self.sync_variable()

    def add_badge(self, tag, sync=True):
        tag = tag.strip()
        if not tag:
            return
        if tag in self.tags:
            self.input_var.set("")
            self.sync_variable()
            return
        first_badge = not self.tags
        self.tags.append(tag)
        if first_badge:
            self.badge_frame.pack(side="left", before=self.entry, padx=(6, 0), pady=4)
        badge = tk.Frame(self.badge_frame, bg="#707070", relief="flat", cursor="hand2")
        badge.pack(side="left", padx=(0, 5))
        tag_label = tk.Label(
            badge, text=tag, bg="#707070", fg="#ffffff",
            font=("맑은 고딕", 9, "bold"), padx=0, pady=3, cursor="hand2",
        )
        tag_label.pack(side="left", padx=(7, 2))
        close_label = tk.Label(
            badge, text="X", bg="#707070", fg="#ffffff",
            font=("맑은 고딕", 9, "bold"), padx=0, pady=3, cursor="hand2",
        )
        close_label.pack(side="right", padx=(0, 7))
        for target in (badge, tag_label, close_label):
            target.bind("<ButtonRelease-1>", lambda _event, value=tag, widget=badge: self.remove_badge(value, widget))
        if sync:
            self.sync_variable()

    def remove_badge(self, tag, widget):
        if tag in self.tags:
            self.tags.remove(tag)
        widget.configure(cursor="arrow")
        widget.destroy()
        if not self.tags:
            self.badge_frame.pack_forget()
        self.sync_variable()
        self.restore_mouse_cursor()
        self.restore_cursor()

    def commit_event(self, _event=None):
        self.add_badge(self.input_var.get())
        self.input_var.set("")
        self.sync_variable()
        self.restore_cursor()
        return "break"

    def handle_input_change(self, *_args):
        if self._handling_input_change:
            return
        value = self.input_var.get()
        if "," not in value:
            self.sync_variable()
            return
        parts = value.split(",")
        self._handling_input_change = True
        try:
            for tag in parts[:-1]:
                self.add_badge(tag)
            self.input_var.set(parts[-1])
            self.sync_variable()
            self.restore_cursor()
        finally:
            self._handling_input_change = False

    def remove_last_if_empty(self, _event=None):
        if self.input_var.get() or not self.tags:
            return None
        children = self.badge_frame.winfo_children()
        if children:
            children[-1].destroy()
        self.tags.pop()
        if not self.tags:
            self.badge_frame.pack_forget()
        self.sync_variable()
        self.restore_cursor()
        return "break"

    def sync_variable(self, _event=None):
        values = list(self.tags)
        pending = self.input_var.get().strip()
        if pending:
            values.append(pending)
        self.variable.set(",".join(values))

    def focus_set(self):
        self.restore_cursor()

    def restore_cursor(self):
        def apply_focus():
            if self.entry.winfo_exists():
                self.entry.focus_set()
                self.entry.icursor("end")
                self.entry.xview_moveto(1.0)
        self.after_idle(apply_focus)

    def restore_mouse_cursor(self):
        self._pointer_reset_count += 1
        top = self.winfo_toplevel()
        top.configure(cursor="arrow")

        def release_override():
            if not top.winfo_exists():
                return
            top.configure(cursor="")
            target = top.winfo_containing(top.winfo_pointerx(), top.winfo_pointery())
            if target is not None and target.winfo_exists():
                target.event_generate("<Motion>", x=0, y=0)

        top.after(30, release_override)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{BRAND_TITLE} v{APP_VERSION} - {APP_TITLE}")
        self.root.geometry("760x680")
        self.root.minsize(680, 600)
        config_dir = app_dir()
        self.settings_path = migrate_legacy_config(config_dir, LEGACY_SETTINGS_FILENAME, SETTINGS_FILENAME)
        self.mapping_path = migrate_legacy_config(config_dir, LEGACY_MAPPING_FILENAME, MAPPING_FILENAME)
        self.profile_path = migrate_legacy_config(config_dir, LEGACY_PROFILE_DIRECTORY, PROFILE_DIRECTORY)
        self.mapping = self.load_mapping()
        self.folder = tk.StringVar()
        self.url = tk.StringVar(value=DEFAULT_URL)
        self.sort_mode = tk.StringVar(value="파일 이름")
        self.tags = tk.StringVar()
        self.post_title = tk.StringVar()
        self.price = tk.StringVar()
        self.status = tk.StringVar(value="폴더를 선택해 주세요.")
        self.saved_content = ""
        self.guide_seen = False
        self.load_settings()
        self.build_ui()

    def build_ui(self):
        navy, blue, page_bg, white, text, muted = "#2e486b", "#3478f6", "#d4d4d4", "#ffffff", "#26384d", "#687789"
        self.root.configure(bg=page_bg)
        window_width = min(900, max(680, self.root.winfo_screenwidth() - 80))
        window_height = min(940, max(560, self.root.winfo_screenheight() - 80))
        self.root.geometry(f"{window_width}x{window_height}")
        self.root.minsize(680, 520)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Page.TFrame", background=page_bg)
        style.configure("Card.TFrame", background=white)
        style.configure("Card.TLabel", background=white, foreground=text, font=("맑은 고딕", 10))
        style.configure("Section.TLabel", background=white, foreground=navy, font=("맑은 고딕", 12, "bold"))
        style.configure("Hint.TLabel", background=white, foreground=muted, font=("맑은 고딕", 9))
        style.configure("Accent.TButton", background=blue, foreground=white, borderwidth=0, padding=(18, 10), font=("맑은 고딕", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#2868da")])
        style.configure("Navy.TButton", background=navy, foreground=white, borderwidth=0, padding=(16, 10), font=("맑은 고딕", 10, "bold"))
        style.map("Navy.TButton", background=[("active", "#213a5c")])
        style.configure("Soft.TButton", background="#eef2f7", foreground=navy, borderwidth=0, padding=(12, 9))
        style.map("Soft.TButton", background=[("active", "#dfe7f1")])
        style.configure("Editor.TButton", background="#eef2f7", foreground=navy, borderwidth=0, padding=(8, 3), font=("맑은 고딕", 9))
        style.map("Editor.TButton", background=[("active", "#dfe7f1"), ("pressed", "#d4dde8")])
        style.configure("TEntry", padding=7)
        style.configure("TCombobox", padding=6)
        style.layout(
            "Log.Vertical.TScrollbar",
            [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})],
        )
        style.configure(
            "Log.Vertical.TScrollbar",
            width=8,
            troughcolor="#f7f8fa",
            background="#b6c1cf",
            bordercolor="#f7f8fa",
            lightcolor="#b6c1cf",
            darkcolor="#b6c1cf",
        )
        style.map("Log.Vertical.TScrollbar", background=[("active", navy), ("pressed", navy)])
        style.configure(
            "Order.TCombobox",
            padding=6,
            foreground=text,
            fieldbackground=white,
            background="#eef2f7",
            arrowcolor=navy,
            bordercolor="#c7d1dd",
            lightcolor="#c7d1dd",
            darkcolor="#c7d1dd",
            selectbackground=white,
            selectforeground=text,
        )
        style.map(
            "Order.TCombobox",
            fieldbackground=[("readonly", white), ("focus", white)],
            foreground=[("readonly", text), ("focus", text)],
            background=[("active", "#dfe7f1"), ("pressed", "#d4dde8"), ("readonly", "#eef2f7")],
            arrowcolor=[("active", navy), ("readonly", navy)],
            bordercolor=[("focus", blue), ("readonly", "#c7d1dd")],
        )
        # 에디터 툴바 전용 콤보박스. 기본 Combobox의 입체적인 테두리를
        # 제거하고 툴바 버튼과 동일한 평면형 배색을 사용한다.
        style.layout(
            "FontSize.TCombobox",
            [
                ("Combobox.downarrow", {"side": "right", "sticky": "ns"}),
                (
                    "Combobox.field",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Combobox.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [("Combobox.textarea", {"sticky": "nswe"})],
                                },
                            )
                        ],
                    },
                ),
            ],
        )
        style.configure(
            "FontSize.TCombobox",
            padding=(8, 5),
            foreground=navy,
            fieldbackground=white,
            background="#eef2f7",
            arrowcolor=navy,
            bordercolor="#cbd5e1",
            lightcolor="#cbd5e1",
            darkcolor="#cbd5e1",
            borderwidth=1,
            relief="flat",
            arrowsize=13,
            font=("맑은 고딕", 10),
        )
        style.map(
            "FontSize.TCombobox",
            fieldbackground=[("focus", white), ("active", white)],
            foreground=[("focus", text), ("active", text)],
            background=[("active", "#dfe7f1"), ("pressed", "#d4dde8")],
            arrowcolor=[("active", navy), ("pressed", navy)],
            bordercolor=[("focus", blue), ("active", "#aebdce")],
            lightcolor=[("focus", blue)],
            darkcolor=[("focus", blue)],
        )
        style.layout(
            "ComboPopup.Vertical.TScrollbar",
            [
                (
                    "Vertical.Scrollbar.trough",
                    {
                        "sticky": "ns",
                        "children": [
                            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})
                        ],
                    },
                )
            ],
        )
        style.configure(
            "ComboPopup.Vertical.TScrollbar",
            width=8,
            troughcolor=white,
            background="#aebdce",
            bordercolor=white,
            lightcolor="#aebdce",
            darkcolor="#aebdce",
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "ComboPopup.Vertical.TScrollbar",
            background=[("active", navy), ("pressed", navy)],
            lightcolor=[("active", navy), ("pressed", navy)],
            darkcolor=[("active", navy), ("pressed", navy)],
        )
        self.root.option_add("*TCombobox*Listbox.background", white)
        self.root.option_add("*TCombobox*Listbox.foreground", text)
        self.root.option_add("*TCombobox*Listbox.selectBackground", blue)
        self.root.option_add("*TCombobox*Listbox.selectForeground", white)
        self.root.option_add("*TCombobox*Listbox.font", ("맑은 고딕", 10))

        try:
            self.app_icon = tk.PhotoImage(file=str(resource_path("ic_profile_dd.png")))
            self.root.iconphoto(True, self.app_icon)
        except tk.TclError:
            self.app_icon = None

        header = tk.Frame(self.root, bg=navy, height=78)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_inner = tk.Frame(header, bg=navy)
        header_inner.pack(fill="both", expand=True, padx=28)
        if self.app_icon:
            self.header_icon = self.app_icon.subsample(4, 4)
            tk.Label(header_inner, image=self.header_icon, bg=navy).pack(side="left", padx=(0, 14))
        try:
            self.brand_logo = tk.PhotoImage(file=str(resource_path("dogdrip-con-uploader-logo.png")))
            tk.Label(header_inner, image=self.brand_logo, bg=navy).pack(side="left")
        except tk.TclError:
            self.brand_logo = None
            tk.Label(header_inner, text=BRAND_TITLE, bg=navy, fg=white, font=("Consolas", 19, "bold")).pack(side="left")
        header_tools = tk.Frame(header_inner, bg=navy)
        header_tools.pack(side="right")
        guide_area = tk.Frame(header_tools, bg=navy, cursor="hand2")
        guide_area.pack(side="left")
        guide_text = tk.Label(guide_area, text="Guide", bg=navy, fg="#d9e5f5", font=("맑은 고딕", -16, "bold"), cursor="hand2")
        guide_text.pack(side="left", padx=(0, 6))
        guide_icon = tk.Canvas(guide_area, width=20, height=20, bg=navy, highlightthickness=0, cursor="hand2")
        guide_icon.create_oval(1, 1, 19, 19, outline="#d9e5f5", width=1)
        guide_icon.create_text(10, 10, text="!", fill="#d9e5f5", font=("맑은 고딕", 9, "bold"))
        guide_icon.pack(side="left")
        tk.Label(header_tools, text="|", bg=navy, fg="#738aa8", font=("맑은 고딕", -16)).pack(side="left", padx=10)
        self.version_label = tk.Label(
            header_tools, text=f"v{APP_VERSION}", bg=navy, fg="#d9e5f5", font=("맑은 고딕", -16)
        )
        self.version_label.pack(side="left")
        for guide_widget in (guide_area, guide_text, guide_icon):
            guide_widget.bind("<Button-1>", lambda _event: self.show_guide())

        scroll_container = tk.Frame(self.root, bg=page_bg)
        scroll_container.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_container, bg=page_bg, highlightthickness=0, borderwidth=0)
        self.page_canvas = canvas
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        self.page_scrollbar = scrollbar
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        page = ttk.Frame(canvas, style="Page.TFrame", padding=(26, 22))
        page_window = canvas.create_window((0, 0), window=page, anchor="nw")
        self.comboboxes = []

        def update_scroll_region(_event=None):
            bounds = canvas.bbox("all")
            canvas.configure(scrollregion=bounds)
            if not bounds:
                return
            content_height = bounds[3] - bounds[1]
            viewport_height = canvas.winfo_height()
            if viewport_height > 1 and content_height <= viewport_height + 2:
                if scrollbar.winfo_ismapped():
                    scrollbar.pack_forget()
            elif not scrollbar.winfo_ismapped():
                scrollbar.pack(side="right", fill="y", before=canvas)

        def fit_page_width(event):
            canvas.itemconfigure(page_window, width=event.width)

        def scroll_page_when_overflowed(event):
            widget_class = event.widget.winfo_class() if event.widget.winfo_exists() else ""
            if isinstance(event.widget, (tk.Text, ttk.Combobox, tk.Listbox)) or widget_class in {
                "Text", "TCombobox", "Listbox", "ComboboxPopdown",
            }:
                # 내부 에디터와 펼쳐진 목록은 각각 자신의 스크롤만 처리한다.
                return "break"
            bounds = canvas.bbox("all")
            if not bounds:
                return "break"
            content_height = bounds[3] - bounds[1]
            viewport_height = canvas.winfo_height()
            if viewport_height > 1 and content_height > viewport_height + 2:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        page.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_page_width)
        self.root.bind_all("<MouseWheel>", scroll_page_when_overflowed, add="+")
        card = ttk.Frame(page, style="Card.TFrame", padding=24)
        card.pack(fill="both", expand=True)

        ttk.Label(card, text="1  업로드할 이미지 선택", style="Section.TLabel").pack(anchor="w")
        folder_row = ttk.Frame(card, style="Card.TFrame")
        folder_row.pack(fill="x", pady=(10, 8))
        ttk.Entry(folder_row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="폴더 선택", command=self.choose_folder, style="Navy.TButton").pack(side="left", padx=(10, 0))
        sort_row = ttk.Frame(card, style="Card.TFrame")
        sort_row.pack(fill="x", pady=(0, 18))
        ttk.Label(sort_row, text="배치 순서", style="Card.TLabel").pack(side="left")
        sort_box = ttk.Combobox(sort_row, textvariable=self.sort_mode, values=tuple(SORT_OPTIONS), state="readonly", width=22, style="Order.TCombobox")
        self.comboboxes.append(sort_box)
        sort_box.pack(side="left", padx=(10, 12))
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.preview())
        sort_box.bind("<MouseWheel>", lambda _event: "break", add="+")
        ttk.Label(sort_row, text="첫 번째 파일이 메인 이미지가 됩니다.", style="Hint.TLabel").pack(side="left")

        ttk.Separator(card).pack(fill="x", pady=(0, 18))
        ttk.Label(card, text="2  게시글 정보 (선택)", style="Section.TLabel").pack(anchor="w")
        ttk.Label(card, text="개드립콘 등록 페이지 주소", style="Card.TLabel").pack(anchor="w", pady=(10, 0))
        url_row = ttk.Frame(card, style="Card.TFrame")
        url_row.pack(fill="x", pady=(5, 12))
        ttk.Entry(url_row, textvariable=self.url).pack(side="left", fill="x", expand=True)
        default_page_button = ttk.Button(url_row, text="기본 페이지", command=self.reset_default_url, style="Soft.TButton")
        default_page_button.pack(side="left", padx=(10, 0))
        info_row = ttk.Frame(card, style="Card.TFrame")
        info_row.pack(fill="x", pady=(0, 12))
        title_box = ttk.Frame(info_row, style="Card.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="게시글 제목", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(title_box, textvariable=self.post_title).pack(fill="x", pady=(5, 0))
        price_box = ttk.Frame(info_row, style="Card.TFrame")
        price_box.pack(side="left", padx=(12, 0))
        ttk.Label(price_box, text="판매 포인트", style="Card.TLabel").pack(anchor="w")
        price_entry_box = ttk.Frame(
            price_box,
            style="Card.TFrame",
            width=default_page_button.winfo_reqwidth(),
            height=default_page_button.winfo_reqheight(),
        )
        price_entry_box.pack(pady=(5, 0))
        price_entry_box.pack_propagate(False)
        ttk.Entry(price_entry_box, textvariable=self.price).pack(fill="both", expand=True)
        content_label_row = ttk.Frame(card, style="Card.TFrame")
        content_label_row.pack(fill="x", pady=(0, 5))
        ttk.Label(content_label_row, text="게시글 내용", style="Card.TLabel").pack(side="left")
        self.html_view = tk.BooleanVar(value=False)
        editor_toolbar = tk.Frame(card, bg="#eef2f7", padx=5, pady=4)
        editor_toolbar.pack(fill="x")
        self.font_size = tk.StringVar(value="14 px")
        self.last_font_size = "14 px"
        # Tk에서 음수 font size는 포인트가 아닌 화면 픽셀 단위다.
        # 팝다운 항목별 폰트를 보관해 가비지 컬렉션으로 사라지지 않게 한다.
        self.font_size_preview_fonts = {
            size: tkfont.Font(root=self.root, family="맑은 고딕", size=-size)
            for size in FONT_SIZE_OPTIONS
        }

        size_box = tk.Frame(
            editor_toolbar, bg="#cbd5e1", highlightthickness=0, borderwidth=0,
        )
        self.font_size_box = size_box
        size_box.pack(side="left", padx=(0, 5))
        size_entry = tk.Entry(
            size_box,
            textvariable=self.font_size,
            width=7,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            bg="#ffffff",
            fg="#26384d",
            insertbackground="#26384d",
            font=("맑은 고딕", 10),
            justify="left",
        )
        size_entry.pack(side="left", fill="y", padx=(1, 0), pady=1, ipady=5, ipadx=7)
        size_button = tk.Button(
            size_box,
            text="▾",
            width=2,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            bg="#eef2f7",
            fg="#2e486b",
            activebackground="#dfe7f1",
            activeforeground="#2e486b",
            font=("맑은 고딕", 10, "bold"),
            padx=0,
            pady=0,
            cursor="hand2",
        )
        size_button.pack(side="left", fill="y", padx=(0, 1), pady=1)
        self.font_size_combo = size_entry
        self.font_size_button = size_button
        size_entry.bind("<Return>", self.apply_editor_font_size)
        size_entry.bind("<MouseWheel>", lambda _event: "break", add="+")
        add_tooltip(size_box, "글자 크기")

        def show_font_size_popup(_event=None):
            existing = getattr(self, "font_size_popup", None)
            if existing is not None and existing.winfo_exists():
                closer = getattr(existing, "close_popup", None)
                if closer is not None:
                    closer()
                else:
                    existing.destroy()
                    self.font_size_popup = None
                return "break"

            popup = tk.Toplevel(self.root)
            self.font_size_popup = popup
            # Windows에서 overrideredirect 창이 첫 매핑 위치 (0, 0)에 고정되지 않도록
            # 완성된 좌표를 적용할 때까지 화면에 매핑하지 않는다.
            popup.withdraw()
            popup.overrideredirect(True)
            popup.transient(self.root)
            popup.attributes("-topmost", True)
            popup.configure(bg="#cbd5e1")
            outer = tk.Frame(popup, bg="#ffffff", padx=1, pady=1)
            outer.pack(fill="both", expand=True, padx=1, pady=1)
            preview_canvas = tk.Canvas(outer, bg="#ffffff", highlightthickness=0, borderwidth=0)
            preview_scrollbar = ttk.Scrollbar(
                outer, orient="vertical", command=preview_canvas.yview,
                style="ComboPopup.Vertical.TScrollbar",
            )
            preview_canvas.configure(yscrollcommand=preview_scrollbar.set)
            preview_canvas.pack(side="left", fill="both", expand=True)
            rows = tk.Frame(preview_canvas, bg="#ffffff")
            rows_window = preview_canvas.create_window((0, 0), window=rows, anchor="nw")
            outside_binding = {"click": None, "unmap": None}

            def close_popup(_close_event=None):
                if outside_binding["click"] is not None:
                    try:
                        self.root.unbind("<ButtonPress-1>", outside_binding["click"])
                    except tk.TclError:
                        pass
                    outside_binding["click"] = None
                if outside_binding["unmap"] is not None:
                    try:
                        self.root.unbind("<Unmap>", outside_binding["unmap"])
                    except tk.TclError:
                        pass
                    outside_binding["unmap"] = None
                try:
                    if popup.winfo_exists():
                        popup.destroy()
                except tk.TclError:
                    pass
                self.font_size_popup = None

            def choose_size(size):
                self.font_size.set(f"{size} px")
                self.apply_editor_font_size()
                close_popup()
                self.content_editor.text.focus_set()

            popup.close_popup = close_popup

            def scroll_preview(event):
                preview_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
                return "break"

            try:
                current_size = int(self.font_size.get().strip().lower().removesuffix("px").strip())
            except ValueError:
                current_size = 14
            for size in FONT_SIZE_OPTIONS:
                selected = size == current_size
                row = tk.Label(
                    rows,
                    text=f"{size} px",
                    font=self.font_size_preview_fonts[size],
                    bg="#3478f6" if selected else "#ffffff",
                    fg="#ffffff" if selected else "#26384d",
                    anchor="w",
                    padx=10,
                    pady=5,
                    cursor="hand2",
                )
                row.pack(fill="x")
                row.bind("<Button-1>", lambda _click, value=size: choose_size(value))
                row.bind("<MouseWheel>", scroll_preview)
                if not selected:
                    row.bind("<Enter>", lambda _enter, widget=row: widget.configure(bg="#eef2f7"))
                    row.bind("<Leave>", lambda _leave, widget=row: widget.configure(bg="#ffffff"))

            rows.update_idletasks()
            popup.update_idletasks()
            popup_width = max(150, rows.winfo_reqwidth() + 14)
            max_popup_height = min(460, self.root.winfo_screenheight() - 80)
            popup_height = min(max_popup_height, rows.winfo_reqheight() + 4)
            preview_canvas.itemconfigure(rows_window, width=popup_width - 12)
            preview_canvas.configure(scrollregion=(0, 0, popup_width - 12, rows.winfo_reqheight()))
            if rows.winfo_reqheight() > popup_height:
                preview_scrollbar.pack(side="right", fill="y")
            x = size_box.winfo_rootx()
            y = size_box.winfo_rooty() + size_box.winfo_height()
            x = min(x, self.root.winfo_screenwidth() - popup_width)
            if y + popup_height > self.root.winfo_screenheight():
                y = size_box.winfo_rooty() - popup_height
            popup.geometry(f"{popup_width}x{popup_height}+{max(0, x)}+{max(0, y)}")
            popup.deiconify()
            popup.update_idletasks()
            popup.lift()
            popup.bind("<Escape>", close_popup)
            preview_canvas.bind("<MouseWheel>", scroll_preview)
            popup.focus_force()

            def bind_outside_click():
                if popup.winfo_exists():
                    outside_binding["click"] = self.root.bind(
                        "<ButtonPress-1>", close_popup, add="+"
                    )

            # 현재 화살표 클릭 이벤트가 팝업을 즉시 다시 닫지 않도록 다음 틱에 등록한다.
            popup.after_idle(bind_outside_click)
            outside_binding["unmap"] = self.root.bind("<Unmap>", close_popup, add="+")

            def release_topmost():
                try:
                    if popup.winfo_exists():
                        popup.attributes("-topmost", False)
                except tk.TclError:
                    pass

            popup.after(150, release_topmost)
            return "break"

        self.show_font_size_popup = show_font_size_popup
        # ttk/tk Button의 클래스별 Release 처리에 의존하지 않고 누르는 순간 직접 연다.
        size_button.configure(command=lambda: None)
        size_button.bind("<ButtonPress-1>", show_font_size_popup)
        size_entry.bind("<Alt-Down>", show_font_size_popup, add="+")
        size_entry.bind("<F4>", show_font_size_popup, add="+")
        self.toolbar_icons = {}
        self.format_buttons = {}

        def separator():
            tk.Frame(editor_toolbar, bg="#cbd5e1", width=1, height=22).pack(side="left", padx=5)

        def icon_button(icon_name, tooltip, command):
            try:
                image = tk.PhotoImage(file=str(resource_path(f"lucide/{icon_name}.png")))
                self.toolbar_icons[icon_name] = image
            except tk.TclError:
                image = None
            button = tk.Button(
                editor_toolbar, image=image, text="" if image else tooltip[:1], command=command,
                bg="#eef2f7", fg=navy, activebackground="#dfe7f1", activeforeground=navy,
                relief="flat", borderwidth=0, highlightthickness=1,
                highlightbackground="#eef2f7", width=28, height=26,
                padx=0, pady=0, cursor="hand2",
            )
            button.pack(side="left", padx=1)
            add_tooltip(button, tooltip)
            return button

        for icon_name, tooltip, kind in (
            ("bold", "굵게 (Ctrl+B)", "bold"),
            ("italic", "기울임 (Ctrl+I)", "italic"),
            ("underline", "밑줄 (Ctrl+U)", "underline"),
        ):
            self.format_buttons[kind] = icon_button(
                icon_name, tooltip, lambda kind=kind: self.content_editor.toggle_format(kind)
            )
        separator()
        for icon_name, tooltip, alignment in (
            ("align-left", "왼쪽 정렬", "left"),
            ("align-center", "가운데 정렬", "center"),
            ("align-right", "오른쪽 정렬", "right"),
        ):
            self.format_buttons[f"align_{alignment}"] = icon_button(
                icon_name, tooltip,
                lambda alignment=alignment: self.content_editor.set_alignment(alignment),
            )
        separator()
        for icon_name, tooltip, syntax in (
            ("link", "링크 삽입", "link"),
            ("minus", "가로줄 삽입", "rule"),
            ("image", "이미지 삽입", "image"),
        ):
            button = icon_button(icon_name, tooltip, lambda: None)
            button.configure(command=lambda kind=syntax, anchor=button: self.insert_content_syntax(kind, anchor))
        tk.Checkbutton(
            editor_toolbar,
            text="HTML",
            variable=self.html_view,
            command=self.toggle_html_view,
            bg="#eef2f7",
            fg=navy,
            activebackground="#eef2f7",
            activeforeground=navy,
            selectcolor="#eef2f7",
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            font=("맑은 고딕", 9),
            padx=7,
            pady=2,
            cursor="hand2",
        ).pack(side="right")
        self.content_editor = WysiwygEditor(card, self.saved_content, height=150)
        self.content_editor.pack(fill="x", pady=(0, 10))

        def update_toolbar_state(_event=None):
            if self.content_editor.html_mode:
                return
            state = self.content_editor.get_format_state()
            for kind in ("bold", "italic", "underline"):
                selected = state[kind]
                self.format_buttons[kind].configure(
                    bg="#cfe0ff" if selected else "#eef2f7",
                    activebackground="#c3d8fa" if selected else "#dfe7f1",
                    relief="sunken" if selected else "flat",
                    highlightthickness=1,
                    highlightbackground="#3478f6" if selected else "#eef2f7",
                )
            for alignment in ("left", "center", "right"):
                selected = state["alignment"] == alignment
                self.format_buttons[f"align_{alignment}"].configure(
                    bg="#cfe0ff" if selected else "#eef2f7",
                    activebackground="#c3d8fa" if selected else "#dfe7f1",
                    relief="sunken" if selected else "flat",
                    highlightthickness=1,
                    highlightbackground="#3478f6" if selected else "#eef2f7",
                )
            self.font_size.set(f"{state['size']} px" if state["size"] is not None else "— px")

        self.update_toolbar_state = update_toolbar_state
        for event_name in ("<<Selection>>", "<ButtonRelease-1>", "<KeyRelease>"):
            self.content_editor.text.bind(
                event_name, lambda _event: self.root.after_idle(update_toolbar_state), add="+"
            )
        for button in self.format_buttons.values():
            button.bind(
                "<ButtonRelease-1>", lambda _event: self.root.after_idle(update_toolbar_state), add="+"
            )
        update_toolbar_state()
        ttk.Label(card, text="태그 (쉼표로 구분)", style="Card.TLabel").pack(anchor="w")
        self.tag_input = TagBadgeInput(card, self.tags)
        self.tag_input.pack(fill="x", pady=(5, 18))

        ttk.Separator(card).pack(fill="x", pady=(0, 18))
        ttk.Label(card, text="3  기능 및 로그", style="Section.TLabel").pack(anchor="w")
        button_row = ttk.Frame(card, style="Card.TFrame")
        button_row.pack(fill="x", pady=(10, 14))
        ttk.Button(button_row, text="등록 페이지 열기", command=self.launch_browser, style="Navy.TButton").pack(side="left")
        ttk.Button(button_row, text="이미지와 내용 채우기", command=self.start_fill, style="Accent.TButton").pack(side="left", padx=10)
        ttk.Button(button_row, text="폴더 검사", command=self.preview, style="Soft.TButton").pack(side="left")
        ttk.Button(button_row, text="⚙ 매칭 설정", command=self.open_mapping_settings, style="Soft.TButton").pack(side="right")

        status_bar = tk.Frame(card, bg="#eef4fd", padx=12, pady=9)
        status_bar.pack(fill="x", pady=(0, 8))
        tk.Label(status_bar, textvariable=self.status, bg="#eef4fd", fg=navy, font=("맑은 고딕", 10, "bold")).pack(anchor="w")
        self.log_frame = tk.Frame(card, bg="#f7f8fa")
        self.log_frame.pack(fill="both", expand=True)
        self.log_scrollbar = ttk.Scrollbar(self.log_frame, orient="vertical", style="Log.Vertical.TScrollbar")
        self.log = tk.Text(
            self.log_frame,
            height=6,
            wrap="word",
            state="disabled",
            relief="flat",
            bg="#f7f8fa",
            fg=muted,
            font=("맑은 고딕", 9),
            padx=10,
            pady=8,
            yscrollcommand=self.log_scrollbar.set,
        )
        self.log_scrollbar.configure(command=self.log.yview)
        self.log.pack(side="left", fill="both", expand=True)
        for hover_widget in (self.log_frame, self.log, self.log_scrollbar):
            hover_widget.bind("<Enter>", self.show_log_scrollbar, add="+")
            hover_widget.bind("<Leave>", self.schedule_log_scrollbar_hide, add="+")
        self.log_menu = tk.Menu(
            self.log,
            tearoff=False,
            bg="#eef2f7",
            fg=navy,
            activebackground=blue,
            activeforeground=white,
            disabledforeground="#9aa7b6",
            relief="solid",
            borderwidth=1,
            activeborderwidth=0,
            font=("맑은 고딕", 9),
        )
        self.log_menu.add_command(label="로그 지우기", command=self.clear_log)
        self.log.bind("<Button-3>", self.show_log_menu)
        tk.Label(
            card,
            text=(
                "이 프로그램은 개드립넷(dogdrip.net)의 개드립콘 기능을 활용한 무료·비공식 소프트웨어입니다."
                "\n개드립넷의 명칭·서비스·관련 이미지에 대한 권리는 개드립넷(dogdrip.net)에 있습니다."
            ),
            bg=white,
            fg="#8a96a5",
            font=("맑은 고딕", 8),
            justify="center",
            wraplength=760,
            pady=2,
        ).pack(fill="x", pady=(8, 0))
        self.write_log("사용법: 폴더 선택 → 전용 브라우저에서 로그인/등록 페이지 이동 → 파일 자동 배치")
        self.write_log("이름순 예: a.png, b.gif, image2.png, image10.png (자연 정렬)")
        self.write_log("안전을 위해 최종 등록 버튼은 자동으로 누르지 않습니다.")

        def fit_initial_height():
            self.root.update_idletasks()
            usable_height = max(560, self.root.winfo_screenheight() - 80)
            desired_height = header.winfo_reqheight() + page.winfo_reqheight() + 12
            fitted_height = min(usable_height, max(560, desired_height))
            self.root.geometry(f"{window_width}x{fitted_height}")
            self.root.after_idle(update_scroll_region)

        self.root.after_idle(fit_initial_height)
        if not self.guide_seen:
            self.root.after(450, self.show_guide)

    def show_log_menu(self, event):
        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.set_status("로그를 지웠습니다.")
        self.hide_log_scrollbar()

    def show_log_scrollbar(self, _event=None):
        first, last = self.log.yview()
        if first <= 0.0 and last >= 1.0:
            return
        if not self.log_scrollbar.winfo_ismapped():
            self.log_scrollbar.pack(side="right", fill="y", before=self.log)

    def schedule_log_scrollbar_hide(self, _event=None):
        self.root.after(120, self.hide_log_scrollbar_if_outside)

    def hide_log_scrollbar_if_outside(self):
        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        left = self.log_frame.winfo_rootx()
        top = self.log_frame.winfo_rooty()
        right = left + self.log_frame.winfo_width()
        bottom = top + self.log_frame.winfo_height()
        if not (left <= pointer_x < right and top <= pointer_y < bottom):
            self.hide_log_scrollbar()

    def hide_log_scrollbar(self):
        if self.log_scrollbar.winfo_ismapped():
            self.log_scrollbar.pack_forget()

    def show_guide(self):
        if getattr(self, "guide_window", None) and self.guide_window.winfo_exists():
            self.guide_window.lift()
            self.guide_window.focus_force()
            return
        self.guide_seen = True
        self.save_settings()
        navy, blue, white, muted = "#2e486b", "#3478f6", "#ffffff", "#687789"
        dialog = tk.Toplevel(self.root)
        self.guide_window = dialog
        dialog.title("DogDrip.Con Uploader 사용 가이드")
        dialog.geometry("680x760")
        dialog.minsize(600, 570)
        dialog.transient(self.root)
        dialog.lift()
        dialog.configure(bg="#e8ebef")
        center_toplevel(dialog, self.root, 680, 760)

        header = tk.Frame(dialog, bg=navy, padx=24, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="빠른 시작 가이드", bg=navy, fg=white, font=("맑은 고딕", 18, "bold")).pack(anchor="w")
        tk.Label(header, text="아래 세 단계대로 진행하면 개드립콘 등록 준비가 완료됩니다.", bg=navy, fg="#c8d6e8", font=("맑은 고딕", 10)).pack(anchor="w", pady=(4, 0))

        # Reserve the footer before the expanding body so it always remains visible.
        footer = tk.Frame(dialog, bg="#e8ebef", padx=22, height=54)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="이 안내는 최초 실행 시 한 번만 자동으로 표시됩니다.", bg="#e8ebef", fg=muted, font=("맑은 고딕", 9)).pack(side="left", anchor="center", pady=15)
        ttk.Button(footer, text="온라인 매뉴얼 열기", command=open_online_guide, style="Soft.TButton").pack(side="left", anchor="center", padx=(12, 0), pady=8)
        ttk.Button(footer, text="닫기", command=dialog.destroy, style="Accent.TButton").pack(side="right", anchor="center", pady=8)

        body = tk.Frame(dialog, bg="#e8ebef", padx=22, pady=10)
        body.pack(fill="both", expand=True)
        steps = (
            (
                "1",
                "업로드 이미지 선택",
                "• 이미지가 들어 있는 폴더를 선택합니다.\n"
                "• 파일 이름 또는 수정된 날짜 기준의 배치 순서를 선택합니다.\n"
                "• ‘폴더 검사’에서 파일별 배치 위치를 확인합니다.\n"
                "• 첫 번째 파일은 개드립콘 메인 이미지가 됩니다.",
            ),
            (
                "2",
                "게시글 정보 입력",
                "• WYSIWYG 에디터에서 실제 결과와 유사한 형태로 본문을 작성합니다.\n"
                "• 툴바에서 글자 크기·굵게·기울임·밑줄·문단 정렬을 적용할 수 있습니다.\n"
                "• 링크·가로줄·이미지 삽입과 HTML 보기를 사용할 수 있습니다.\n"
                "• 링크와 이미지를 우클릭하면 내용·URL·크기를 수정할 수 있습니다.\n"
                "• 태그는 쉼표로 구분하며 입력한 태그는 배지로 표시됩니다.\n"
                "• 비워 둔 선택 항목은 등록 페이지의 기존 값을 변경하지 않습니다.\n"
                "단축키 가이드\n"
                "• Ctrl+A 전체 선택 · Ctrl+C 복사\n"
                "• Ctrl+X 잘라내기 · Ctrl+V 붙여넣기\n"
                "• Ctrl+B 굵게 · Ctrl+I 기울임 · Ctrl+U 밑줄\n"
                "• Ctrl+Z 실행 취소 · Ctrl+Y 다시 실행\n"
                "• 한글 입력 상태에서도 같은 단축키가 동작합니다.",
            ),
            (
                "3",
                "기능 및 로그",
                "• ‘등록 페이지 열기’는 기본 브라우저가 아닌 Chrome을 우선 실행합니다.\n"
                "• Chrome이 없으면 Edge를 사용하며 전용 프로필에서 로그인을 유지합니다.\n"
                "• ‘이미지와 내용 채우기’로 준비한 값을 자동 배치하고 로그를 확인합니다.\n"
                "• 브라우저에서 결과를 확인한 뒤 최종 등록 버튼은 직접 누릅니다.",
            ),
        )
        for number, title, description in steps:
            card = tk.Frame(body, bg=white, padx=16, pady=5, highlightbackground="#d2d9e2", highlightthickness=1)
            card.pack(fill="x", pady=(1, 5))
            badge = tk.Label(card, text=number, bg=blue, fg=white, font=("맑은 고딕", 11, "bold"), width=3, pady=5)
            badge.pack(side="left", anchor="n", padx=(0, 14))
            copy = tk.Frame(card, bg=white)
            copy.pack(side="left", fill="x", expand=True)
            tk.Label(copy, text=title, bg=white, fg=navy, font=("맑은 고딕", 12, "bold")).pack(anchor="w")
            for description_line in description.splitlines():
                if description_line == "단축키 가이드":
                    tk.Label(
                        copy,
                        text=description_line,
                        bg=white,
                        fg=navy,
                        justify="left",
                        font=("맑은 고딕", 10, "bold"),
                        anchor="w",
                    ).pack(anchor="w", pady=(8, 1))
                    continue
                tk.Label(
                    copy,
                    text=description_line,
                    bg=white,
                    fg=muted,
                    justify="left",
                    font=("맑은 고딕", 9),
                    anchor="w",
                ).pack(anchor="w")

    def load_mapping(self):
        mapping = read_mapping_file(self.mapping_path)
        self.write_mapping(mapping)
        return mapping

    def write_mapping(self, mapping):
        parser = configparser.ConfigParser(interpolation=None)
        parser["mapping"] = mapping
        with self.mapping_path.open("w", encoding="utf-8") as file:
            parser.write(file)

    def open_mapping_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("개드립콘 페이지 매칭 설정")
        dialog.geometry("700x560")
        dialog.transient(self.root)
        dialog.grab_set()
        center_toplevel(dialog, self.root, 700, 560)
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="사이트 HTML이 변경된 경우에만 수정하세요.", font=("맑은 고딕", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        labels = {
            "target_host": "대상 도메인",
            "main_file_name": "메인 이미지 input name",
            "extra_file_pattern": "추가 이미지 패턴",
            "content_selector": "본문 input CSS 선택자",
            "editor_selector": "본문 에디터 CSS 선택자",
            "tag_selector": "태그 input CSS 선택자",
            "title_selector": "제목 input CSS 선택자",
            "price_selector": "포인트 input CSS 선택자",
        }
        values = {}
        for row, (key, label) in enumerate(labels.items(), start=1):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=6)
            value = tk.StringVar(value=self.mapping.get(key, MAPPING_DEFAULTS[key]))
            values[key] = value
            ttk.Entry(body, textvariable=value).grid(row=row, column=1, sticky="ew", pady=6)
        note_row = len(labels) + 1
        ttk.Label(body, text="추가 이미지 패턴에는 순번 위치를 나타내는 {index}가 반드시 필요합니다.", foreground="#555555").grid(row=note_row, column=0, columnspan=2, sticky="w", pady=(10, 16))
        body.columnconfigure(1, weight=1)

        def save():
            updated = {key: value.get().strip() for key, value in values.items()}
            if not all(updated.values()):
                centered_messagebox(dialog, "showerror", APP_TITLE, "모든 매칭 값을 입력해 주세요.")
                return
            if "{index}" not in updated["extra_file_pattern"]:
                centered_messagebox(dialog, "showerror", APP_TITLE, "추가 이미지 패턴에 {index}가 필요합니다.")
                return
            try:
                updated["extra_file_pattern"].format(index=1)
            except (KeyError, ValueError) as exc:
                centered_messagebox(dialog, "showerror", APP_TITLE, f"추가 이미지 패턴이 올바르지 않습니다: {exc}")
                return
            self.write_mapping(updated)
            self.mapping = updated
            self.write_log("페이지 매칭 설정을 저장했습니다.")
            dialog.destroy()

        buttons = ttk.Frame(body)
        buttons.grid(row=note_row + 1, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="INI 파일 열기", command=lambda: os.startfile(self.mapping_path)).pack(side="left")
        ttk.Button(buttons, text="기본값 복원", command=lambda: [values[key].set(value) for key, value in MAPPING_DEFAULTS.items()]).pack(side="left", padx=8)
        ttk.Button(buttons, text="저장", command=save).pack(side="left")

    def write_log(self, text):
        def update():
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, update)

    def set_status(self, text):
        self.root.after(0, lambda: self.status.set(text))

    def load_settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.url.set(data.get("url", DEFAULT_URL))
            self.folder.set(data.get("folder", ""))
            saved_sort = data.get("sort_mode", "파일 이름")
            if saved_sort in {"파일 이름순", "숫자 파일명 (1~50)"}:
                saved_sort = "파일 이름"
            saved_sort = {"변경 날짜": "수정된 날짜", "변경 날짜 (역순)": "수정된 날짜 (역순)"}.get(saved_sort, saved_sort)
            self.sort_mode.set(saved_sort if saved_sort in SORT_OPTIONS else "파일 이름")
            self.tags.set(data.get("tags", ""))
            self.post_title.set(data.get("post_title", ""))
            self.price.set(data.get("price", ""))
            self.saved_content = data.get("content", "")
            self.guide_seen = bool(data.get("guide_seen", False))
        except (OSError, ValueError):
            pass

    def save_settings(self, content=None, tags=None, post_title=None, price=None):
        if content is None:
            content = self.content_editor.get_html()
        if tags is None:
            tags = self.tags.get().strip()
        if post_title is None:
            post_title = self.post_title.get().strip()
        if price is None:
            price = self.price.get().strip()
        data = {
            "url": self.url.get().strip(),
            "folder": self.folder.get().strip(),
            "sort_mode": self.sort_mode.get(),
            "content": content,
            "tags": tags,
            "post_title": post_title,
            "price": price,
            "guide_seen": self.guide_seen,
        }
        self.settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset_default_url(self):
        self.url.set(DEFAULT_URL)
        try:
            self.save_settings()
        except OSError as exc:
            centered_messagebox(self.root, "showerror", APP_TITLE, f"기본 페이지 주소를 저장하지 못했습니다.\n{exc}")
            return
        self.set_status("기본 개드립콘 등록 페이지 주소로 복원했습니다.")
        self.write_log(f"등록 페이지 주소 복원: {DEFAULT_URL}")

    def insert_content_syntax(self, kind, anchor=None):
        if kind == "rule":
            self.content_editor.insert_html("<hr>")
            self.content_editor.focus_editor()
        else:
            self.open_content_insert_dialog(kind, anchor)

    def apply_editor_font_size(self, _event=None):
        value = self.font_size.get().strip().lower().removesuffix("px").strip()
        try:
            size = int(value)
            self.content_editor.set_font_size(size)
        except (TypeError, ValueError):
            self.root.bell()
            self.font_size.set(self.last_font_size)
            return "break"
        self.last_font_size = f"{size} px"
        self.font_size.set(self.last_font_size)
        return "break"

    def toggle_html_view(self):
        self.content_editor.set_html_mode(self.html_view.get())

    def open_content_insert_dialog(self, kind, anchor=None):
        configs = {
            "link": ("링크 삽입", (("표시 텍스트", "text", ""), ("링크", "url", "https://"))),
            "image": ("이미지 삽입", (("설명 텍스트 (선택)", "text", ""), ("이미지 주소", "url", "https://"))),
        }
        if kind not in configs:
            return
        title, fields = configs[kind]
        previous = getattr(self, "content_popover", None)
        if previous is not None and previous.winfo_exists():
            previous.destroy()
        shell = tk.Frame(self.root, bg="#c7d0dd", padx=1, pady=1)
        self.content_popover = shell
        body = ttk.Frame(shell, style="Card.TFrame", padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=title, style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )
        values = {}
        first_entry = None
        for row, (label, key, default) in enumerate(fields, start=1):
            ttk.Label(body, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 10))
            value = tk.StringVar(value=default)
            values[key] = value
            entry = ttk.Entry(body, textvariable=value, width=42 if key == "url" else 24)
            entry.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=(0, 10))
            if key == "url":
                def clean_url_input(_event=None, target=value, target_entry=entry):
                    cleaned = normalize_url_prefix(target.get())
                    if cleaned != target.get():
                        target.set(cleaned)
                        target_entry.icursor("end")
                entry.bind("<KeyRelease>", clean_url_input, add="+")
                entry.bind("<<Paste>>", lambda _event, callback=clean_url_input: body.after_idle(callback), add="+")
            if first_entry is None:
                first_entry = entry
        body.columnconfigure(1, weight=1)
        next_row = len(fields) + 1
        size_entries = []
        if kind == "image":
            keep_ratio_var = tk.BooleanVar(value=False)
            ratio_cache = {"url": None, "image": None}
            ratio_after_id = [None]
            ratio_update_guard = [False]
            last_size_axis = ["width"]
            ratio_check = tk.Checkbutton(
                body, text="원본 비율 맞춤", variable=keep_ratio_var,
                bg="#ffffff", fg="#26384d", activebackground="#ffffff", activeforeground="#26384d",
                selectcolor="#ffffff", highlightthickness=0, borderwidth=0, relief="flat",
                font=("맑은 고딕", 9),
            )
            ratio_check.grid(row=next_row, column=0, sticky="w", pady=(0, 8))
            size_frame = ttk.Frame(body, style="Card.TFrame")
            size_frame.grid(row=next_row, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
            for column, (label, key, default) in enumerate((("가로", "width", ""), ("세로", "height", ""))):
                field = ttk.Frame(size_frame, style="Card.TFrame")
                field.grid(row=0, column=column, sticky="ew", padx=((0, 9) if column == 0 else (9, 0)))
                field.columnconfigure(1, weight=1)
                ttk.Label(field, text=label, style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
                value = tk.StringVar(value=default)
                values[key] = value
                entry = ttk.Entry(field, textvariable=value, width=16)
                entry.grid(row=0, column=1, sticky="ew")
                size_entries.append(entry)
                size_frame.columnconfigure(column, weight=1, uniform="image_size")

            def fetch_original_image():
                url = normalize_url_prefix(values["url"].get())
                if ratio_cache["url"] == url and ratio_cache["image"] is not None:
                    return ratio_cache["image"]
                headers = {"User-Agent": "Mozilla/5.0"}
                if "dcinside.com" in url:
                    headers["Referer"] = "https://gall.dcinside.com/"
                response = requests.get(url, timeout=8, headers=headers)
                response.raise_for_status()
                with Image.open(io.BytesIO(response.content)) as source:
                    original = source.convert("RGBA")
                ratio_cache.update(url=url, image=original)
                return original

            def apply_ratio():
                ratio_after_id[0] = None
                if ratio_update_guard[0] or not keep_ratio_var.get() or not shell.winfo_exists():
                    return
                axis = last_size_axis[0]
                source_var = values[axis]
                try:
                    value = int(source_var.get().strip())
                    if not 1 <= value <= 4096:
                        return
                    original_width, original_height = fetch_original_image().size
                    ratio_update_guard[0] = True
                    if axis == "width":
                        values["height"].set(str(matching_image_dimension(value, original_width, original_height)))
                    else:
                        values["width"].set(str(matching_image_dimension(value, original_height, original_width)))
                except Exception:
                    return
                finally:
                    ratio_update_guard[0] = False

            def schedule_ratio(axis):
                if ratio_update_guard[0]:
                    return
                last_size_axis[0] = axis
                if ratio_after_id[0] is not None:
                    body.after_cancel(ratio_after_id[0])
                ratio_after_id[0] = body.after(450, apply_ratio)

            preview_frame = tk.Frame(body, bg="#edf2f8", width=520, height=270, relief="flat")
            preview_frame.grid(row=next_row + 1, column=0, columnspan=2, sticky="ew", pady=(8, 4))
            preview_frame.grid_propagate(False)
            preview_box = tk.Canvas(preview_frame, width=520, height=270, bg="#edf2f8", highlightthickness=0)
            preview_box.pack(fill="both", expand=True)
            preview_box.create_text(260, 135, text="이미지 URL을 입력해 주세요.", fill="#53657a")
            preview_status = ttk.Label(body, text="", style="Hint.TLabel", anchor="center")
            preview_status.grid(row=next_row + 2, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            preview_refs = []
            preview_after_id = [None]

            def load_insert_preview():
                preview_after_id[0] = None
                try:
                    original = fetch_original_image()
                    width_text = values["width"].get().strip()
                    height_text = values["height"].get().strip()
                    width = int(width_text) if width_text else None
                    height = int(height_text) if height_text else None
                    if any(value is not None and not 1 <= value <= 4096 for value in (width, height)):
                        return
                    if width is None and height is None:
                        target_width, target_height = original.size
                    else:
                        target_width = width if width is not None else matching_image_dimension(height, original.height, original.width)
                        target_height = height if height is not None else matching_image_dimension(width, original.width, original.height)
                    preview = original.resize((target_width, target_height), Image.Resampling.LANCZOS)
                    scale = min(1.0, 500 / target_width, 250 / target_height)
                    shown_width = max(1, round(target_width * scale))
                    shown_height = max(1, round(target_height * scale))
                    if preview.size != (shown_width, shown_height):
                        preview = preview.resize((shown_width, shown_height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(preview, master=self.root)
                    preview_refs[:] = [photo]
                    preview_box.delete("all")
                    preview_box.create_rectangle(0, 0, 520, 270, fill="#edf2f8", outline="")
                    preview_box.create_image(260, 135, image=photo, anchor="center")
                    preview_box.create_rectangle(
                        260 - shown_width / 2, 135 - shown_height / 2,
                        260 + shown_width / 2, 135 + shown_height / 2,
                        outline="#c4cedb",
                    )
                    preview_status.configure(
                        text=f"원본 {original.width}×{original.height}  ·  적용 {target_width}×{target_height}  ·  미리보기 {round(scale * 100)}%"
                    )
                except Exception:
                    preview_box.delete("all")
                    preview_box.create_text(260, 135, text="이미지 URL을 확인해 주세요.", fill="#53657a")
                    preview_status.configure(text="")

            def schedule_insert_preview():
                if preview_after_id[0] is not None:
                    body.after_cancel(preview_after_id[0])
                preview_after_id[0] = body.after(550, load_insert_preview)

            def handle_size_change(axis):
                schedule_ratio(axis)
                schedule_insert_preview()

            def handle_url_change():
                ratio_cache.update(url=None, image=None)
                schedule_insert_preview()

            values["width"].trace_add("write", lambda *_args: handle_size_change("width"))
            values["height"].trace_add("write", lambda *_args: handle_size_change("height"))
            values["url"].trace_add("write", lambda *_args: handle_url_change())
            ratio_check.configure(command=lambda: (schedule_ratio(last_size_axis[0]), schedule_insert_preview()))

            next_row += 3

        def close_popover():
            if shell.winfo_exists():
                shell.destroy()
            if getattr(self, "content_popover", None) is shell:
                self.content_popover = None

        def submit():
            has_size = kind == "image" and (values.get("width").get().strip() or values.get("height").get().strip())
            syntax_kind = "sized_image" if has_size else kind
            try:
                values["url"].set(normalize_url_prefix(values["url"].get()))
                syntax_values = {key: value.get() for key, value in values.items()}
                markup = build_content_syntax(syntax_kind, **syntax_values)
            except ValueError as exc:
                centered_messagebox(self.root, "showerror", title, str(exc))
                return
            self.content_editor.insert_html(markup)
            self.content_editor.focus_editor()
            close_popover()

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=next_row, column=0, columnspan=2, sticky="e", pady=(4, 0))
        ttk.Button(buttons, text="취소", command=close_popover, style="Soft.TButton").pack(side="left")
        ttk.Button(buttons, text="확인", command=submit, style="Navy.TButton").pack(side="left", padx=(8, 0))
        for entry in body.winfo_children():
            entry.bind("<Return>", lambda _event: submit())
            entry.bind("<Escape>", lambda _event: close_popover())
        shell.update_idletasks()
        anchor = anchor or self.root
        x = anchor.winfo_rootx() - self.root.winfo_rootx()
        x += max(0, (anchor.winfo_width() - shell.winfo_reqwidth()) // 2)
        y = anchor.winfo_rooty() - self.root.winfo_rooty() + anchor.winfo_height() + 7
        x = min(max(8, x), max(8, self.root.winfo_width() - shell.winfo_reqwidth() - 8))
        if y + shell.winfo_reqheight() > self.root.winfo_height() - 8:
            y = anchor.winfo_rooty() - self.root.winfo_rooty() - shell.winfo_reqheight() - 7
        shell.place(x=x, y=max(8, y))
        shell.lift()
        if first_entry is not None:
            first_entry.focus_set()

    def choose_folder(self):
        selected = filedialog.askdirectory(title="1~50번 이미지가 든 폴더 선택")
        if selected:
            self.folder.set(selected)
            self.preview()

    def preview(self):
        try:
            mode = SORT_OPTIONS.get(self.sort_mode.get(), "name")
            files, ignored = collect_files(self.folder.get(), mode)
            self.set_status(f"{len(files)}개 파일 준비 완료 — 첫 파일: {files[0].name}")
            mapping_lines = ["배치 순서"]
            for index, path in enumerate(files, start=1):
                destination = "메인 이미지" if index == 1 else f"{index}번 이미지"
                mapping_lines.append(f"  {index:02d}. {path.name}  →  {destination}")
            self.write_log("\n".join(mapping_lines))
            if ignored:
                self.write_log("번호 형식이 아니어서 제외: " + ", ".join(ignored))
            self.save_settings()
        except Exception as exc:
            self.set_status("폴더를 확인해 주세요.")
            centered_messagebox(self.root, "showerror", APP_TITLE, str(exc))

    def launch_browser(self):
        try:
            browser = find_browser()
            self.profile_path.mkdir(exist_ok=True)
            subprocess.Popen([
                str(browser),
                "--remote-debugging-port=9222",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile_path}",
                "--no-first-run",
                self.url.get().strip() or DEFAULT_URL,
            ])
            self.save_settings()
            self.set_status("전용 브라우저에서 로그인하고 등록 페이지를 열어 주세요.")
            self.write_log(f"브라우저 실행: {browser.name}")
        except Exception as exc:
            centered_messagebox(self.root, "showerror", APP_TITLE, str(exc))

    def start_fill(self):
        content = self.content_editor.get_html()
        tags = self.tags.get().strip()
        post_title = self.post_title.get().strip()
        price = self.price.get().strip()
        if price and not price.isdigit():
            centered_messagebox(self.root, "showerror", APP_TITLE, "판매 포인트는 0 이상의 숫자로 입력해 주세요.")
            return
        threading.Thread(target=self.fill_files, args=(content, tags, post_title, price), daemon=True).start()

    def fill_files(self, content, tags, post_title, price):
        try:
            mode = SORT_OPTIONS.get(self.sort_mode.get(), "name")
            files, ignored = collect_files(self.folder.get(), mode)
            self.set_status("브라우저 연결 중…")
            tabs = requests.get("http://127.0.0.1:9222/json/list", timeout=3).json()
            target_host = self.mapping["target_host"]
            candidates = [tab for tab in tabs if tab.get("type") == "page" and target_host in tab.get("url", "")]
            if not candidates:
                raise RuntimeError("전용 브라우저에서 개드립콘 등록 페이지를 열어 주세요.")
            tab = next((item for item in candidates if "dogcon" in item.get("url", "")), candidates[0])
            client = CdpClient(tab["webSocketDebuggerUrl"])
            try:
                document = client.call("DOM.getDocument", {"depth": -1, "pierce": True})
                root_id = document["root"]["nodeId"]
                result = client.call("DOM.querySelectorAll", {"nodeId": root_id, "selector": 'input[type="file"]'})
                inputs = {}
                for node_id in result["nodeIds"]:
                    node = client.call("DOM.describeNode", {"nodeId": node_id})["node"]
                    attrs = dict(zip(node.get("attributes", [])[0::2], node.get("attributes", [])[1::2]))
                    if attrs.get("name"):
                        inputs[attrs["name"]] = node_id

                assignments = {self.mapping["main_file_name"]: files[0]}
                assignments.update({self.mapping["extra_file_pattern"].format(index=index): path for index, path in enumerate(files[1:], start=1)})
                missing_inputs = [name for name in assignments if name not in inputs]
                if missing_inputs:
                    raise RuntimeError("페이지에서 업로드 칸을 찾지 못했습니다: " + ", ".join(missing_inputs[:5]))
                for name, path in assignments.items():
                    client.call("DOM.setFileInputFiles", {"nodeId": inputs[name], "files": [str(path)]})
                client.call("Runtime.evaluate", {"expression": """
                    document.querySelectorAll('input[type=file]').forEach(el => {
                        if (el.files && el.files.length) el.dispatchEvent(new Event('change', {bubbles:true}));
                    });
                """})
                if content.strip():
                    safe_html = content
                    content_selector = json.dumps(self.mapping["content_selector"])
                    editor_selector = json.dumps(self.mapping["editor_selector"])
                    expression = f"""(() => {{
                        const html = {json.dumps(safe_html)};
                        const contentSelector = {content_selector};
                        const editorSelector = {editor_selector};
                        let changed = 0;
                        document.querySelectorAll(contentSelector).forEach(el => {{
                            el.value = html;
                            el.dispatchEvent(new Event('input', {{bubbles:true}}));
                            el.dispatchEvent(new Event('change', {{bubbles:true}}));
                            changed++;
                        }});
                        document.querySelectorAll('iframe').forEach(frame => {{
                            try {{
                                const body = frame.contentDocument && frame.contentDocument.body;
                                if (body && (body.isContentEditable || body.getAttribute('contenteditable') === 'true')) {{
                                    body.innerHTML = html;
                                    body.dispatchEvent(new Event('input', {{bubbles:true}}));
                                    changed++;
                                }}
                            }} catch (_error) {{}}
                        }});
                        const editable = document.querySelector(editorSelector);
                        if (editable) {{
                            editable.innerHTML = html;
                            editable.dispatchEvent(new Event('input', {{bubbles:true}}));
                            changed++;
                        }}
                        return changed;
                    }})()"""
                    content_result = client.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                    changed = content_result.get("result", {}).get("value", 0)
                    if not changed:
                        raise RuntimeError("페이지에서 게시글 내용 편집기를 찾지 못했습니다.")
                if tags:
                    tag_selector = json.dumps(self.mapping["tag_selector"])
                    tag_expression = f"""(() => {{
                        const selector = {tag_selector};
                        const value = {json.dumps(tags)};
                        const fields = Array.from(document.querySelectorAll(selector));
                        fields.forEach(el => {{
                            el.value = value;
                            el.dispatchEvent(new Event('input', {{bubbles:true}}));
                            el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        }});
                        return fields.length;
                    }})()"""
                    tag_result = client.call("Runtime.evaluate", {"expression": tag_expression, "returnByValue": True})
                    changed_tags = tag_result.get("result", {}).get("value", 0)
                    if not changed_tags:
                        raise RuntimeError("페이지에서 태그 입력란을 찾지 못했습니다. 매칭 설정의 태그 선택자를 확인하세요.")
                for field_label, field_value, selector_key in (
                    ("게시글 제목", post_title, "title_selector"),
                    ("판매 포인트", price, "price_selector"),
                ):
                    if not field_value:
                        continue
                    field_expression = f"""(() => {{
                        const fields = Array.from(document.querySelectorAll({json.dumps(self.mapping[selector_key])}));
                        fields.forEach(el => {{
                            el.value = {json.dumps(field_value)};
                            el.dispatchEvent(new Event('input', {{bubbles:true}}));
                            el.dispatchEvent(new Event('change', {{bubbles:true}}));
                        }});
                        return fields.length;
                    }})()"""
                    field_result = client.call("Runtime.evaluate", {"expression": field_expression, "returnByValue": True})
                    changed_fields = field_result.get("result", {}).get("value", 0)
                    if not changed_fields:
                        raise RuntimeError(f"페이지에서 {field_label} 입력란을 찾지 못했습니다. 매칭 설정을 확인하세요.")
            finally:
                client.close()
            self.save_settings(content, tags, post_title, price)
            self.set_status(f"{len(files)}개 파일을 배치했습니다. 브라우저에서 확인하세요.")
            content_status = " + 게시글 내용" if content.strip() else ""
            tag_status = " + 태그" if tags else ""
            title_status = " + 제목" if post_title else ""
            price_status = " + 포인트" if price else ""
            self.write_log(f"자동 배치 완료: {len(files)}개, 메인 이미지 {files[0].name}{title_status}{price_status}{content_status}{tag_status}")
            centered_messagebox(self.root, "showinfo", APP_TITLE, "내용 채우기가 완료되었습니다.\n브라우저에서 내용을 확인한 후 직접 등록해 주세요.")
        except Exception as exc:
            self.set_status("자동 배치 실패")
            self.write_log("오류: " + str(exc))
            self.root.after(0, lambda: centered_messagebox(self.root, "showerror", APP_TITLE, str(exc)))


def run_app():
    root = tk.Tk()
    App(root)
    root.mainloop()


def run_editor_self_test(output_path):
    root = tk.Tk()
    root.geometry("320x180+-10000+-10000")
    editor = WysiwygEditor(root, "<p>초기 내용</p>", height=150)
    editor.pack(fill="both", expand=True)
    root.update()
    editor.insert_html('<a href="https://example.com">링크</a><hr><img src="" alt="이미지">')
    editor.text.insert("insert", "직접 입력")
    root.focus_force()
    editor.focus_editor()
    root.clipboard_clear()
    root.clipboard_append("키보드 입력")
    editor.text.event_generate("<<Paste>>")
    root.update()
    editor.set_html_mode(True)
    editor.text.insert("end", "<br>HTML 편집")
    raw_html_visible = "<a href=" in editor.text.get("1.0", "end-1c")
    editor.set_html_mode(False)
    result = editor.get_html()
    focused = editor.text.focus_get() is editor.text
    root.clipboard_clear()
    root.destroy()
    required = ("초기 내용", "https://example.com", "<hr", "<img", "직접 입력", "키보드 입력", "HTML 편집")
    payload = {"ok": focused and raw_html_visible and all(item in result for item in required), "focused": focused, "raw_html_visible": raw_html_visible, "html": result}
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload["ok"]


def run_startup_self_test(output_path):
    root = tk.Tk()
    app = App(root)
    root.update_idletasks()
    popup_probe = tk.Toplevel(root)
    center_toplevel(popup_probe, root, 200, 100)
    popup_probe.update_idletasks()
    expected_popup_x = max(0, min(root.winfo_x() + (root.winfo_width() - 200) // 2, root.winfo_screenwidth() - 200))
    expected_popup_y = max(0, min(root.winfo_y() + (root.winfo_height() - 100) // 2, root.winfo_screenheight() - 100))
    popup_centered = abs(popup_probe.winfo_x() - expected_popup_x) <= 1 and abs(popup_probe.winfo_y() - expected_popup_y) <= 1
    popup_probe.destroy()
    version_label_checked = app.version_label.cget("text") == f"v{APP_VERSION}"
    font_combo_checked = (
        str(app.font_size_combo.cget("state")) == "normal"
        and app.font_size.get() == "14 px"
        and app.font_size_button.winfo_exists()
        and tuple(app.font_size_preview_fonts) == FONT_SIZE_OPTIONS
        and not app.font_size_combo.bind("<FocusOut>")
    )
    app.page_canvas.configure(scrollregion=(0, 0, 900, 3000))
    app.page_canvas.yview_moveto(0.4)
    page_position_before_combo_wheel = app.page_canvas.yview()
    app.font_size_combo.event_generate("<MouseWheel>", delta=-120)
    combo_wheel_isolated = app.page_canvas.yview() == page_position_before_combo_wheel
    app.page_canvas.yview_moveto(0)
    root.update()
    empty_tag_entry_x = app.tag_input.entry.winfo_rootx()
    app.content_editor.insert_html('<a href="https://example.com">시작 테스트</a><hr>')
    app.tag_input.input_var.set("태그 테스트")
    app.tag_input.commit_event()
    badge_checked = app.tags.get() == "태그 테스트" and len(app.tag_input.badge_frame.winfo_children()) == 1
    root.focus_force()
    root.update()
    app.tag_input.badge_frame.winfo_children()[0].event_generate("<ButtonRelease-1>")
    root.update()
    tag_layout_collapsed = app.tag_input.entry.winfo_rootx() == empty_tag_entry_x and not app.tag_input.badge_frame.winfo_ismapped()
    cursor_restored = app.tags.get() == "" and root.focus_get() is app.tag_input.entry and app.tag_input.entry.index("insert") == 0 and app.tag_input._pointer_reset_count == 1 and tag_layout_collapsed
    app.html_view.set(True)
    app.toggle_html_view()
    html_checked = app.content_editor.html_mode and "시작 테스트" in app.content_editor.text.get("1.0", "end-1c")
    app.html_view.set(False)
    app.toggle_html_view()
    result = app.content_editor.get_html()
    # 전용 폰트 팝다운의 캔버스 휠이 메인 페이지까지 전파되지 않는지 검증한다.
    app.show_font_size_popup()
    root.update()
    popup_canvas = next(
        child
        for outer in app.font_size_popup.winfo_children()
        for child in outer.winfo_children()
        if isinstance(child, tk.Canvas)
    )
    app.page_canvas.configure(scrollregion=(0, 0, 900, 3000))
    app.page_canvas.yview_moveto(0.4)
    page_position_before_popup_wheel = app.page_canvas.yview()
    popup_canvas.event_generate("<MouseWheel>", delta=-120)
    popup_wheel_isolated = app.page_canvas.yview() == page_position_before_popup_wheel
    app.font_size_popup.close_popup()
    app.page_canvas.yview_moveto(0)
    root.update()
    app.show_guide()
    root.update_idletasks()
    guide_labels = []
    guide_buttons = []
    pending_widgets = [app.guide_window]
    while pending_widgets:
        current_widget = pending_widgets.pop()
        pending_widgets.extend(current_widget.winfo_children())
        if isinstance(current_widget, tk.Label):
            guide_labels.append(str(current_widget.cget("text")))
        if isinstance(current_widget, ttk.Button):
            guide_buttons.append(str(current_widget.cget("text")))
    guide_text = "\n".join(guide_labels)
    guide_updated = all(
        phrase in guide_text
        for phrase in ("WYSIWYG 에디터", "단축키 가이드", "Ctrl+A", "Ctrl+B", "Ctrl+C", "Ctrl+Z", "Ctrl+Y")
    )
    online_guide_button_checked = "온라인 매뉴얼 열기" in guide_buttons
    app.guide_window.destroy()
    payload = {
        "ok": root.winfo_exists() == 1 and BRAND_TITLE in root.title() and version_label_checked and font_combo_checked and combo_wheel_isolated and popup_wheel_isolated and popup_centered and html_checked and badge_checked and cursor_restored and guide_updated and online_guide_button_checked and "시작 테스트" in result and "<hr" in result,
        "version_label": version_label_checked,
        "font_combo": font_combo_checked,
        "combo_wheel_isolated": combo_wheel_isolated,
        "popup_wheel_isolated": popup_wheel_isolated,
        "popup_centered": popup_centered,
        "html_toggle": html_checked,
        "tag_badge": badge_checked,
        "tag_cursor_restored": cursor_restored,
        "mouse_pointer_reset": app.tag_input._pointer_reset_count == 1,
        "tag_layout_collapsed": tag_layout_collapsed,
        "guide_updated": guide_updated,
        "online_guide_button": online_guide_button_checked,
        "title": root.title(),
        "size": [root.winfo_width(), root.winfo_height()],
        "html": result,
    }
    root.destroy()
    Path(output_path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload["ok"]


if __name__ == "__main__":
    self_test_arg = next((arg for arg in sys.argv[1:] if arg.startswith("--self-test-output=")), None)
    startup_test_arg = next((arg for arg in sys.argv[1:] if arg.startswith("--startup-test-output=")), None)
    if self_test_arg:
        raise SystemExit(0 if run_editor_self_test(self_test_arg.split("=", 1)[1]) else 1)
    if startup_test_arg:
        raise SystemExit(0 if run_startup_self_test(startup_test_arg.split("=", 1)[1]) else 1)
    run_app()
