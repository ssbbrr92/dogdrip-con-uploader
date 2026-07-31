import json
import html
import configparser
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import requests
import websocket


APP_TITLE = "개드립콘 폴더 업로더"
BRAND_TITLE = "DogDrip.Con Uploader"
DEFAULT_URL = "https://www.dogdrip.net/index.php?mid=dogcon&act=dispDogconWrite"
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MARKDOWN_TOKEN = re.compile(
    r"!\[([^\]\n]*)\]\((https?://[^\s)]+)\)(?:\{(\d{1,5})\s*,\s*(\d{1,5})\})?|"
    r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)",
    re.IGNORECASE,
)
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


def app_dir():
    return Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def resource_path(name):
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / name
    source_dir = Path(__file__).resolve().parent
    asset_path = source_dir.parent / "assets" / name
    return asset_path if asset_path.exists() else source_dir / name


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


def render_inline(text):
    """Convert safe inline Markdown links and remote images."""
    output = []
    position = 0
    for match in MARKDOWN_TOKEN.finditer(text):
        output.append(html.escape(text[position:match.start()]))
        if match.group(1) is not None:
            alt = html.escape(match.group(1), quote=True)
            url = html.escape(match.group(2), quote=True)
            if match.group(3) and match.group(4):
                width = min(4096, max(1, int(match.group(3))))
                height = min(4096, max(1, int(match.group(4))))
                output.append(
                    f'<img src="{url}" alt="{alt}" width="{width}" height="{height}" '
                    f'style="width:{width}px;height:{height}px;max-width:100%;object-fit:contain;">'
                )
            else:
                output.append(f'<img src="{url}" alt="{alt}" style="max-width:100%;height:auto;">')
        else:
            label = html.escape(match.group(5))
            url = html.escape(match.group(6), quote=True)
            output.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>')
        position = match.end()
    output.append(html.escape(text[position:]))
    return "".join(output)


