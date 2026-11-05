# -*- coding: utf-8 -*-
"""經典圖庫搜尋 v0.1  作者:ArchieKUO
多來源免費經典圖片搜尋、勾選批次下載、收藏。
"""
import os
import re
import io
import csv
import sys
import json
import queue
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import requests
from PIL import Image, ImageTk, ImageDraw

APP_NAME = "經典圖庫搜尋"
VERSION = "v0.1"
AUTHOR = "作者:ArchieKUO"
GOLD = "#B8860B"
UA = {"User-Agent": "ClassicPhotoSearch/0.1 (personal desktop app)"}
PER_FETCH = 20
PER_PAGE = 6
THUMB_W, THUMB_H = 300, 190
MOCK = os.environ.get("PHOTO_MOCK") == "1"

FONT = "Microsoft JhengHei UI"
F_BIG = (FONT, 20)
F_MID = (FONT, 16)
F_MIDB = (FONT, 16, "bold")
F_SM = (FONT, 14)

CJK = re.compile(r"[㐀-鿿]")


def data_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "ClassicPhotoSearch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_download_dir():
    return str(Path.home() / "Pictures" / "經典圖庫")


# ---------------------------------------------------------------- 授權判斷
def classify(text):
    """回傳 (標籤, 是否可自由使用, 等級 ok/warn/unk)"""
    t = (text or "").lower()
    if not t:
        return ("權利請看出處頁", False, "unk")
    if "cc0" in t or "cc-zero" in t or "/zero/" in t:
        return ("CC0 可自由使用", True, "ok")
    if ("public domain" in t or t in ("pd", "pdm") or t.startswith("pd-")
            or "publicdomain" in t or "no known restrictions" in t
            or "公有領域" in t):
        return ("公有領域", True, "ok")
    if "by" in t and ("cc" in t or "creative" in t):
        return ("需標示作者", False, "warn")
    if t in ("by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd"):
        return ("需標示作者", False, "warn")
    return ("權利請看出處頁", False, "unk")


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


class Item:
    __slots__ = ("key", "source", "title", "thumb", "full", "page",
                 "creator", "lic", "free", "level", "resolver")

    def __init__(self, source, ident, title, thumb, full, page, creator,
                 lic_text, resolver=None):
        self.source = source
        self.key = f"{source}:{ident}"
        self.title = (title or "未命名").strip()[:120]
        self.thumb = thumb
        self.full = full
        self.page = page
        self.creator = strip_html(creator)[:80]
        self.lic, self.free, self.level = classify(lic_text)
        self.resolver = resolver

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__ if k != "resolver"}

    @classmethod
    def from_dict(cls, d):
        it = cls.__new__(cls)
        for k in cls.__slots__:
            setattr(it, k, d.get(k))
        it.resolver = None
        return it


# ---------------------------------------------------------------- 各來源
def http_json(url, params=None, timeout=20):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def src_commons(q, page, free_only):
    p = http_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{q} filetype:bitmap", "gsrnamespace": 6,
        "gsrlimit": PER_FETCH, "gsroffset": (page - 1) * PER_FETCH,
        "prop": "imageinfo", "iiprop": "url|extmetadata|size",
        "iiurlwidth": 400})
    pages = sorted((p.get("query", {}).get("pages", {}) or {}).values(),
                   key=lambda x: x.get("index", 0))
    out = []
    for pg in pages:
        ii = (pg.get("imageinfo") or [{}])[0]
        if not ii.get("url"):
            continue
        meta = ii.get("extmetadata", {})
        lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
        title = pg.get("title", "").replace("File:", "")
        title = re.sub(r"\.(jpe?g|png|tiff?|gif|webp)$", "", title, flags=re.I)
        out.append(Item("commons", pg.get("pageid"), title,
                        ii.get("thumburl") or ii["url"], ii["url"],
                        ii.get("descriptionurl"),
                        (meta.get("Artist", {}) or {}).get("value", ""), lic))
    return out


def src_openverse(q, page, free_only):
    params = {"q": q, "page": page, "page_size": PER_FETCH}
    if free_only:
        params["license"] = "cc0,pdm"
    d = http_json("https://api.openverse.org/v1/images/", params)
    out = []
    for r in d.get("results", []):
        lic = r.get("license", "")
        if lic == "pdm":
            lic = "public domain"
        elif lic != "cc0":
            lic = f"cc {lic}"
        out.append(Item("openverse", r.get("id"), r.get("title"),
                        r.get("thumbnail") or r.get("url"), r.get("url"),
                        r.get("foreign_landing_url"), r.get("creator"), lic))
    return out


