# -*- coding: utf-8 -*-
"""經典圖庫搜尋 v0.2  作者:ArchieKUO
免費圖庫搜尋（Pexels、Unsplash、Pixabay…）、勾選批次下載、收藏。
介面顏色跟著 Windows 淺色／深色設定。
"""
import os
import re
import io
import csv
import json
import queue
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
import requests
from PIL import Image, ImageOps, ImageDraw

APP_NAME = "經典圖庫搜尋"
VERSION = "v0.2"
AUTHOR = "作者:ArchieKUO"
GOLD = "#C9A227"
UA = {"User-Agent": "ClassicPhotoSearch/0.2 (personal desktop app)"}
PER_FETCH = 24
PER_PAGE = 6
MOCK = os.environ.get("PHOTO_MOCK") == "1"
SMOKE = os.environ.get("PHOTO_SMOKE") == "1"
FONT = "Microsoft JhengHei UI"

ACCENT = ("#1F6FB2", "#3B8ED8")
ACCENT_HOVER = ("#185C94", "#2F7DC4")
BG = ("#F5F5F3", "#1C1C1C")
PANEL = ("#FFFFFF", "#262626")
PANEL2 = ("#ECECE8", "#2F2F2F")
LINE = ("#D9D9D4", "#3D3D3D")
TX = ("#1A1A1A", "#F2F2F2")
SUB = ("#5C5C5C", "#B5B5B5")
PH = ("#E6E6E1", "#333333")
CHIP_ON = ("#DCEBFA", "#1E3F63")
CHIP_ON_TX = ("#0C447C", "#D6E8FB")
OK_BG, OK_TX = ("#E3F2E1", "#1F3D22"), ("#1B5E20", "#A8DDA9")
WARN_BG, WARN_TX = ("#FFF1CC", "#4A3A10"), ("#7A4F01", "#F2D58A")
UNK_BG, UNK_TX = ("#EEEEEE", "#3A3A3A"), ("#555555", "#CCCCCC")
DANGER = ("#B3261E", "#F28B82")

CJK = re.compile(r"[㐀-鿿＀-￯]")


def F(size, bold=False, italic=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal",
                       slant="italic" if italic else "roman")


def data_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "ClassicPhotoSearch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_download_dir():
    return str(Path.home() / "Pictures" / "經典圖庫")


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def classify(text):
    t = (text or "").lower()
    if t in ("free", "免費可用"):
        return ("免費可用", True, "ok")
    if not t:
        return ("權利請看出處頁", False, "unk")
    if "cc0" in t or "/zero/" in t:
        return ("CC0 可自由使用", True, "ok")
    if "public domain" in t or t in ("pd", "pdm") or t.startswith("pd-") or "publicdomain" in t:
        return ("公有領域", True, "ok")
    if "by" in t:
        return ("需標示作者", False, "warn")
    return ("權利請看出處頁", False, "unk")


def short(text, max_em):
    """依字寬截斷：中文算 1，英數算 0.55。"""
    out, w = "", 0.0
    for ch in text:
        cw = 1.0 if CJK.match(ch) else 0.56
        if w + cw > max_em:
            return out.rstrip() + "…"
        out += ch
        w += cw
    return out


def rounded(img, bg, r):
    """圖片四角做成圓角，角落填卡片底色。"""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], r, fill=255)
    out = Image.new("RGB", img.size, bg)
    out.paste(img, (0, 0), mask)
    return out


class Item:
    FIELDS = ("key", "source", "title", "thumb", "full", "page", "creator",
              "lic", "free", "level", "size", "dl_ping")

    def __init__(self, source, ident, title, thumb, full, page, creator,
                 lic_text, size="", dl_ping=None):
        self.source = source
        self.key = f"{source}:{ident}"
        t = (title or "").strip()
        self.title = (t[:1].upper() + t[1:])[:120] if t else "未命名"
        self.thumb, self.full, self.page = thumb, full, page
        self.creator = strip_html(creator)[:60]
        self.lic, self.free, self.level = classify(lic_text)
        self.size = size
        self.dl_ping = dl_ping

    def to_dict(self):
        return {k: getattr(self, k) for k in self.FIELDS}

    @classmethod
    def from_dict(cls, d):
        it = cls.__new__(cls)
        for k in cls.FIELDS:
            setattr(it, k, d.get(k))
        return it


# ---------------------------------------------------------------- 各來源
def http_json(url, params=None, headers=None, timeout=20):
    h = dict(UA)
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def src_pexels(q, page, key):
    d = http_json("https://api.pexels.com/v1/search",
                  {"query": q, "per_page": PER_FETCH, "page": page},
                  {"Authorization": key})
    out = []
    for p in d.get("photos", []):
        src = p.get("src") or {}
        out.append(Item("pexels", p.get("id"), p.get("alt") or q,
                        src.get("medium") or src.get("large"),
                        src.get("original") or src.get("large2x"),
                        p.get("url"), p.get("photographer"), "free",
                        f"{p.get('width')} × {p.get('height')}"))
    return out