def render_content(text):
    """Convert safe Markdown-style links/rules and preserve line breaks."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    rendered = []
    for index, line in enumerate(lines):
        is_rule = line.strip() == "---"
        rendered.append("<hr>" if is_rule else render_inline(line))
        if index == len(lines) - 1:
            continue
        next_is_rule = lines[index + 1].strip() == "---"
        # <hr> is already a block separator. Do not add an extra <br>
        # immediately before or after it; explicit blank lines still survive.
        if not is_rule and not next_is_rule:
            rendered.append("<br>")
    return "".join(rendered)


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


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{BRAND_TITLE} - {APP_TITLE}")
        self.root.geometry("760x680")
        self.root.minsize(680, 600)
        self.settings_path = app_dir() / "dogcon-uploader-settings.json"
        self.mapping_path = app_dir() / "dogcon-uploader.ini"
        self.profile_path = app_dir() / "dogcon-browser-profile"
        self.mapping = self.load_mapping()
        self.folder = tk.StringVar()
        self.url = tk.StringVar(value=DEFAULT_URL)
        self.sort_mode = tk.StringVar(value="파일 이름순")
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
        guide_area = tk.Frame(header_inner, bg=navy, cursor="hand2")
        guide_area.pack(side="right")
        guide_text = tk.Label(guide_area, text="Guide", bg=navy, fg="#d9e5f5", font=("맑은 고딕", 10, "bold"), cursor="hand2")
        guide_text.pack(side="left", padx=(0, 6))
        guide_icon = tk.Canvas(guide_area, width=20, height=20, bg=navy, highlightthickness=0, cursor="hand2")
        guide_icon.create_oval(1, 1, 19, 19, outline="#d9e5f5", width=1)
        guide_icon.create_text(10, 10, text="!", fill="#d9e5f5", font=("맑은 고딕", 9, "bold"))
        guide_icon.pack(side="left")
        for guide_widget in (guide_area, guide_text, guide_icon):
            guide_widget.bind("<Button-1>", lambda _event: self.show_guide())

        scroll_container = tk.Frame(self.root, bg=page_bg)
        scroll_container.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_container, bg=page_bg, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        page = ttk.Frame(canvas, style="Page.TFrame", padding=(26, 22))
        page_window = canvas.create_window((0, 0), window=page, anchor="nw")

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

        def scroll_page(event):
            if isinstance(event.widget, tk.Text):
                return None
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        page.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_page_width)
        self.root.bind_all("<MouseWheel>", scroll_page, add="+")
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
        sort_box = ttk.Combobox(sort_row, textvariable=self.sort_mode, values=("파일 이름순", "숫자 파일명 (1~50)"), state="readonly", width=22, style="Order.TCombobox")
        sort_box.pack(side="left", padx=(10, 12))
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.preview())
        ttk.Label(sort_row, text="첫 번째 파일이 메인 이미지가 됩니다.", style="Hint.TLabel").pack(side="left")

        ttk.Separator(card).pack(fill="x", pady=(0, 18))
        ttk.Label(card, text="2  게시글 정보", style="Section.TLabel").pack(anchor="w")
        ttk.Label(card, text="개드립콘 등록 페이지 주소", style="Card.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Entry(card, textvariable=self.url).pack(fill="x", pady=(5, 10))
        info_row = ttk.Frame(card, style="Card.TFrame")
        info_row.pack(fill="x", pady=(0, 10))
        title_box = ttk.Frame(info_row, style="Card.TFrame")
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="게시글 제목 (선택 사항)", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(title_box, textvariable=self.post_title).pack(fill="x", pady=(5, 0))
        price_box = ttk.Frame(info_row, style="Card.TFrame")
        price_box.pack(side="left", padx=(12, 0))
        ttk.Label(price_box, text="판매 포인트", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(price_box, textvariable=self.price, width=14).pack(pady=(5, 0))
        content_label_row = ttk.Frame(card, style="Card.TFrame")
        content_label_row.pack(fill="x")
        ttk.Label(content_label_row, text="게시글 내용 (선택 사항)", style="Card.TLabel").pack(side="left")
        help_icon = tk.Canvas(content_label_row, width=18, height=18, bg=white, highlightthickness=0, cursor="question_arrow")
        help_icon.create_oval(1, 1, 17, 17, fill=navy, outline=navy)
        help_icon.create_text(9, 9, text="!", fill="white", font=("맑은 고딕", 8, "bold"))
        help_icon.pack(side="left", padx=(7, 0))
        self.content_tooltip = Tooltip(
            help_icon,
            "게시글 내용 문법\n\n"
            "링크: [표시할 텍스트](https://example.com)\n"
            "가로줄: 별도의 한 줄에 ---\n"
            "이미지: ![대체 텍스트](https://example.com/image.png)\n\n"
            "이미지 크기: ![대체 텍스트](URL){가로, 세로}\n"
            "예시: ![샘플](https://example.com/a.png){320, 200}\n\n"
            "이미지는 HTTP/HTTPS URL만 지원합니다.\n"
            "PC의 로컬 파일 경로는 개드립 에디터에서 직접 첨부해 주세요.",
        )
        self.content_text = tk.Text(card, height=6, wrap="word", relief="solid", borderwidth=1, highlightthickness=0, font=("맑은 고딕", 10), fg=text, bg="#fbfcfe", insertbackground=text, padx=9, pady=8)
        self.content_text.pack(fill="x", pady=(5, 4))
        if self.saved_content:
            self.content_text.insert("1.0", self.saved_content)
        ttk.Label(card, text="링크·가로줄·이미지 문법은 제목 옆 ! 아이콘에서 확인할 수 있습니다.", style="Hint.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(card, text="태그 (선택 사항, 쉼표로 구분)", style="Card.TLabel").pack(anchor="w")
        ttk.Entry(card, textvariable=self.tags).pack(fill="x", pady=(5, 18))

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
        dialog.geometry("680x590")
        dialog.minsize(600, 520)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#e8ebef")
        dialog.update_idletasks()
        popup_width = dialog.winfo_width()
        popup_height = dialog.winfo_height()
        popup_x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - popup_width) // 2)
        popup_y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - popup_height) // 2)
        dialog.geometry(f"{popup_width}x{popup_height}+{popup_x}+{popup_y}")

        header = tk.Frame(dialog, bg=navy, padx=24, pady=14)
        header.pack(fill="x")
        tk.Label(header, text="빠른 시작 가이드", bg=navy, fg=white, font=("맑은 고딕", 18, "bold")).pack(anchor="w")
        tk.Label(header, text="아래 세 단계대로 진행하면 개드립콘 등록 준비가 완료됩니다.", bg=navy, fg="#c8d6e8", font=("맑은 고딕", 10)).pack(anchor="w", pady=(4, 0))

        # Reserve the footer before the expanding body so it always remains visible.
        footer = tk.Frame(dialog, bg="#e8ebef", padx=22, height=54)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="이 안내는 최초 실행 시 한 번만 자동으로 표시됩니다.", bg="#e8ebef", fg=muted, font=("맑은 고딕", 9)).pack(side="left", anchor="center", pady=15)
        ttk.Button(footer, text="닫기", command=dialog.destroy, style="Accent.TButton").pack(side="right", anchor="center", pady=8)

        body = tk.Frame(dialog, bg="#e8ebef", padx=22, pady=10)
        body.pack(fill="both", expand=True)
        steps = (
            (
                "1",
                "업로드 이미지 선택",
                "• 이미지가 들어 있는 폴더를 선택합니다.\n"
                "• 파일 이름순 또는 숫자 파일명 순서를 선택합니다.\n"
                "• ‘폴더 검사’에서 파일별 배치 위치를 확인합니다.\n"
                "• 첫 번째 파일은 개드립콘 메인 이미지가 됩니다.",
            ),
            (
                "2",
                "게시글 정보 입력",
                "• 게시글 제목, 판매 포인트, 본문과 태그를 입력합니다.\n"
                "• 본문은 링크, 가로줄, 원격 이미지 문법을 지원합니다.\n"
                "• 제목이나 포인트 등을 비워두면 해당 페이지 값은 변경하지 않습니다.\n"
                "• 본문 제목 옆 ! 아이콘에서 문법 도움말을 볼 수 있습니다.",
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
                messagebox.showerror(APP_TITLE, "모든 매칭 값을 입력해 주세요.", parent=dialog)
                return
            if "{index}" not in updated["extra_file_pattern"]:
                messagebox.showerror(APP_TITLE, "추가 이미지 패턴에 {index}가 필요합니다.", parent=dialog)
                return
            try:
                updated["extra_file_pattern"].format(index=1)
            except (KeyError, ValueError) as exc:
                messagebox.showerror(APP_TITLE, f"추가 이미지 패턴이 올바르지 않습니다: {exc}", parent=dialog)
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
            self.sort_mode.set(data.get("sort_mode", "파일 이름순"))
            self.tags.set(data.get("tags", ""))
            self.post_title.set(data.get("post_title", ""))
            self.price.set(data.get("price", ""))
            self.saved_content = data.get("content", "")
            self.guide_seen = bool(data.get("guide_seen", False))
        except (OSError, ValueError):
            pass

    def save_settings(self, content=None, tags=None, post_title=None, price=None):
        if content is None:
            content = self.content_text.get("1.0", "end-1c")
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

    def choose_folder(self):
        selected = filedialog.askdirectory(title="1~50번 이미지가 든 폴더 선택")
        if selected:
            self.folder.set(selected)
            self.preview()

    def preview(self):
        try:
            mode = "name" if self.sort_mode.get() == "파일 이름순" else "number"
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
            messagebox.showerror(APP_TITLE, str(exc))

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
            messagebox.showerror(APP_TITLE, str(exc))

    def start_fill(self):
        content = self.content_text.get("1.0", "end-1c")
        tags = self.tags.get().strip()
        post_title = self.post_title.get().strip()
        price = self.price.get().strip()
        if price and not price.isdigit():
            messagebox.showerror(APP_TITLE, "판매 포인트는 0 이상의 숫자로 입력해 주세요.")
            return
        threading.Thread(target=self.fill_files, args=(content, tags, post_title, price), daemon=True).start()

    def fill_files(self, content, tags, post_title, price):
        try:
            mode = "name" if self.sort_mode.get() == "파일 이름순" else "number"
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
                    safe_html = render_content(content)
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
            messagebox.showinfo(APP_TITLE, "파일 배치가 완료되었습니다.\n브라우저에서 제목·가격·이미지를 확인한 후 직접 등록해 주세요.")
        except Exception as exc:
            self.set_status("자동 배치 실패")
            self.write_log("오류: " + str(exc))
            self.root.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