def src_loc(q, page, free_only):
    d = http_json("https://www.loc.gov/photos/", {
        "q": q, "fo": "json", "c": PER_FETCH, "sp": page})
    out = []
    for r in d.get("results", []):
        imgs = [u.split("#")[0] for u in (r.get("image_url") or [])
                if isinstance(u, str)]
        imgs = [("https:" + u) if u.startswith("//") else u for u in imgs]
        if not imgs:
            continue
        thumb = imgs[min(1, len(imgs) - 1)]
        full = imgs[-1]
        m = re.match(r"(.*?)_150px\.jpg$", full)
        if m:
            thumb = m.group(1) + "r.jpg"
            full = m.group(1) + "v.jpg"
        rights = r.get("rights") or r.get("rights_advisory") or ""
        if isinstance(rights, list):
            rights = " ".join(map(str, rights))
        item = r.get("item") or {}
        if not rights and isinstance(item, dict):
            ra = item.get("rights_advisory") or item.get("rights") or ""
            rights = " ".join(ra) if isinstance(ra, list) else str(ra)
        title = r.get("title")
        if isinstance(title, list):
            title = title[0] if title else ""
        creator = ""
        if isinstance(item, dict):
            cr = item.get("creators") or item.get("contributors") or []
            if isinstance(cr, list) and cr:
                creator = cr[0] if isinstance(cr[0], str) else str(cr[0].get("title", ""))
        out.append(Item("loc", r.get("id") or full, title, thumb, full,
                        r.get("url") or r.get("id"), creator, rights))
    return out


_met_ids = {}