def src_unsplash(q, page, key):
    d = http_json("https://api.unsplash.com/search/photos",
                  {"query": q, "per_page": PER_FETCH, "page": page},
                  {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"})
    out = []
    for p in d.get("results", []):
        urls = p.get("urls") or {}
        links = p.get("links") or {}
        out.append(Item("unsplash", p.get("id"),
                        p.get("alt_description") or p.get("description") or q,
                        urls.get("small") or urls.get("regular"),
                        urls.get("full") or urls.get("raw"),
                        links.get("html"), (p.get("user") or {}).get("name"), "free",
                        f"{p.get('width')} × {p.get('height')}",
                        dl_ping=links.get("download_location")))
    return out


def src_pixabay(q, page, key):
    d = http_json("https://pixabay.com/api/",
                  {"key": key, "q": q[:100], "image_type": "photo",
                   "per_page": PER_FETCH, "page": page, "safesearch": "true"})
    out = []
    for p in d.get("hits", []):
        tags = (p.get("tags") or "").split(",")[0].strip()
        out.append(Item("pixabay", p.get("id"), tags or q,
                        p.get("webformatURL") or p.get("previewURL"),
                        p.get("largeImageURL") or p.get("webformatURL"),
                        p.get("pageURL"), p.get("user"), "free",
                        f"{p.get('imageWidth')} × {p.get('imageHeight')}"))
    return out


def src_openverse(q, page, key):
    d = http_json("https://api.openverse.org/v1/images/",
                  {"q": q, "page": page, "page_size": PER_FETCH, "license": "cc0,pdm"})
    out = []
    for r in d.get("results", []):
        lic = "public domain" if r.get("license") == "pdm" else "cc0"
        size = f"{r.get('width')} × {r.get('height')}" if r.get("width") else ""
        out.append(Item("openverse", r.get("id"), r.get("title"),
                        r.get("thumbnail") or r.get("url"), r.get("url"),
                        r.get("foreign_landing_url"), r.get("creator"), lic, size))
    return out


def src_commons(q, page, key):
    p = http_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6,
        "gsrlimit": PER_FETCH, "gsroffset": (page - 1) * PER_FETCH,
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 500})
    pages = sorted((p.get("query", {}).get("pages", {}) or {}).values(),
                   key=lambda x: x.get("index", 0))
    out = []
    for pg in pages:
        ii = (pg.get("imageinfo") or [{}])[0]
        if not ii.get("url"):
            continue
        meta = ii.get("extmetadata", {})
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        title = re.sub(r"\.(jpe?g|png|tiff?|gif|webp)$", "",
                       pg.get("title", "").replace("File:", ""), flags=re.I)
        out.append(Item("commons", pg.get("pageid"), title,
                        ii.get("thumburl") or ii["url"], ii["url"],
                        ii.get("descriptionurl"),
                        (meta.get("Artist", {}) or {}).get("value", ""), lic,
                        f"{ii.get('width')} × {ii.get('height')}"))
    return out


MOCK_WORDS = ["海景飯店大廳", "Hotel swimming pool at sunset", "飯店客房", "城市夜景",
              "Luxury resort entrance with palm trees", "飯店餐廳"]


def make_mock(source):
    def fn(q, page, key):
        out = []
        for i in range(PER_FETCH):
            n = (page - 1) * PER_FETCH + i
            out.append(Item(source, n, MOCK_WORDS[n % len(MOCK_WORDS)], "mock", "mock",
                            "https://example.com", "測試攝影師", "free", "6000 × 4000"))
        return out
    return fn


# key, 名稱, 函式, 需要金鑰, 預設勾選, 是否在「更多來源」
SOURCES = [
    ("pexels", "Pexels", src_pexels, True, True, False),
    ("unsplash", "Unsplash", src_unsplash, True, True, False),
    ("pixabay", "Pixabay", src_pixabay, True, True, False),
    ("commons", "維基共享資源", src_commons, False, False, True),
]
if MOCK:
    SOURCES = [(k, n, make_mock(k), False, d, x) for k, n, _, _, d, x in SOURCES]
SRC_NAME = {s[0]: s[1] for s in SOURCES}

KEY_INFO = [
    ("pexels", "Pexels", "https://www.pexels.com/api/",
     "登入後按「Your API Key」，複製那串金鑰"),
    ("unsplash", "Unsplash", "https://unsplash.com/oauth/applications",
     "按「New Application」建立，複製「Access Key」"),
    ("pixabay", "Pixabay", "https://pixabay.com/api/docs/",
     "登入後在頁面中段的「key」欄位就是金鑰"),
]


def test_key(src, key):
    fn = {"pexels": src_pexels, "unsplash": src_unsplash, "pixabay": src_pixabay}[src]
    fn("hotel", 1, key)


# ---------------------------------------------------------------- 翻譯
def translate_zh_en(text):
    if MOCK:
        return "hotel"
    try:
        d = http_json("https://translate.googleapis.com/translate_a/single", {
            "client": "gtx", "sl": "zh-TW", "tl": "en", "dt": "t", "q": text}, timeout=10)
        s = "".join(seg[0] for seg in d[0] if seg and seg[0]).strip()
        if s:
            return s
    except Exception:
        pass
    d = http_json("https://api.mymemory.translated.net/get",
                  {"q": text, "langpair": "zh-TW|en"}, timeout=10)
    s = (d.get("responseData") or {}).get("translatedText", "").strip()
    if not s:
        raise RuntimeError("翻譯失敗")
    return s