def src_met(q, page, free_only):
    if q not in _met_ids:
        d = http_json("https://collectionapi.metmuseum.org/public/collection/v1/search",
                      {"q": q, "hasImages": "true", "isPublicDomain": "true"})
        _met_ids[q] = d.get("objectIDs") or []
    ids = _met_ids[q][(page - 1) * PER_FETCH: page * PER_FETCH]

    def one(oid):
        try:
            o = http_json(f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{oid}")
        except Exception:
            return None
        if not o.get("primaryImage"):
            return None
        return Item("met", oid, o.get("title"),
                    o.get("primaryImageSmall") or o["primaryImage"],
                    o["primaryImage"], o.get("objectURL"),
                    o.get("artistDisplayName"),
                    "public domain" if o.get("isPublicDomain") else "")
    with ThreadPoolExecutor(8) as ex:
        return [x for x in ex.map(one, ids) if x]


def src_aic(q, page, free_only):
    params = {"q": q, "limit": PER_FETCH, "page": page,
              "fields": "id,title,image_id,is_public_domain,artist_display"}
    if free_only:
        params["query[term][is_public_domain]"] = "true"
    d = http_json("https://api.artic.edu/api/v1/artworks/search", params)
    base = (d.get("config") or {}).get("iiif_url") or "https://www.artic.edu/iiif/2"
    out = []
    for r in d.get("data", []):
        iid = r.get("image_id")
        if not iid:
            continue
        out.append(Item("aic", r.get("id"), r.get("title"),
                        f"{base}/{iid}/full/400,/0/default.jpg",
                        f"{base}/{iid}/full/1686,/0/default.jpg",
                        f"https://www.artic.edu/artworks/{r.get('id')}",
                        r.get("artist_display"),
                        "public domain" if r.get("is_public_domain") else ""))
    return out


def src_cleveland(q, page, free_only):
    params = {"q": q, "has_image": 1, "limit": PER_FETCH,
              "skip": (page - 1) * PER_FETCH}
    if free_only:
        params["cc0"] = 1
    d = http_json("https://openaccess-api.clevelandart.org/api/artworks/", params)
    out = []
    for r in d.get("data", []):
        im = r.get("images") or {}
        web = (im.get("web") or {}).get("url")
        full = (im.get("print") or {}).get("url") or (im.get("full") or {}).get("url") or web
        if not web:
            continue
        cr = r.get("creators") or []
        creator = cr[0].get("description", "") if cr and isinstance(cr[0], dict) else ""
        out.append(Item("cleveland", r.get("id"), r.get("title"), web, full,
                        r.get("url"), creator, r.get("share_license_status", "")))
    return out


def _ia_resolve(ident):
    d = http_json(f"https://archive.org/metadata/{ident}")
    best, size = None, -1
    for f in d.get("files", []):
        n = f.get("name", "")
        if not re.search(r"\.(jpe?g|png|tiff?)$", n, re.I):
            continue
        if "thumb" in n.lower() or f.get("source") == "derivative" and n.lower().endswith("_thumb.jpg"):
            continue
        s = int(f.get("size") or 0)
        if s > size and s < 60_000_000:
            best, size = n, s
    if not best:
        return f"https://archive.org/services/img/{ident}"
    return f"https://archive.org/download/{ident}/{requests.utils.quote(best)}"


def full_url(it):
    if it.full:
        return it.full
    if it.resolver:
        it.full = it.resolver()
    elif it.source == "archive":
        it.full = _ia_resolve(it.key.split(":", 1)[1])
    return it.full


def get_with_fallback(url, it, timeout):
    """國會圖書館的大圖有時沒有 v.jpg，改試 r.jpg 或原本的小圖。"""
    cands = [url]
    m = re.match(r"(.*?)[vr]\.jpg$", url or "")
    if it.source == "loc" and m:
        cands += [m.group(1) + "r.jpg", m.group(1) + "_150px.jpg"]
    last = None
    for u in dict.fromkeys(cands):
        try:
            r = requests.get(u, headers=UA, timeout=timeout)
            r.raise_for_status()
            if it.full == url and u != url and timeout > 20:
                it.full = u
            return r
        except Exception as ex:
            last = ex
    raise last


def src_archive(q, page, free_only):
    d = http_json("https://archive.org/advancedsearch.php", {
        "q": f"({q}) AND mediatype:image",
        "fl[]": ["identifier", "title", "creator", "licenseurl"],
        "rows": PER_FETCH, "page": page, "output": "json"})
    out = []
    for r in (d.get("response") or {}).get("docs", []):
        ident = r.get("identifier")
        if not ident:
            continue
        cr = r.get("creator")
        if isinstance(cr, list):
            cr = cr[0] if cr else ""
        title = r.get("title")
        if isinstance(title, list):
            title = title[0] if title else ""
        out.append(Item("archive", ident, title,
                        f"https://archive.org/services/img/{ident}", None,
                        f"https://archive.org/details/{ident}", cr,
                        r.get("licenseurl", ""),
                        resolver=lambda i=ident: _ia_resolve(i)))
    return out


def src_mock(q, page, free_only):
    out = []
    for i in range(PER_FETCH):
        n = (page - 1) * PER_FETCH + i
        lic = ["public domain", "cc0", "cc by", ""][n % 4]
        out.append(Item("mock", n, f"{q} 範例 {n + 1}", None, "mock",
                        "https://example.com", "測試作者", lic))
    return out


SOURCES = [
    # key, 顯示名稱, 函式, 是否支援中文, 分類
    ("loc", "國會圖書館", src_loc, False, "photo"),
    ("commons", "維基共享資源", src_commons, True, "both"),
    ("openverse", "Openverse", src_openverse, False, "photo"),
    ("aic", "芝加哥藝術館", src_aic, False, "art"),
    ("cleveland", "克里夫蘭藝術館", src_cleveland, False, "art"),
    ("archive", "Internet Archive", src_archive, False, "photo"),
]
if MOCK:
    SOURCES = [("mock", "測試來源", src_mock, True, "both")]
SRC_NAME = {k: n for k, n, *_ in SOURCES}
SRC_NAME.update({"loc": "國會圖書館", "commons": "維基共享資源", "openverse": "Openverse",
                 "met": "大都會博物館", "aic": "芝加哥藝術館",
                 "cleveland": "克里夫蘭藝術館", "archive": "Internet Archive",
                 "mock": "測試來源"})


# ---------------------------------------------------------------- 翻譯
def translate_zh_en(text):
    if MOCK:
        return "mock " + text
    try:
        d = http_json("https://translate.googleapis.com/translate_a/single", {
            "client": "gtx", "sl": "zh-TW", "tl": "en", "dt": "t", "q": text},
            timeout=10)
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
        self.favs = {d["key"]: Item.from_dict(d)
                     for d in self.load_json("favorites.json", [])}
        self.results = []
        self.seen = set()
        self.fetch_page = 0
        self.page = 0
        self.checked = {}          # key -> Item
        self.current = None
        self.thumbs = {}
        self.thumb_loading = set()
        self.view_favs = False
        self.query_en = ""
        self.query_zh = ""
        self.searching = False
        self.hidden_count = 0

        root.title(f"{APP_NAME} {VERSION}")
        root.geometry("1180x900")
        root.minsize(980, 760)
        root.configure(bg="#FFFFFF")
        self.build_ui()
        self.root.after(100, self.poll)
        self.render()

    # ---------- 存檔
    def load_json(self, name, default):
        try:
            return json.loads((data_dir() / name).read_text("utf-8"))
        except Exception:
            return default

    def save_json(self, name, obj):
        try:
            (data_dir() / name).write_text(
                json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")
        except Exception:
            pass

    def save_settings(self):
        self.settings["sources"] = [k for k, v in self.src_vars.items() if v.get()]
        self.settings["free_only"] = self.free_var.get()
        self.save_json("settings.json", self.settings)

    # ---------- 介面
    def build_ui(self):
        bg = "#FFFFFF"
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Big.TButton", font=F_MID, padding=(14, 6))

        top = tk.Frame(self.root, bg="#F4F4F2", padx=18, pady=10)
        top.pack(fill="x")
        tk.Label(top, text=APP_NAME, font=(FONT, 22, "bold"), bg="#F4F4F2").pack(side="left")
        tk.Label(top, text=f"{AUTHOR}　{VERSION}", font=(FONT, 16, "italic"),
                 fg=GOLD, bg="#F4F4F2").pack(side="right")

        body = tk.Frame(self.root, bg=bg, padx=18, pady=10)
        body.pack(fill="both", expand=True)

        # 搜尋列
        r1 = tk.Frame(body, bg=bg)
        r1.pack(fill="x")
        self.q_var = tk.StringVar()
        e = tk.Entry(r1, textvariable=self.q_var, font=F_BIG, relief="solid", bd=1)
        e.pack(side="left", fill="x", expand=True, ipady=6)
        e.bind("<Return>", lambda ev: self.start_search(from_en=False))
        e.focus_set()
        tk.Button(r1, text="搜尋", font=F_BIG, bg="#222222", fg="white",
                  activebackground="#444444", activeforeground="white",
                  relief="flat", padx=26, command=lambda: self.start_search(False)
                  ).pack(side="left", padx=(10, 0))

        r2 = tk.Frame(body, bg=bg, pady=8)
        r2.pack(fill="x")
        tk.Label(r2, text="英文關鍵字", font=F_MID, bg=bg, fg="#555555").pack(side="left")
        self.en_var = tk.StringVar()
        e2 = tk.Entry(r2, textvariable=self.en_var, font=F_MID, relief="solid", bd=1)
        e2.pack(side="left", fill="x", expand=True, padx=10, ipady=3)
        e2.bind("<Return>", lambda ev: self.start_search(from_en=True))
        tk.Label(r2, text="可修改後按 Enter", font=F_SM, bg=bg, fg="#888888").pack(side="left")

        # 來源
        r3 = tk.Frame(body, bg=bg)
        r3.pack(fill="x", pady=(4, 0))
        tk.Label(r3, text="搜尋來源", font=F_MID, bg=bg, fg="#555555").pack(side="left", padx=(0, 8))
        saved = self.settings.get("sources")
        self.src_vars = {}
        for k, name, *_ in SOURCES:
            v = tk.BooleanVar(value=(k in saved) if saved else (k != "archive"))
            self.src_vars[k] = v
            tk.Checkbutton(r3, text=name, variable=v, font=F_SM, indicatoron=False,
                           selectcolor="#DCEBFA", bg="#FFFFFF", relief="solid", bd=1,
                           padx=10, pady=4, offrelief="solid",
                           command=self.save_settings).pack(side="left", padx=3)

        r3b = tk.Frame(body, bg=bg)
        r3b.pack(fill="x", pady=(6, 0))
        tk.Label(r3b, text="快速選擇", font=F_MID, bg=bg, fg="#555555").pack(side="left", padx=(0, 8))
        for label, cat in (("全部", None), ("老照片", "photo"), ("名畫", "art")):
            ttk.Button(r3b, text=label, style="Big.TButton",
                       command=lambda c=cat: self.preset(c)).pack(side="left", padx=3)
        self.free_var = tk.BooleanVar(value=self.settings.get("free_only", True))
        tk.Checkbutton(r3b, text="只看可自由使用（公有領域、CC0）", variable=self.free_var,
                       font=F_MID, bg=bg, activebackground=bg,
                       command=self.on_free_toggle).pack(side="left", padx=(20, 0))

        # 工具列
        tb = tk.Frame(body, bg="#F4F4F2", padx=10, pady=8)
        tb.pack(fill="x", pady=(12, 8))
        ttk.Button(tb, text="全選本頁", style="Big.TButton", command=self.check_page).pack(side="left", padx=3)
        ttk.Button(tb, text="全部取消", style="Big.TButton", command=self.uncheck_all).pack(side="left", padx=3)
        self.dl_btn = tk.Button(tb, text="下載已勾選（0）", font=F_MIDB, bg="#1F6FB2", fg="white",
                                activebackground="#2A80C8", activeforeground="white",
                                relief="flat", padx=16, pady=4, command=self.download_checked)
        self.dl_btn.pack(side="left", padx=(12, 3))
        self.fav_btn = ttk.Button(tb, text="收藏已勾選", style="Big.TButton", command=self.fav_checked)
        self.fav_btn.pack(side="left", padx=3)
        self.unfav_btn = ttk.Button(tb, text="移除已勾選收藏", style="Big.TButton", command=self.unfav_checked)
        ttk.Button(tb, text="開啟下載資料夾", style="Big.TButton", command=self.open_folder).pack(side="right", padx=3)
        ttk.Button(tb, text="變更資料夾", style="Big.TButton", command=self.choose_folder).pack(side="right", padx=3)

        # 圖片牆
        self.grid = tk.Frame(body, bg=bg)
        self.grid.pack(fill="both", expand=True)
        for c in range(3):
            self.grid.columnconfigure(c, weight=1, uniform="col")
        for r in range(2):
            self.grid.rowconfigure(r, weight=1, uniform="row")
        self.cards = [self.make_card(i) for i in range(PER_PAGE)]

        # 分頁
        pg = tk.Frame(body, bg=bg, pady=6)
        pg.pack(fill="x")
        self.view_btn = ttk.Button(pg, text="看我的收藏", style="Big.TButton", command=self.toggle_view)
        self.view_btn.pack(side="left")
        ttk.Button(pg, text="下一頁", style="Big.TButton", command=self.next_page).pack(side="right")
        self.page_lbl = tk.Label(pg, text="", font=F_MID, bg=bg)
        self.page_lbl.pack(side="right", padx=14)
        ttk.Button(pg, text="上一頁", style="Big.TButton", command=self.prev_page).pack(side="right")

        # 詳細資訊
        det = tk.Frame(body, bg="#F7F7F5", padx=14, pady=10, highlightthickness=1,
                       highlightbackground="#CCCCCC")
        det.pack(fill="x", pady=(4, 0))
        left = tk.Frame(det, bg="#F7F7F5")
        left.pack(side="left", fill="x", expand=True)
        self.det_title = tk.Label(left, text="點一下圖片看詳細資訊，按兩下看大圖",
                                  font=F_MIDB, bg="#F7F7F5", anchor="w")
        self.det_title.pack(fill="x")
        self.det_info = tk.Label(left, text="", font=F_SM, bg="#F7F7F5", fg="#555555",
                                 anchor="w", justify="left")
        self.det_info.pack(fill="x")
        tk.Button(det, text="下載這張", font=F_MIDB, bg="#222222", fg="white",
                  activebackground="#444444", activeforeground="white", relief="flat",
                  padx=16, pady=4, command=lambda: self.download_items([self.current] if self.current else [])
                  ).pack(side="right", padx=3)
        ttk.Button(det, text="收藏這張", style="Big.TButton",
                   command=lambda: self.add_favs([self.current] if self.current else [])).pack(side="right", padx=3)
        ttk.Button(det, text="開啟出處頁", style="Big.TButton", command=self.open_page).pack(side="right", padx=3)

        self.status = tk.Label(self.root, text="輸入中文或英文關鍵字，按 Enter 搜尋",
                               font=F_SM, bg="#F4F4F2", fg="#444444", anchor="w", padx=18, pady=6)
        self.status.pack(fill="x", side="bottom")

    def make_card(self, i):
        f = tk.Frame(self.grid, bg="#FFFFFF", highlightthickness=1,
                     highlightbackground="#D0D0D0", padx=8, pady=8)
        f.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
        img = tk.Label(f, bg="#EFEFEC", width=THUMB_W, height=THUMB_H, cursor="hand2")
        img.pack(fill="x")
        var = tk.BooleanVar()
        cb = tk.Checkbutton(f, variable=var, font=F_MIDB, bg="#FFFFFF", anchor="w",
                            activebackground="#FFFFFF", wraplength=320, justify="left")
        cb.pack(fill="x", pady=(6, 0))
        meta = tk.Frame(f, bg="#FFFFFF")
        meta.pack(fill="x")
        src = tk.Label(meta, font=F_SM, bg="#FFFFFF", fg="#666666", anchor="w")
        src.pack(side="left")
        badge = tk.Label(meta, font=F_SM, padx=8)
        badge.pack(side="right")
        card = {"frame": f, "img": img, "var": var, "cb": cb, "src": src,
                "badge": badge, "item": None}
        img.bind("<Button-1>", lambda e, c=card: self.select(c["item"]))
        img.bind("<Double-Button-1>", lambda e, c=card: self.preview(c["item"]))
        cb.configure(command=lambda c=card: self.on_check(c))
        return card

    # ---------- 顯示
    def items_view(self):
        if self.view_favs:
            return list(self.favs.values())
        if self.free_var.get():
            return [x for x in self.results if x.free]
        return self.results

    def render(self):
        items = self.items_view()
        start = self.page * PER_PAGE
        page_items = items[start:start + PER_PAGE]
        for i, card in enumerate(self.cards):
            it = page_items[i] if i < len(page_items) else None
            card["item"] = it
            if not it:
                card["frame"].grid_remove()
                continue
            card["frame"].grid()
            card["var"].set(it.key in self.checked)
            card["cb"].configure(text=it.title[:40])
            card["src"].configure(text=SRC_NAME.get(it.source, it.source))
            colors = {"ok": ("#E3F2E1", "#1B5E20"), "warn": ("#FFF1CC", "#7A4F01"),
                      "unk": ("#EEEEEE", "#555555")}[it.level or "unk"]
            card["badge"].configure(text=it.lic, bg=colors[0], fg=colors[1])
            card["frame"].configure(highlightbackground="#1F6FB2" if it is self.current else "#D0D0D0",
                                    highlightthickness=2 if it is self.current else 1)
            ph = self.thumbs.get(it.key)
            if ph:
                card["img"].configure(image=ph, text="")
            else:
                card["img"].configure(image=self.placeholder(), text="")
                self.load_thumb(it)
        total_pages = max(1, -(-len(items) // PER_PAGE))
        more = "" if self.view_favs else ("+" if self.results else "")
        self.page_lbl.configure(text=f"第 {self.page + 1} 頁 / 共 {total_pages}{more} 頁")
        self.dl_btn.configure(text=f"下載已勾選（{len(self.checked)}）")
        if self.view_favs:
            self.fav_btn.pack_forget()
            self.unfav_btn.pack(side="left", padx=3)
            self.view_btn.configure(text="回到搜尋結果")
        else:
            self.unfav_btn.pack_forget()
            self.fav_btn.pack(side="left", padx=3)
            self.view_btn.configure(text=f"看我的收藏（{len(self.favs)}）")
        if self.view_favs and not items:
            self.set_status("收藏是空的。勾選圖片後按「收藏已勾選」就會出現在這裡。")

    _ph = None

    def placeholder(self):
        if not App._ph:
            im = Image.new("RGB", (THUMB_W, THUMB_H), "#EFEFEC")
            d = ImageDraw.Draw(im)
            d.rectangle([0, 0, THUMB_W - 1, THUMB_H - 1], outline="#DDDDDA")
            App._ph = ImageTk.PhotoImage(im)
        return App._ph

    def load_thumb(self, it):
        if it.key in self.thumb_loading:
            return
        self.thumb_loading.add(it.key)

        def job():
            try:
                if MOCK or not it.thumb:
                    im = Image.new("RGB", (400, 260), ["#C9B79C", "#9CB4C9", "#A9C99C"][hash(it.key) % 3])
                else:
                    r = get_with_fallback(it.thumb, it, 20)
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.thumbnail((THUMB_W, THUMB_H))
                canvas = Image.new("RGB", (THUMB_W, THUMB_H), "#EFEFEC")
                canvas.paste(im, ((THUMB_W - im.width) // 2, (THUMB_H - im.height) // 2))
                self.q.put(("thumb", it.key, canvas))
            except Exception:
                self.q.put(("thumbfail", it.key, None))
        self.pool.submit(job)

    # ---------- 事件處理（背景執行緒 → 主執行緒）
    def poll(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "thumb":
                    self.thumbs[a] = ImageTk.PhotoImage(b)
                    for c in self.cards:
                        if c["item"] and c["item"].key == a:
                            c["img"].configure(image=self.thumbs[a])
                elif kind == "thumbfail":
                    self.thumb_loading.discard(a)
                elif kind == "translated":
                    self.en_var.set(a)
                elif kind == "results":
                    self.merge_results(a, b)
                elif kind == "status":
                    self.set_status(a)
                elif kind == "done_download":
                    self.after_download(a, b)
                elif kind == "msg":
                    messagebox.showinfo(APP_NAME, a)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def set_status(self, s):
        self.status.configure(text=s)

    # ---------- 搜尋
    def active_sources(self):
        return [s for s in SOURCES if self.src_vars[s[0]].get()]

    def preset(self, cat):
        for k, name, fn, zh, c in SOURCES:
            self.src_vars[k].set(cat is None or c == cat or c == "both")
        self.save_settings()

    def on_free_toggle(self):
        self.save_settings()
        self.page = 0
        self.render()

    def start_search(self, from_en):
        if self.searching:
            return
        text = self.q_var.get().strip()
        en = self.en_var.get().strip()
        if not text and not en:
            self.set_status("請先輸入關鍵字")
            return
        srcs = self.active_sources()
        if not srcs:
            self.set_status("請至少選一個搜尋來源")
            return
        self.view_favs = False
        self.results, self.seen, self.page, self.fetch_page = [], set(), 0, 0
        self.current = None
        self.hidden_count = 0
        self.render()
        self.searching = True
        self.set_status("搜尋中…")

        def job():
            q_en = en if from_en else text
            q_zh = text if CJK.search(text) else ""
            if not from_en and q_zh:
                self.q.put(("status", "翻譯成英文中…", None))
                try:
                    q_en = translate_zh_en(text)
                    self.q.put(("translated", q_en, None))
                except Exception:
                    q_en = text
                    self.q.put(("translated", "", None))
                    self.q.put(("status", "翻譯失敗，先用中文搜尋；也可以自己在英文欄輸入", None))
            elif not from_en:
                self.q.put(("translated", text, None))
            self.query_en, self.query_zh = q_en, q_zh
            self.fetch_more_sync(srcs)
        threading.Thread(target=job, daemon=True).start()

    def fetch_more_sync(self, srcs):
        self.fetch_page += 1
        page = self.fetch_page
        free = self.free_var.get()
        jobs = []
        for k, name, fn, zh, cat in srcs:
            jobs.append((name, fn, self.query_en))
            if zh and self.query_zh and self.query_zh != self.query_en:
                jobs.append((name, fn, self.query_zh))
        per_src, errors = [], []

        def run(j):
            name, fn, q = j
            try:
                return name, fn(q, page, free), None
            except Exception as ex:
                return name, [], str(ex)[:60]
        with ThreadPoolExecutor(8) as ex:
            for name, items, err in ex.map(run, jobs):
                per_src.append(items)
                if err:
                    errors.append(name)
        merged = []
        i = 0
        while any(i < len(l) for l in per_src):
            for l in per_src:
                if i < len(l):
                    merged.append(l[i])
            i += 1
        self.q.put(("results", merged, errors))

    def merge_results(self, items, errors):
        self.searching = False
        new = [x for x in items if x.key not in self.seen and (x.full or x.resolver)]
        for x in new:
            self.seen.add(x.key)
        self.results.extend(new)
        shown = len(self.items_view())
        hidden = len(self.results) - shown
        msg = f"找到 {len(self.results)} 張"
        if self.free_var.get() and hidden:
            msg += f"，其中 {hidden} 張權利不明或需標示作者已隱藏（取消勾選「只看可自由使用」就會顯示）"
        if errors:
            msg += f"。連不上：{'、'.join(sorted(set(errors)))}"
        if not self.results:
            msg = "沒有找到。可以試試修改英文關鍵字，或多勾選幾個來源。" + (
                f" 連不上：{'、'.join(sorted(set(errors)))}" if errors else "")
        self.set_status(msg)
        self.render()

    def next_page(self):
        items = self.items_view()
        if (self.page + 1) * PER_PAGE < len(items):
            self.page += 1
            self.render()
            if not self.view_favs and (self.page + 2) * PER_PAGE >= len(items):
                self.load_more()
        elif not self.view_favs and self.results:
            self.load_more(advance=True)

    def load_more(self, advance=False):
        if self.searching:
            return
        self.searching = True
        self.set_status("載入更多…")
        srcs = self.active_sources()
        before = len(self.items_view())

        def job():
            self.fetch_more_sync(srcs)
        threading.Thread(target=job, daemon=True).start()
        if advance:
            def wait():
                if self.searching:
                    self.root.after(200, wait)
                elif len(self.items_view()) > before:
                    self.page += 1
                    self.render()
                else:
                    self.set_status("已經是最後一頁了")
            wait()

    def prev_page(self):
        if self.page > 0:
            self.page -= 1
            self.render()

    def toggle_view(self):
        self.view_favs = not self.view_favs
        self.page = 0
        self.checked.clear()
        self.render()

    # ---------- 勾選
    def on_check(self, card):
        it = card["item"]
        if not it:
            return
        if card["var"].get():
            self.checked[it.key] = it
        else:
            self.checked.pop(it.key, None)
        self.render()

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
        self.det_title.configure(text=it.title)
        info = f"來源：{SRC_NAME.get(it.source, it.source)}　　授權：{it.lic}"
        if it.creator:
            info += f"　　作者：{it.creator}"
        self.det_info.configure(text=info)
        self.render()

    def open_page(self):
        if self.current and self.current.page:
            webbrowser.open(self.current.page)

    def preview(self, it):
        if not it:
            return
        self.select(it)
        win = tk.Toplevel(self.root)
        win.title(it.title)
        win.geometry("1000x760")
        lbl = tk.Label(win, text="載入大圖中…", font=F_MID, bg="#202020", fg="white")
        lbl.pack(fill="both", expand=True)
        tk.Label(win, text=f"{it.title}　|　{it.lic}", font=F_MID).pack(fill="x", pady=6)
        holder = {}

        def job():
            try:
                url = None if MOCK else full_url(it)
                if MOCK or not url:
                    im = Image.new("RGB", (1600, 1000), "#9CB4C9")
                else:
                    r = get_with_fallback(url, it, 60)
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.thumbnail((980, 680))

                def show():
                    if win.winfo_exists():
                        holder["p"] = ImageTk.PhotoImage(im)
                        lbl.configure(image=holder["p"], text="")
                self.root.after(0, show)
            except Exception:
                self.root.after(0, lambda: win.winfo_exists() and lbl.configure(text="大圖載入失敗，可以按「開啟出處頁」在瀏覽器看"))
        threading.Thread(target=job, daemon=True).start()

    # ---------- 收藏
    def add_favs(self, items):
        items = [x for x in items if x]
        if not items:
            self.set_status("請先勾選或點選圖片")
            return
        for x in items:
            self.favs[x.key] = x
        self.save_json("favorites.json", [x.to_dict() for x in self.favs.values()])
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
        self.save_json("favorites.json", [x.to_dict() for x in self.favs.values()])
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
            self.set_status(f"下載資料夾：{d}")

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

        def job():
            ok, fail = 0, 0
            rows = []
            for n, it in enumerate(items, 1):
                try:
                    url = None if MOCK else full_url(it)
                    if MOCK:
                        data, ext = b"mock", ".jpg"
                    else:
                        r = get_with_fallback(url, it, 120)
                        data = r.content
                        ct = r.headers.get("Content-Type", "")
                        ext = ".png" if "png" in ct else ".tif" if "tiff" in ct else ".jpg"
                        m = re.search(r"\.(jpe?g|png|tiff?|gif|webp)(?:$|\?)", url, re.I)
                        if m:
                            ext = "." + m.group(1).lower()
                    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", it.title)[:60].strip() or "image"
                    ident = re.sub(r"[^0-9A-Za-z_-]", "", it.key.split(":", 1)[1])[-20:]
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
                            w.writerow(["檔名", "標題", "來源", "授權", "作者", "出處網址"])
                        w.writerows(rows)
                except Exception:
                    pass
            self.q.put(("done_download", ok, fail))
        threading.Thread(target=job, daemon=True).start()

    def after_download(self, ok, fail):
        msg = f"已下載 {ok} 張到：\n{self.folder()}"
        if fail:
            msg += f"\n\n有 {fail} 張下載失敗，可以稍後再試，或開啟出處頁手動下載。"
        msg += "\n\n每張的來源和授權記在資料夾裡的「出處紀錄.csv」。"
        self.set_status(f"下載完成：成功 {ok} 張" + (f"，失敗 {fail} 張" if fail else ""))
        self.checked.clear()
        self.render()
        if messagebox.askyesno(APP_NAME, msg + "\n\n要開啟下載資料夾嗎？"):
            self.open_folder()


def main():
    root = tk.Tk()
    try:
        root.state("zoomed")
    except Exception:
        pass
    app = App(root)
    if os.environ.get("PHOTO_SMOKE") == "1":
        app.q_var.set("老火車")
        root.after(500, lambda: app.start_search(False))
        root.after(6000, lambda: (print("SMOKE results", len(app.results)), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