# ---------------------------------------------------------------- 主程式
class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(8)
        self.settings = self.load_json("settings.json", {})
        self.keys = self.settings.setdefault("keys", {})
        self.favs = {d["key"]: Item.from_dict(d) for d in self.load_json("favorites.json", [])}
        self.results, self.seen = [], set()
        self.fetch_page, self.page = 0, 0
        self.checked = {}
        self.current = None
        self.pil = {}             # key -> PIL 縮圖
        self.loading = set()
        self.mode = "search"      # search / favs / settings
        self.query_en = ""
        self.searching = False
        self.more_open = False
        self.card_size = (300, 200)
        self._resize_job = None
        self.ph_img = None

        root.title(f"{APP_NAME} {VERSION}")
        root.geometry("1200x900")
        root.minsize(1000, 700)
        root.configure(fg_color=BG)
        self.build()
        self.root.after(100, self.poll)
        self.show_mode("search")
        if not MOCK and not any(self.keys.get(k) for k, *_ in KEY_INFO):
            self.set_status("第一次使用：請先按右上方「設定」，貼上免費圖庫的金鑰")

    # ---------- 存檔
    def load_json(self, name, default):
        try:
            return json.loads((data_dir() / name).read_text("utf-8"))
        except Exception:
            return default

    def save_json(self, name, obj):
        try:
            (data_dir() / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass

    def save_settings(self):
        self.settings["sources"] = [k for k, v in self.src_on.items() if v]
        self.save_json("settings.json", self.settings)

    def save_favs(self):
        self.save_json("favorites.json", [x.to_dict() for x in self.favs.values()])

    # ---------- 介面
    def btn(self, parent, text, cmd, primary=False, width=0, size=16):
        kw = dict(text=text, command=cmd, font=F(size, bold=primary), height=40,
                  corner_radius=8)
        if width:
            kw["width"] = width
        if primary:
            kw.update(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF")
        else:
            kw.update(fg_color=PANEL, hover_color=PANEL2, text_color=TX,
                      border_width=1, border_color=LINE)
        return ctk.CTkButton(parent, **kw)

    def build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(4, weight=1)

        head = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0, height=64)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text=APP_NAME, font=F(24, bold=True), text_color=TX
                     ).grid(row=0, column=0, padx=24, pady=10, sticky="w")
        self.status = ctk.CTkLabel(head, text="輸入關鍵字後按 Enter 搜尋", font=F(15),
                                   text_color=SUB, anchor="w")
        self.status.grid(row=0, column=1, sticky="ew", padx=10)
        ctk.CTkLabel(head, text=f"{AUTHOR}　{VERSION}", font=F(17, italic=True),
                     text_color=GOLD).grid(row=0, column=2, padx=24, sticky="e")

        # 搜尋（中文、英文、搜尋鈕同一行）
        s = ctk.CTkFrame(r, fg_color="transparent")
        s.grid(row=1, column=0, sticky="ew", padx=24, pady=(14, 0))
        s.grid_columnconfigure(0, weight=3)
        s.grid_columnconfigure(2, weight=2)
        self.q_entry = ctk.CTkEntry(s, font=F(20), height=50, corner_radius=10,
                                    border_width=1, border_color=LINE, fg_color=PANEL,
                                    text_color=TX, placeholder_text="輸入中文或英文，例如：海邊飯店")
        self.q_entry.grid(row=0, column=0, sticky="ew")
        self.q_entry.bind("<Return>", lambda e: self.start_search(False))
        ctk.CTkLabel(s, text="英文", font=F(16), text_color=SUB
                     ).grid(row=0, column=1, padx=(14, 8))
        self.en_entry = ctk.CTkEntry(s, font=F(18), height=50, corner_radius=10,
                                     border_width=1, border_color=LINE, fg_color=PANEL,
                                     text_color=TX, placeholder_text="自動翻譯，可修改後按 Enter")
        self.en_entry.grid(row=0, column=2, sticky="ew")
        self.en_entry.bind("<Return>", lambda e: self.start_search(True))
        ctk.CTkButton(s, text="搜尋", font=F(20, bold=True), height=50, width=120,
                      corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self.start_search(False)
                      ).grid(row=0, column=3, padx=(12, 0))

        # 來源
        src = ctk.CTkFrame(r, fg_color="transparent")
        src.grid(row=2, column=0, sticky="ew", padx=24, pady=(12, 0))
        ctk.CTkLabel(src, text="來源", font=F(16), text_color=SUB).pack(side="left", padx=(2, 10))
        saved = self.settings.get("sources")
        self.src_on, self.chips = {}, {}
        for k, name, fn, need, default, extra in SOURCES:
            self.src_on[k] = (k in saved) if saved is not None else default
            b = ctk.CTkButton(src, text=name, font=F(16), height=38, corner_radius=19,
                              border_width=1, command=lambda k=k: self.toggle_src(k))
            self.chips[k] = (b, extra)
        self.more_btn = ctk.CTkButton(src, text="更多來源 ▾", font=F(16), height=38, width=120,
                                      corner_radius=19, fg_color="transparent",
                                      hover_color=PANEL2, text_color=SUB,
                                      command=self.toggle_more)
        self.src_frame = src
        self.btn(src, "設定", lambda: self.show_mode("settings"), width=86).pack(side="right")
        self.btn(src, "開啟下載資料夾", self.open_folder, width=150).pack(side="right", padx=8)
        self.b_view = self.btn(src, "我的收藏（0）", self.toggle_favs, width=150)
        self.b_view.pack(side="right")
        self.layout_chips()

        # 內容區（圖片牆 / 設定）
        self.content = ctk.CTkFrame(r, fg_color="transparent")
        self.content.grid(row=4, column=0, sticky="nsew", padx=18, pady=(10, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.grid_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        for c in range(3):
            self.grid_frame.grid_columnconfigure(c, weight=1, uniform="c")
        for rr in range(2):
            self.grid_frame.grid_rowconfigure(rr, weight=1, uniform="r")
        self.cards = [self.make_card(i) for i in range(PER_PAGE)]
        self.empty_lbl = ctk.CTkLabel(self.content, text="", font=F(18), text_color=SUB)
        self.grid_frame.bind("<Configure>", self.on_resize)
        self.settings_frame = self.build_settings(self.content)

        # 動作列（勾選後的批次動作 + 換頁）
        bar = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
        bar.grid(row=5, column=0, sticky="ew", padx=24, pady=(8, 0))
        self.toolbar = bar
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)
        self.b_all = self.btn(inner, "全選本頁", self.check_page, width=110)
        self.b_none = self.btn(inner, "全部取消", self.uncheck_all, width=110)
        self.b_dl = self.btn(inner, "下載已勾選（0）", self.download_checked, primary=True, width=190)
        self.b_fav = self.btn(inner, "收藏已勾選", self.fav_checked, width=120)
        self.b_unfav = self.btn(inner, "移除已勾選收藏", self.unfav_checked, width=150)
        for b in (self.b_all, self.b_none, self.b_dl, self.b_fav):
            b.pack(side="left", padx=4)
        self.b_next = self.btn(inner, "下一頁", self.next_page, width=96)
        self.b_next.pack(side="right", padx=4)
        self.page_lbl = ctk.CTkLabel(inner, text="", font=F(16), text_color=TX, width=170)
        self.page_lbl.pack(side="right")
        self.b_prev = self.btn(inner, "上一頁", self.prev_page, width=96)
        self.b_prev.pack(side="right", padx=4)
        self.pager = bar

        # 詳細資訊（一行）
        det = ctk.CTkFrame(r, fg_color="transparent")
        det.grid(row=6, column=0, sticky="ew", padx=24, pady=(8, 12))
        self.detail = det
        det.grid_columnconfigure(1, weight=1)
        self.det_title = ctk.CTkLabel(det, text="點一下圖片看資訊，按兩下看大圖",
                                      font=F(17, bold=True), text_color=TX, anchor="w")
        self.det_title.grid(row=0, column=0, sticky="w", padx=(4, 14))
        self.det_info = ctk.CTkLabel(det, text="", font=F(15), text_color=SUB, anchor="w")
        self.det_info.grid(row=0, column=1, sticky="ew")
        bb = ctk.CTkFrame(det, fg_color="transparent")
        bb.grid(row=0, column=2)
        self.btn(bb, "出處頁", self.open_page, width=90).pack(side="left", padx=4)
        self.btn(bb, "收藏", lambda: self.add_favs([self.current]), width=80).pack(side="left", padx=4)
        self.btn(bb, "下載這張", lambda: self.download_items([self.current]),
                 primary=True, width=120).pack(side="left", padx=(4, 0))


    def layout_chips(self):
        for k, (b, extra) in self.chips.items():
            b.pack_forget()
        self.more_btn.pack_forget()
        for k, (b, extra) in self.chips.items():
            if not extra or self.more_open or self.src_on[k]:
                b.pack(side="left", padx=4)
        self.more_btn.configure(text="收起 ▴" if self.more_open else "更多來源 ▾")
        self.more_btn.pack(side="left", padx=4)
        self.paint_chips()

    def paint_chips(self):
        for k, (b, extra) in self.chips.items():
            on = self.src_on[k]
            name = SRC_NAME[k]
            b.configure(text=("✓ " + name) if on else name,
                        fg_color=CHIP_ON if on else PANEL,
                        text_color=CHIP_ON_TX if on else SUB,
                        border_color=CHIP_ON if on else LINE,
                        hover_color=CHIP_ON if on else PANEL2)

    def toggle_src(self, k):
        self.src_on[k] = not self.src_on[k]
        self.save_settings()
        self.paint_chips()

    def toggle_more(self):
        self.more_open = not self.more_open
        self.layout_chips()

    def make_card(self, i):
        f = ctk.CTkFrame(self.grid_frame, fg_color=PANEL, corner_radius=14,
                         border_width=1, border_color=LINE)
        f.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(0, weight=1)
        f.grid_propagate(False)
        img = ctk.CTkLabel(f, text="", fg_color="transparent", cursor="hand2")
        img.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 4))
        var = tk.BooleanVar()
        cb = ctk.CTkCheckBox(f, text="", variable=var, font=F(17, bold=True), text_color=TX,
                             checkbox_width=26, checkbox_height=26, corner_radius=6,
                             fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=SUB)
        cb.grid(row=1, column=0, sticky="w", padx=12)
        meta = ctk.CTkFrame(f, fg_color="transparent")
        meta.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 10))
        src = ctk.CTkLabel(meta, text="", font=F(15), text_color=SUB)
        src.pack(side="left")
        badge = ctk.CTkLabel(meta, text="", font=F(14), corner_radius=6, height=26)
        badge.pack(side="right")
        card = {"frame": f, "img": img, "var": var, "cb": cb, "src": src,
                "badge": badge, "item": None, "shown": None}
        for w in (img,):
            w.bind("<Button-1>", lambda e, c=card: self.select(c["item"]))
            w.bind("<Double-Button-1>", lambda e, c=card: self.preview(c["item"]))
        cb.configure(command=lambda c=card: self.on_check(c))
        return card

    def build_settings(self, parent):
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14, border_width=1, border_color=LINE)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="設定", font=F(22, bold=True), text_color=TX
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=24, pady=(20, 4))
        self.btn(f, "回到搜尋", lambda: self.show_mode("search"), primary=True, width=130
                 ).grid(row=0, column=3, sticky="e", padx=24, pady=(20, 4))
        ctk.CTkLabel(f, text="三個圖庫都可以免費申請金鑰：按「申請金鑰」→ 用 Email 註冊 → 複製金鑰貼到格子裡按 Enter",
                     font=F(15), text_color=SUB, anchor="w"
                     ).grid(row=1, column=0, columnspan=4, sticky="w", padx=24, pady=(0, 14))
        self.key_entries, self.key_status = {}, {}
        row = 2
        for k, name, url, hint in KEY_INFO:
            ctk.CTkLabel(f, text=name, font=F(18, bold=True), text_color=TX, width=110, anchor="w"
                         ).grid(row=row, column=0, sticky="w", padx=(24, 8), pady=(8, 0))
            e = ctk.CTkEntry(f, font=F(16), height=40, corner_radius=8, border_width=1,
                             border_color=LINE, fg_color=BG, text_color=TX,
                             placeholder_text="貼上金鑰後按 Enter")
            if self.keys.get(k):
                e.insert(0, self.keys[k])
            e.grid(row=row, column=1, sticky="ew", pady=(8, 0))
            e.bind("<Return>", lambda ev, k=k: self.save_key(k, move=True))
            e.bind("<FocusOut>", lambda ev, k=k: self.save_key(k, move=False))
            self.key_entries[k] = e
            self.btn(f, "申請金鑰", lambda u=url: webbrowser.open(u), width=110
                     ).grid(row=row, column=2, padx=10, pady=(8, 0))
            st = ctk.CTkLabel(f, text="", font=F(15, bold=True), width=110, anchor="w")
            st.grid(row=row, column=3, sticky="w", padx=(0, 24), pady=(8, 0))
            self.key_status[k] = st
            ctk.CTkLabel(f, text=hint, font=F(14), text_color=SUB, anchor="w"
                         ).grid(row=row + 1, column=1, columnspan=3, sticky="w", pady=(2, 4))
            row += 2
            self.paint_key_status(k)
        ctk.CTkFrame(f, height=1, fg_color=LINE).grid(row=row, column=0, columnspan=4,
                                                       sticky="ew", padx=24, pady=16)
        row += 1
        ctk.CTkLabel(f, text="下載資料夾", font=F(18, bold=True), text_color=TX, anchor="w"
                     ).grid(row=row, column=0, sticky="w", padx=(24, 8))
        self.folder_lbl = ctk.CTkLabel(f, text=self.folder(), font=F(16), text_color=TX, anchor="w")
        self.folder_lbl.grid(row=row, column=1, sticky="ew")
        self.btn(f, "變更", self.choose_folder, width=110).grid(row=row, column=2, padx=10)
        ctk.CTkLabel(f, text="", height=12).grid(row=row + 1, column=0)
        return f

    def paint_key_status(self, k, state=None):
        st = self.key_status[k]
        if state == "testing":
            st.configure(text="檢查中…", text_color=SUB)
        elif state == "bad":
            st.configure(text="✗ 金鑰錯誤", text_color=DANGER)
        elif state == "neterr":
            st.configure(text="連不上，稍後再試", text_color=SUB)
        elif self.keys.get(k):
            st.configure(text="✓ 可以用", text_color=OK_TX)
        else:
            st.configure(text="未設定", text_color=SUB)

    def save_key(self, k, move):
        e = self.key_entries[k]
        val = e.get().strip()
        if move:
            order = [x[0] for x in KEY_INFO]
            nxt = order[(order.index(k) + 1) % len(order)]
            self.key_entries[nxt].focus_set()
        if val == self.keys.get(k, "") and not move:
            return
        if not val:
            self.keys.pop(k, None)
            self.save_settings()
            self.paint_key_status(k)
            return
        e.configure(border_color=LINE)
        self.paint_key_status(k, "testing")

        def job():
            try:
                if not MOCK:
                    test_key(k, val)
                self.q.put(("key_ok", k, val))
            except requests.HTTPError as ex:
                code = ex.response.status_code if ex.response is not None else 0
                self.q.put(("key_bad" if code in (400, 401, 403) else "key_net", k, val))
            except Exception:
                self.q.put(("key_net", k, val))
        threading.Thread(target=job, daemon=True).start()

    # ---------- 模式切換
    def show_mode(self, mode):
        self.mode = mode
        self.page = 0 if mode != "search" or not self.results else self.page
        self.grid_frame.grid_forget()
        self.settings_frame.grid_forget()
        self.empty_lbl.grid_forget()
        if mode == "settings":
            self.settings_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            for w in (self.toolbar, self.detail):
                w.grid_remove()
        else:
            for w in (self.toolbar, self.detail):
                w.grid()
            self.grid_frame.grid(row=0, column=0, sticky="nsew")
            self.render()

    def toggle_favs(self):
        self.checked.clear()
        self.page = 0
        self.show_mode("search" if self.mode == "favs" else "favs")

    # ---------- 顯示
    def items_view(self):
        return list(self.favs.values()) if self.mode == "favs" else self.results

    def on_resize(self, event):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self.apply_resize)

    def scale(self):
        try:
            return ctk.ScalingTracker.get_widget_scaling(self.grid_frame)
        except Exception:
            return 1.0

    def apply_resize(self):
        self._resize_job = None
        s = self.scale()
        w = self.grid_frame.winfo_width() / s
        h = self.grid_frame.winfo_height() / s
        cw = max(160, w / 3 - 12)
        ch = max(170, h / 2 - 12)
        self.card_size = (int(cw - 20), int(max(80, ch - 98)))
        for c in self.cards:
            c["shown"] = None
        self.render()

    def render(self):
        if self.mode == "settings":
            return
        items = self.items_view()
        start = self.page * PER_PAGE
        page_items = items[start:start + PER_PAGE]
        tw, th = self.card_size
        max_em = max(6, (tw - 30) / 17)
        for i, card in enumerate(self.cards):
            it = page_items[i] if i < len(page_items) else None
            card["item"] = it
            f = card["frame"]
            if not it:
                f.grid_remove()
                continue
            f.grid()
            card["var"].set(it.key in self.checked)
            card["cb"].configure(text=short(it.title, max_em))
            card["src"].configure(text=SRC_NAME.get(it.source, it.source))
            bg, fg = {"ok": (OK_BG, OK_TX), "warn": (WARN_BG, WARN_TX)}.get(it.level, (UNK_BG, UNK_TX))
            card["badge"].configure(text=f"  {it.lic}  ", fg_color=bg, text_color=fg)
            sel = it is self.current
            f.configure(border_color=ACCENT if sel else LINE, border_width=3 if sel else 1)
            self.show_thumb(card)
        n_pages = max(1, -(-len(items) // PER_PAGE))
        more = "+" if self.mode == "search" and self.results else ""
        self.page_lbl.configure(text=f"第 {self.page + 1} 頁 / 共 {n_pages}{more} 頁")
        self.b_dl.configure(text=f"下載已勾選（{len(self.checked)}）")
        if self.mode == "favs":
            self.b_fav.pack_forget()
            self.b_unfav.pack(side="left", padx=4, after=self.b_dl)
            self.b_view.configure(text="回到搜尋結果")
        else:
            self.b_unfav.pack_forget()
            self.b_fav.pack(side="left", padx=4, after=self.b_dl)
            self.b_view.configure(text=f"我的收藏（{len(self.favs)}）")
        if not page_items:
            msg = ("收藏是空的。勾選圖片後按「收藏已勾選」，就會出現在這裡。"
                   if self.mode == "favs" else
                   ("搜尋中…" if self.searching else "輸入關鍵字，按 Enter 開始搜尋"))
            self.empty_lbl.configure(text=msg)
            self.empty_lbl.grid(row=0, column=0)
        else:
            self.empty_lbl.grid_forget()

    def show_thumb(self, card):
        it = card["item"]
        tw, th = self.card_size
        sig = (it.key, tw, th)
        if card["shown"] == sig:
            return
        pil = self.pil.get(it.key)
        if pil is None:
            card["img"].configure(image=self.placeholder(tw, th))
            card["shown"] = None
            self.load_thumb(it)
            return
        s = self.scale()
        size = (max(1, int(tw * s)), max(1, int(th * s)))
        fitted = ImageOps.fit(pil, size, Image.LANCZOS)
        im = ctk.CTkImage(light_image=rounded(fitted, PANEL[0], int(10 * s)),
                          dark_image=rounded(fitted, PANEL[1], int(10 * s)), size=(tw, th))
        card["img"].configure(image=im)
        card["img"]._keep = im
        card["shown"] = sig

    def placeholder(self, tw, th):
        key = (tw, th)
        if not self.ph_img or self.ph_img[0] != key:
            s = self.scale()
            sz = (max(1, int(tw * s)), max(1, int(th * s)))
            l = rounded(Image.new("RGB", sz, PH[0]), PANEL[0], int(10 * s))
            d = rounded(Image.new("RGB", sz, PH[1]), PANEL[1], int(10 * s))
            self.ph_img = (key, ctk.CTkImage(light_image=l, dark_image=d, size=(tw, th)))
        return self.ph_img[1]

    def load_thumb(self, it):
        if it.key in self.loading:
            return
        self.loading.add(it.key)

        def job():
            try:
                if MOCK or it.thumb == "mock":
                    colors = ["#B9A88E", "#8FA9BF", "#A7B98F", "#C4A9A0", "#9DA6B8", "#B7AE8F"]
                    im = Image.new("RGB", (800, 530), colors[hash(it.key) % 6])
                    dr = ImageDraw.Draw(im)
                    dr.ellipse([560, 70, 680, 190], fill="#F2E3B3")
                    dr.polygon([(0, 530), (260, 250), (470, 530)], fill="#6F7F63")
                    dr.polygon([(300, 530), (560, 300), (800, 530)], fill="#58684F")
                else:
                    r = requests.get(it.thumb, headers=UA, timeout=25)
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.thumbnail((900, 900))
                self.q.put(("thumb", it.key, im))
            except Exception:
                self.q.put(("thumbfail", it.key, None))
        self.pool.submit(job)

    # ---------- 背景 → 主執行緒
    def poll(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "thumb":
                    self.pil[a] = b
                    for c in self.cards:
                        if c["item"] and c["item"].key == a:
                            self.show_thumb(c)
                elif kind == "thumbfail":
                    self.loading.discard(a)
                elif kind == "translated":
                    self.en_entry.delete(0, "end")
                    if a:
                        self.en_entry.insert(0, a)
                elif kind == "results":
                    self.merge_results(a, b)
                elif kind == "status":
                    self.set_status(a)
                elif kind == "done_download":
                    self.after_download(a, b)
                elif kind == "key_ok":
                    self.keys[a] = b
                    self.save_settings()
                    self.paint_key_status(a)
                    self.key_entries[a].configure(border_color=LINE)
                elif kind == "key_bad":
                    self.paint_key_status(a, "bad")
                    self.key_entries[a].configure(border_color=DANGER)
                elif kind == "key_net":
                    self.paint_key_status(a, "neterr")
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_status(self, s):
        self.status.configure(text=s)

    # ---------- 搜尋
    def active_sources(self):
        return [s for s in SOURCES if self.src_on[s[0]]]

    def start_search(self, from_en):
        if self.searching:
            return
        text = self.q_entry.get().strip()
        en = self.en_entry.get().strip()
        if from_en and not en:
            from_en = False
        if not text and not en:
            self.set_status("請先輸入關鍵字")
            return
        if not text:
            from_en = True
        srcs = self.active_sources()
        if not srcs:
            self.set_status("請至少選一個來源")
            return
        self.mode = "search"
        self.show_mode("search")
        self.results, self.seen, self.page, self.fetch_page = [], set(), 0, 0
        self.current = None
        self.searching = True
        self.render()
        self.set_status("搜尋中…")

        def job():
            q_en = en if from_en else text
            if not from_en:
                if CJK.search(text):
                    self.q.put(("status", "翻譯成英文中…", None))
                    try:
                        q_en = translate_zh_en(text)
                    except Exception:
                        q_en = text
                        self.q.put(("status", "翻譯失敗，先用中文搜尋；也可以自己在英文欄輸入", None))
                self.q.put(("translated", q_en, None))
            self.query_en = q_en
            self.fetch_more_sync(srcs)
        threading.Thread(target=job, daemon=True).start()

    def fetch_more_sync(self, srcs):
        self.fetch_page += 1
        page = self.fetch_page
        nokey, jobs = [], []
        for k, name, fn, need, d, x in srcs:
            key = self.keys.get(k, "")
            if need and not key:
                nokey.append(name)
                continue
            jobs.append((name, fn, key))

        def run(j):
            name, fn, key = j
            try:
                return name, fn(self.query_en, page, key), None
            except Exception as ex:
                return name, [], str(ex)
        per_src, errors = [], []
        with ThreadPoolExecutor(6) as ex:
            for name, items, err in ex.map(run, jobs):
                per_src.append(items)
                if err:
                    errors.append(name)
        merged, i = [], 0
        while any(i < len(l) for l in per_src):
            for l in per_src:
                if i < len(l):
                    merged.append(l[i])
            i += 1
        self.q.put(("results", merged, (errors, nokey)))

    def merge_results(self, items, info):
        errors, nokey = info
        self.searching = False
        new = [x for x in items if x.key not in self.seen and x.full]
        for x in new:
            self.seen.add(x.key)
        self.results.extend(new)
        parts = [f"找到 {len(self.results)} 張"] if self.results else ["沒有找到，可以換個關鍵字試試"]
        if nokey:
            parts.append(f"{'、'.join(nokey)} 還沒設定金鑰（按「設定」）")
        if errors:
            parts.append(f"連不上：{'、'.join(errors)}")
        self.set_status("。".join(parts))
        self.render()

    def next_page(self):
        items = self.items_view()
        if (self.page + 1) * PER_PAGE < len(items):
            self.page += 1
            self.render()
            if self.mode == "search" and (self.page + 2) * PER_PAGE >= len(items):
                self.load_more()
        elif self.mode == "search" and self.results:
            self.load_more(advance=True)

    def load_more(self, advance=False):
        if self.searching:
            return
        self.searching = True
        before = len(self.results)
        srcs = self.active_sources()
        threading.Thread(target=lambda: self.fetch_more_sync(srcs), daemon=True).start()
        if advance:
            self.set_status("載入更多…")

            def wait():
                if self.searching:
                    self.root.after(200, wait)
                elif len(self.results) > before:
                    self.page += 1
                    self.render()
                else:
                    self.set_status("已經是最後一頁了")
            wait()

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.render()

    # ---------- 勾選與選取
    def on_check(self, card):
        it = card["item"]
        if not it:
            return
        if card["var"].get():
            self.checked[it.key] = it
        else:
            self.checked.pop(it.key, None)
        self.b_dl.configure(text=f"下載已勾選（{len(self.checked)}）")

    def check_page(self):
        for c in self.cards:
            if c["item"]:
                self.checked[c["item"].key] = c["item"]
        self.render()

    def uncheck_all(self):
        self.checked.clear()
        self.render()

    def select(self, it):
        if not it:
            return
        self.current = it
        self.det_title.configure(text=short(it.title, 30))
        info = [SRC_NAME.get(it.source, it.source)]
        if it.creator:
            info.append(f"攝影／作者：{it.creator}")
        if it.size and "None" not in it.size:
            info.append(it.size)
        info.append(it.lic)
        self.det_info.configure(text="　·　".join(info))
        self.render()

    def open_page(self):
        if self.current and self.current.page:
            webbrowser.open(self.current.page)

    def preview(self, it):
        if not it:
            return
        self.select(it)
        win = ctk.CTkToplevel(self.root)
        win.title(it.title)
        win.geometry("1100x800")
        win.configure(fg_color=BG)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(0, weight=1)
        lbl = ctk.CTkLabel(win, text="載入大圖中…", font=F(18), text_color=SUB)
        lbl.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        ctk.CTkLabel(win, text=short(it.title, 50) + "　·　" + it.lic, font=F(17), text_color=TX
                     ).grid(row=1, column=0, pady=(0, 14))
        win.after(200, win.lift)

        def job():
            try:
                if MOCK or it.full == "mock":
                    im = self.pil.get(it.key) or Image.new("RGB", (1200, 800), "#8FA9BF")
                else:
                    r = requests.get(it.full, headers=UA, timeout=60)
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im = im.copy()
                im.thumbnail((2000, 2000))

                def show():
                    if win.winfo_exists():
                        w, h = im.size
                        k = min(1060 / w, 700 / h, 1.0)
                        ci = ctk.CTkImage(light_image=im, dark_image=im,
                                          size=(int(w * k), int(h * k)))
                        lbl.configure(image=ci, text="")
                        lbl._keep = ci
                self.root.after(0, show)
            except Exception:
                self.root.after(0, lambda: win.winfo_exists() and lbl.configure(
                    text="大圖載入失敗，可以按「出處頁」在瀏覽器看"))
        threading.Thread(target=job, daemon=True).start()

    # ---------- 收藏
    def add_favs(self, items):
        items = [x for x in items if x]
        if not items:
            self.set_status("請先勾選或點選圖片")
            return
        for x in items:
            self.favs[x.key] = x
        self.save_favs()
        self.set_status(f"已收藏 {len(items)} 張")
        self.render()

    def fav_checked(self):
        self.add_favs(list(self.checked.values()))

    def unfav_checked(self):
        items = list(self.checked.values())
        if not items:
            self.set_status("請先勾選要移除的收藏")
            return
        if not messagebox.askyesno(APP_NAME, f"確定要從收藏移除 {len(items)} 張嗎？\n（已下載的檔案不會被刪除）"):
            return
        for x in items:
            self.favs.pop(x.key, None)
        self.checked.clear()
        self.save_favs()
        self.page = 0
        self.render()

    # ---------- 下載
    def folder(self):
        return self.settings.get("download_dir") or default_download_dir()

    def choose_folder(self):
        d = filedialog.askdirectory(initialdir=self.folder(), title="選擇下載資料夾")
        if d:
            self.settings["download_dir"] = d
            self.save_settings()
            self.folder_lbl.configure(text=d)

    def open_folder(self):
        d = self.folder()
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)
        except Exception:
            webbrowser.open(Path(d).as_uri())

    def download_checked(self):
        self.download_items(list(self.checked.values()))

    def download_items(self, items):
        items = [x for x in items if x]
        if not items:
            self.set_status("請先勾選要下載的圖片")
            return
        d = Path(self.folder())
        d.mkdir(parents=True, exist_ok=True)
        self.set_status(f"下載中 0 / {len(items)}…")
        keys = dict(self.keys)

        def job():
            ok, fail, rows = 0, 0, []
            for n, it in enumerate(items, 1):
                try:
                    if MOCK or it.full == "mock":
                        data, ext = b"mock", ".jpg"
                    else:
                        if it.source == "unsplash" and it.dl_ping and keys.get("unsplash"):
                            try:
                                requests.get(it.dl_ping, headers={
                                    **UA, "Authorization": f"Client-ID {keys['unsplash']}"}, timeout=15)
                            except Exception:
                                pass
                        r = requests.get(it.full, headers=UA, timeout=120)
                        r.raise_for_status()
                        data = r.content
                        ct = r.headers.get("Content-Type", "")
                        ext = ".png" if "png" in ct else ".webp" if "webp" in ct else ".jpg"
                        m = re.search(r"\.(jpe?g|png|webp|tiff?|gif)(?:$|\?)", it.full, re.I)
                        if m and "unsplash" not in it.source:
                            ext = "." + m.group(1).lower()
                    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", it.title)[:50].strip() or "image"
                    ident = re.sub(r"[^0-9A-Za-z_-]", "", it.key.split(":", 1)[1])[-16:]
                    fn = d / f"{safe}_{SRC_NAME.get(it.source, it.source)}_{ident}{ext}"
                    fn.write_bytes(data)
                    rows.append([fn.name, it.title, SRC_NAME.get(it.source, it.source),
                                 it.lic, it.creator, it.page or ""])
                    ok += 1
                except Exception:
                    fail += 1
                self.q.put(("status", f"下載中 {n} / {len(items)}…", None))
            if rows:
                credit = d / "出處紀錄.csv"
                new = not credit.exists()
                try:
                    with open(credit, "a", newline="", encoding="utf-8-sig") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(["檔名", "標題", "來源", "授權", "攝影／作者", "出處網址"])
                        w.writerows(rows)
                except Exception:
                    pass
            self.q.put(("done_download", ok, fail))
        threading.Thread(target=job, daemon=True).start()

    def after_download(self, ok, fail):
        self.set_status(f"下載完成：成功 {ok} 張" + (f"，失敗 {fail} 張" if fail else ""))
        self.checked.clear()
        self.render()
        if SMOKE:
            return
        msg = f"已下載 {ok} 張到：\n{self.folder()}"
        if fail:
            msg += f"\n\n有 {fail} 張下載失敗，可以稍後再試，或按「出處頁」手動下載。"
        msg += "\n\n每張的來源和攝影師記在資料夾裡的「出處紀錄.csv」。\n\n要開啟下載資料夾嗎？"
        if messagebox.askyesno(APP_NAME, msg):
            self.open_folder()


def smoke_run(root, app):
    """GitHub 編譯時自動操作並截圖，用來檢查排版。"""
    from PIL import ImageGrab
    out = Path("shots")
    out.mkdir(exist_ok=True)
    mode = os.environ.get("PHOTO_THEME", "light")

    def shot(name):
        root.update()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out / f"{name}_{mode}.png")

    def step1():
        app.q_entry.insert(0, "酒店")
        app.start_search(False)
        root.after(3500, step2)

    def step2():
        c = app.cards[0]
        c["var"].set(True)
        app.on_check(c)
        c = app.cards[1]
        c["var"].set(True)
        app.on_check(c)
        app.select(app.cards[0]["item"])
        root.after(1500, lambda: (shot("results"), step3()))

    def step3():
        app.show_mode("settings")
        root.after(1000, lambda: (shot("settings"), step4()))

    def step4():
        print("SMOKE results", len(app.results))
        root.destroy()
    root.after(1500, step1)


def main():
    theme = os.environ.get("PHOTO_THEME")
    ctk.set_appearance_mode(theme if theme else "system")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = App(root)
    if SMOKE:
        root.geometry("1280x720+0+0")
        smoke_run(root, app)
    else:
        try:
            root.after(50, lambda: root.state("zoomed"))
        except Exception:
            pass
    root.mainloop()


if __name__ == "__main__":
    main()
