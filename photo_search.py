# -*- coding: utf-8 -*-
"""經典圖庫搜尋 v0.3  作者:ArchieKUO
免費圖庫搜尋：台灣觀光署、Unsplash、Pixabay…
結果依「台灣 → 亞洲 → 歐美及其他」分段，一排 4 張，上下捲動自動載入。
介面顏色跟著 Windows 淺色／深色設定。
"""
import os
import re
import io
import csv
import json
import time
import queue
import zipfile
import threading
import webbrowser
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
import requests
from PIL import Image, ImageOps, ImageDraw

APP_NAME = "經典圖庫搜尋"
VERSION = "v0.4"
AUTHOR = "作者:ArchieKUO"
GOLD = "#C9A227"
UA = {"User-Agent": "ClassicPhotoSearch/0.4 (personal desktop app)"}
IMG_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 ClassicPhotoSearch/0.4"}
PER_FETCH = 16
COLS = 4
MAX_ITEMS = 320
QUALITY = {"on": True}      # 「只看精選」
MIN_W = 1600
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

SECTIONS = [("tw", "台灣"), ("asia", "亞洲（日本、韓國、東南亞）"), ("other", "歐美及其他地區")]
TW_WORDS = ["taiwan", "taipei", "kaohsiung", "taichung", "tainan", "hualien", "taroko",
            "jiufen", "kenting", "sun moon lake", "alishan", "yilan", "keelung", "hsinchu",
            "台灣", "臺灣", "台北", "臺北", "高雄", "台中", "臺中", "台南", "臺南", "花蓮"]
ASIA_WORDS = ["japan", "japanese", "tokyo", "kyoto", "osaka", "hokkaido", "okinawa", "nara",
              "korea", "korean", "seoul", "busan", "jeju", "hong kong", "macau", "china",
              "chinese", "shanghai", "beijing", "thailand", "thai", "bangkok", "chiang mai",
              "phuket", "vietnam", "hanoi", "saigon", "ho chi minh", "singapore", "malaysia",
              "kuala lumpur", "bali", "indonesia", "jakarta", "philippines", "manila",
              "cambodia", "laos", "myanmar", "asia", "asian", "日本", "韓國", "東京", "京都"]
SYNONYMS = [
    ["酒店", "飯店", "旅館", "民宿", "旅店", "hotel"],
    ["餐廳", "美食", "小吃", "料理"],
    ["海邊", "海灘", "沙灘", "海景", "海岸"],
    ["山", "山景", "高山", "步道"],
    ["夜景", "夜晚", "夜市"],
    ["廟", "寺廟", "宮", "寺"],
]


def F(size, bold=False, italic=False):
    return ctk.CTkFont(family=FONT, size=size, weight="bold" if bold else "normal",
                       slant="italic" if italic else "roman")


def data_dir():
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "ClassicPhotoSearch"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_download_dir():
    return str(Path.home() / "Downloads" / "經典圖庫")


def strip_html(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


def classify(text):
    t = (text or "").lower()
    if t == "free":
        return ("免費可用", True, "ok")
    if t == "gov":
        return ("免費・註明出處", True, "warn")
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
    out, w = "", 0.0
    for ch in text:
        cw = 1.0 if CJK.match(ch) else 0.56
        if w + cw > max_em:
            return out.rstrip() + "…"
        out += ch
        w += cw
    return out


def rounded(img, bg, r):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], r, fill=255)
    out = Image.new("RGB", img.size, bg)
    out.paste(img, (0, 0), mask)
    return out


def region_of(text):
    t = (text or "").lower()
    if any(w in t for w in TW_WORDS):
        return "tw"
    if any(w in t for w in ASIA_WORDS):
        return "asia"
    return None


class Item:
    FIELDS = ("key", "source", "title", "thumb", "full", "page", "creator",
              "lic", "free", "level", "size", "dl_ping", "place", "pop", "width")

    def __init__(self, source, ident, title, thumb, full, page, creator,
                 lic_text, size="", dl_ping=None, place="", pop=0):
        self.source = source
        self.key = f"{source}:{ident}"
        t = (title or "").strip()
        self.title = (t[:1].upper() + t[1:])[:120] if t else "未命名"
        self.thumb, self.full, self.page = thumb, full, page
        self.creator = strip_html(creator)[:60]
        self.lic, self.free, self.level = classify(lic_text)
        self.size = size if size and "None" not in str(size) else ""
        self.dl_ping = dl_ping
        self.place = place
        self.pop = pop or 0
        m = re.match(r"(\d+)", str(size or ""))
        self.width = int(m.group(1)) if m else 0

    def to_dict(self):
        return {k: getattr(self, k, None) for k in self.FIELDS}

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
                  {"query": q, "per_page": PER_FETCH, "page": page}, {"Authorization": key})
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
        loc = ""
        out.append(Item("unsplash", p.get("id"),
                        p.get("alt_description") or p.get("description") or q,
                        urls.get("small") or urls.get("regular"),
                        urls.get("full") or urls.get("raw"),
                        links.get("html"), (p.get("user") or {}).get("name"), "free",
                        f"{p.get('width')} × {p.get('height')}",
                        dl_ping=links.get("download_location"), place=loc,
                        pop=p.get("likes") or 0))
    return out


def src_pixabay(q, page, key):
    d = http_json("https://pixabay.com/api/",
                  dict({"key": key, "q": q[:100], "image_type": "photo",
                        "per_page": PER_FETCH, "page": page, "safesearch": "true",
                        "order": "popular"},
                       **({"editors_choice": "true", "min_width": MIN_W} if QUALITY["on"] else {})))
    out = []
    for p in d.get("hits", []):
        tags = p.get("tags") or ""
        first = tags.split(",")[0].strip()
        it = Item("pixabay", p.get("id"), first or q,
                  p.get("webformatURL") or p.get("previewURL"),
                  p.get("largeImageURL") or p.get("webformatURL"),
                  p.get("pageURL"), p.get("user"), "free",
                  f"{p.get('imageWidth')} × {p.get('imageHeight')}",
                  pop=(p.get("likes") or 0) + (p.get("downloads") or 0) / 20)
        it.place = tags
        out.append(it)
    return out


def src_commons(q, page, key):
    p = http_json("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f'{q} filetype:bitmap' + (' incategory:"Quality_images"' if QUALITY["on"] else ""),
        "gsrnamespace": 6,
        "gsrlimit": PER_FETCH, "gsroffset": (page - 1) * PER_FETCH,
        "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": 500},
        timeout=25)
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


def src_openverse(q, page, key):
    params = {"q": q, "page": page, "page_size": 20, "license": "cc0,pdm,by,by-sa"}
    if QUALITY["on"]:
        params["size"] = "large"
    d = http_json("https://api.openverse.org/v1/images/", params, timeout=25)
    out = []
    for r in d.get("results", []):
        lic = r.get("license", "")
        lic = "public domain" if lic == "pdm" else ("cc0" if lic == "cc0" else f"cc {lic}")
        size = f"{r.get('width')} × {r.get('height')}" if r.get("width") else ""
        out.append(Item("openverse", r.get("id"), r.get("title"),
                        r.get("thumbnail") or r.get("url"), r.get("url"),
                        r.get("foreign_landing_url"), r.get("creator"), lic, size))
    return out


def src_lummi(q, page, key):
    params = {"query": q, "page": page, "perPage": 20, "imageType": "photo", "free": "true"}
    h = {"Authorization": f"Bearer {key}"}
    try:
        d = http_json("https://api.lummi.ai/v1/images/search", params, h, timeout=25)
    except requests.HTTPError as ex:
        if ex.response is not None and ex.response.status_code == 404:
            d = http_json("https://api.lummi.ai/v1/images", params, h, timeout=25)
        else:
            raise
    rows = d.get("data") if isinstance(d, dict) else d
    if isinstance(rows, dict):
        rows = rows.get("images") or rows.get("data") or []
    out = []
    for r in rows or []:
        url = r.get("url")
        if not url:
            continue
        base = url.split("?")[0]
        author = (r.get("author") or {}).get("name", "")
        out.append(Item("lummi", r.get("id"), r.get("name") or r.get("description") or q,
                        base + "?w=600", base, r.get("attributionUrl") or "https://www.lummi.ai/",
                        author, "free", f"{r.get('width')} × {r.get('height')}",
                        place=r.get("description") or ""))
    return out


class TwTourism:
    """交通部觀光署 觀光資訊資料庫（景點、旅館民宿、活動），下載一次存在電腦裡，每 7 天更新。"""
    FILES = [("Attraction", "Attractions", "AttractionName", "景點"),
             ("Hotel", "Hotels", "HotelName", "旅宿"),
             ("Event", "Events", "EventName", "活動")]
    BASE = "https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/{}-json.zip"

    def __init__(self):
        self.lock = threading.Lock()
        self.entries = None

    def ensure(self, status=None):
        with self.lock:
            if self.entries is not None:
                return
            cache = data_dir() / "tw_tourism.json"
            fresh = cache.exists() and time.time() - cache.stat().st_mtime < 7 * 86400
            if not fresh:
                try:
                    if status:
                        status("第一次使用或資料過期，正在下載台灣觀光署資料（約 9 MB）…")
                    entries = self.download()
                    cache.write_text(json.dumps(entries, ensure_ascii=False), "utf-8")
                except Exception:
                    if not cache.exists():
                        raise
            self.entries = json.loads(cache.read_text("utf-8"))

    def download(self):
        entries = []
        for fname, listkey, namekey, kind in self.FILES:
            r = requests.get(self.BASE.format(fname), headers=UA, timeout=180)
            r.raise_for_status()
            z = zipfile.ZipFile(io.BytesIO(r.content))
            fn = [n for n in z.namelist() if n.endswith("List.json")][0]
            data = json.loads(z.read(fn).decode("utf-8-sig"))
            for rec in data.get(listkey, []):
                imgs = [i for i in (rec.get("Images") or []) if i.get("URL")]
                if not imgs:
                    continue
                addr = rec.get("PostalAddress") or {}
                city = (addr.get("City") or "") + (addr.get("Town") or "")
                name = rec.get(namekey) or ""
                desc = (rec.get("Description") or "")[:300]
                site = rec.get("WebsiteURL") or ""
                rid = rec.get(fname + "ID") or name
                for n, im in enumerate(imgs[:4]):
                    entries.append([f"{rid}-{n}", name, (im.get("Name") or "")[:60],
                                    desc, city, im["URL"], site, kind])
        return entries

    def search(self, q_zh, page):
        if MOCK:
            return [Item("tw", f"{page}-{i}", f"日月潭涵碧樓景觀飯店 {i + 1}", "mock", "mock",
                         "https://www.taiwan.net.tw/", "", "gov", place="南投縣")
                    for i in range(8)] if page <= 2 else []
        self.ensure()
        tokens = [t for t in re.split(r"[\s,，、]+", q_zh) if t]
        if not tokens:
            return []
        groups = []
        for t in tokens:
            g = {t}
            for syn in SYNONYMS:
                if t in syn:
                    g.update(syn)
            groups.append(g)
        scored = []
        for e in self.entries:
            rid, name, iname, desc, city, url, site, kind = e
            score = 0
            ok = True
            for g in groups:
                s = 0
                for w in g:
                    if w in name:
                        s = max(s, 3)
                    elif w in iname or w in city:
                        s = max(s, 2)
                    elif w in desc:
                        s = max(s, 1)
                if s == 0:
                    ok = False
                    break
                score += s
            if ok:
                scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        part = scored[(page - 1) * PER_FETCH: page * PER_FETCH]
        out = []
        for _, (rid, name, iname, desc, city, url, site, kind) in part:
            title = name if not iname or iname in name else f"{name}・{iname}"
            out.append(Item("tw", rid, title, url, url,
                            site or "https://www.taiwan.net.tw/", "交通部觀光署", "gov",
                            place=city))
        return out


TW = TwTourism()


def src_tw(q, page, key):
    return TW.search(q, page)


MOCK_WORDS = ["Hotel lobby with ocean view", "飯店泳池", "Hotel room", "城市夜景飯店",
              "Luxury resort entrance", "飯店餐廳"]


def make_mock(source):
    def fn(q, page, key):
        out = []
        if page > 2:
            return out
        for i in range(8):
            n = (page - 1) * 8 + i
            title = MOCK_WORDS[n % len(MOCK_WORDS)] + " " + q.split()[-1]
            out.append(Item(source, f"{q}-{n}", title, "mock", "mock",
                            "https://example.com", "測試攝影師", "free", "6000 × 4000"))
        return out
    return fn


# key, 名稱, 函式, 需要金鑰, 預設勾選, 放在「更多」, 是否為國際圖庫(會分台灣/亞洲/其他搜尋)
SOURCES = [
    ("tw", "台灣觀光署", src_tw, False, True, False, False),
    ("unsplash", "Unsplash", src_unsplash, True, True, False, True),
    ("pixabay", "Pixabay", src_pixabay, True, True, False, True),
    ("commons", "維基優質圖片", src_commons, False, True, False, True),
    ("lummi", "Lummi（AI）", src_lummi, True, False, False, False),
    ("openverse", "Openverse", src_openverse, False, False, True, False),
    ("pexels", "Pexels", src_pexels, True, False, True, True),
]
if MOCK:
    SOURCES = [(k, n, (fn if k == "tw" else make_mock(k)), False, d, x, g)
               for k, n, fn, _, d, x, g in SOURCES]
SRC_NAME = {s[0]: s[1] for s in SOURCES}

KEY_INFO = [
    ("unsplash", "Unsplash", "https://unsplash.com/oauth/applications",
     "建立應用程式後，在「Keys」區複製「Access Key」"),
    ("pixabay", "Pixabay", "https://pixabay.com/api/docs/",
     "登入後按 Explore → API → View API documentation，往下捲找「key」"),
    ("lummi", "Lummi（AI）", "https://www.lummi.ai/developers",
     "註冊登入後到 Developers 申請 API 金鑰（AI 生成的圖片）"),
    ("pexels", "Pexels", "https://www.pexels.com/api/",
     "Pexels 目前暫停核發新金鑰，以後恢復再申請"),
]


def test_key(src, key):
    fn = {"pexels": src_pexels, "unsplash": src_unsplash, "pixabay": src_pixabay,
          "lummi": src_lummi}[src]
    fn("hotel", 1, key)


# ---------------------------------------------------------------- 翻譯
def translate(text, sl, tl):
    if MOCK:
        return {"en": "hotel", "ja": "ホテル", "zh-TW": "飯店", "zh-CN": "酒店"}.get(tl, text)
    try:
        d = http_json("https://translate.googleapis.com/translate_a/single", {
            "client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text}, timeout=10)
        s = "".join(seg[0] for seg in d[0] if seg and seg[0]).strip()
        if s:
            return s
    except Exception:
        pass
    d = http_json("https://api.mymemory.translated.net/get",
                  {"q": text, "langpair": f"{sl}|{tl}"}, timeout=10)
    s = (d.get("responseData") or {}).get("translatedText", "").strip()
    if not s:
        raise RuntimeError("翻譯失敗")
    return s


def download_one(it, d, keys):
    """下載一張圖到資料夾 d，回傳 (檔名, 出處紀錄列)。失敗會丟出例外。"""
    if it.full == "mock":
        data, ext = b"mock", ".jpg"
    else:
        if it.source == "unsplash" and it.dl_ping and keys.get("unsplash"):
            try:
                requests.get(it.dl_ping, headers={
                    **UA, "Authorization": f"Client-ID {keys['unsplash']}"}, timeout=15)
            except Exception:
                pass
        r = requests.get(it.full, headers=UA if it.source == "commons" else IMG_UA, timeout=90)
        r.raise_for_status()
        data = r.content
        if len(data) < 500:
            raise RuntimeError("檔案太小，可能不是圖片")
        ct = r.headers.get("Content-Type", "")
        ext = ".png" if "png" in ct else ".webp" if "webp" in ct else ".jpg"
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", it.title)[:50].strip(" .") or "image"
    ident = re.sub(r"[^0-9A-Za-z_-]", "", it.key.split(":", 1)[1])[-16:]
    fn = Path(d) / f"{safe}_{SRC_NAME.get(it.source, it.source)}_{ident}{ext}"
    fn.write_bytes(data)
    credit = it.creator or ""
    if it.source == "tw":
        credit = "交通部觀光署（政府資料開放授權條款第1版）"
    return fn.name, [fn.name, it.title, SRC_NAME.get(it.source, it.source),
                     it.lic, credit, it.page or ""]


# ---------------------------------------------------------------- 主程式
class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(8)
        self.settings = self.load_json("settings.json", {})
        self.keys = self.settings.setdefault("keys", {})
        self.favs = {d["key"]: Item.from_dict(d) for d in self.load_json("favorites.json", [])}
        self.items = {s: [] for s, _ in SECTIONS}
        self.seen = set()
        self.fetch_page = 0
        self.exhausted = False
        self.checked = {}
        self.current = None
        self.pil = {}
        self.loading = set()
        self.mode = "search"
        self.query_en = self.query_zh = ""
        self.searching = False
        self.search_id = 0
        self.more_open = False
        self.thumb_w = 240
        self._resize_job = None
        self.ph_img = None
        self.cards = []
        self.last_merge = 0

        root.title(f"{APP_NAME} {VERSION}")
        root.geometry("1280x900")
        root.minsize(1000, 680)
        root.configure(fg_color=BG)
        self.build()
        self.root.after(100, self.poll)
        self.show_mode("search")
        if not MOCK and not any(self.keys.get(k) for k, *_ in KEY_INFO):
            self.set_status("台灣觀光署不用金鑰就能搜；Unsplash、Pixabay 請到「設定」貼上金鑰")

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
        self.settings["sources_v4"] = [k for k, v in self.src_on.items() if v]
        self.save_json("settings.json", self.settings)

    def save_favs(self):
        self.save_json("favorites.json", [x.to_dict() for x in self.favs.values()])

    # ---------- 共用元件
    def btn(self, parent, text, cmd, primary=False, width=0, size=16, height=40):
        kw = dict(text=text, command=cmd, font=F(size, bold=primary), height=height,
                  corner_radius=8)
        if width:
            kw["width"] = width
        if primary:
            kw.update(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF")
        else:
            kw.update(fg_color=PANEL, hover_color=PANEL2, text_color=TX,
                      border_width=1, border_color=LINE)
        return ctk.CTkButton(parent, **kw)

    # ---------- 介面
    def build(self):
        r = self.root
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(5, weight=1)

        head = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew")
        head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(head, text=APP_NAME, font=F(24, bold=True), text_color=TX
                     ).grid(row=0, column=0, padx=24, pady=10, sticky="w")
        self.status = ctk.CTkLabel(head, text="輸入關鍵字後按 Enter 搜尋", font=F(15),
                                   text_color=SUB, anchor="w")
        self.status.grid(row=0, column=1, sticky="ew", padx=10)
        ctk.CTkLabel(head, text=f"{AUTHOR}　{VERSION}  ", font=F(17, italic=True),
                     text_color=GOLD).grid(row=0, column=2, padx=(24, 20), sticky="e")

        s = ctk.CTkFrame(r, fg_color="transparent")
        s.grid(row=1, column=0, sticky="ew", padx=24, pady=(14, 0))
        s.grid_columnconfigure(0, weight=3)
        s.grid_columnconfigure(2, weight=2)
        self.q_entry = ctk.CTkEntry(s, font=F(20), height=50, corner_radius=10,
                                    border_width=1, border_color=LINE, fg_color=PANEL,
                                    text_color=TX, placeholder_text="輸入中文或英文，例如：海邊飯店")
        self.q_entry.grid(row=0, column=0, sticky="ew")
        self.q_entry.bind("<Return>", lambda e: self.start_search(False))
        ctk.CTkLabel(s, text="英文", font=F(16), text_color=SUB).grid(row=0, column=1, padx=(14, 8))
        self.en_entry = ctk.CTkEntry(s, font=F(18), height=50, corner_radius=10,
                                     border_width=1, border_color=LINE, fg_color=PANEL,
                                     text_color=TX, placeholder_text="自動翻譯，可修改後按 Enter")
        self.en_entry.grid(row=0, column=2, sticky="ew")
        self.en_entry.bind("<Return>", lambda e: self.start_search(True))
        ctk.CTkButton(s, text="搜尋", font=F(20, bold=True), height=50, width=120,
                      corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=lambda: self.start_search(False)).grid(row=0, column=3, padx=(12, 0))

        src = ctk.CTkFrame(r, fg_color="transparent")
        src.grid(row=2, column=0, sticky="ew", padx=24, pady=(12, 0))
        ctk.CTkLabel(src, text="來源", font=F(16), text_color=SUB).pack(side="left", padx=(2, 10))
        saved = self.settings.get("sources_v4")
        self.src_on, self.chips = {}, {}
        for k, name, fn, need, default, extra, intl in SOURCES:
            self.src_on[k] = (k in saved) if saved is not None else default
            b = ctk.CTkButton(src, text=name, font=F(16), height=38, corner_radius=19,
                              border_width=1, command=lambda k=k: self.toggle_src(k))
            self.chips[k] = (b, extra)
        self.more_btn = ctk.CTkButton(src, text="更多 ▾", font=F(16), height=38, width=80,
                                      corner_radius=19, fg_color="transparent",
                                      hover_color=PANEL2, text_color=SUB, command=self.toggle_more)
        self.layout_chips()

        # 品質列＋右側按鈕
        qr = ctk.CTkFrame(r, fg_color="transparent")
        qr.grid(row=3, column=0, sticky="ew", padx=24, pady=(10, 0))
        ctk.CTkLabel(qr, text="品質", font=F(16), text_color=SUB).pack(side="left", padx=(2, 10))
        self.hq_var = tk.BooleanVar(value=self.settings.get("quality", True))
        QUALITY["on"] = self.hq_var.get()
        ctk.CTkSwitch(qr, text="只看精選（濾掉小張、模糊、冷門的照片）", variable=self.hq_var,
                      font=F(16), text_color=TX, switch_width=48, switch_height=24,
                      progress_color=ACCENT, command=self.on_quality).pack(side="left")
        self.btn(qr, "設定", lambda: self.show_mode("settings"), width=80).pack(side="right")
        self.b_view = self.btn(qr, "我的收藏（0）", self.toggle_favs, width=150)
        self.b_view.pack(side="right", padx=8)
        self.b_sites = self.btn(qr, "其他網站 ↗", self.toggle_sites, width=130)
        self.b_sites.pack(side="right")

        # 其他網站（按「其他網站」才出現）
        self.sites = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
        self.sites_open = False
        groups = [("中文", [("Colorhub", "colorhub")]),
                  ("日本", [("ぱくたそ", "pakutaso"), ("写真AC", "photoac")]),
                  ("歐美", [("StockSnap", "stocksnap"), ("Burst", "burst"), ("ISO Republic", "isorepublic")])]
        inner = ctk.CTkFrame(self.sites, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(inner, text="用瀏覽器打開，並自動帶入關鍵字：", font=F(15), text_color=SUB
                     ).pack(side="left", padx=(0, 10))
        for gname, items in groups:
            ctk.CTkLabel(inner, text=gname, font=F(15, bold=True), text_color=TX).pack(side="left", padx=(12, 6))
            for label, key in items:
                self.btn(inner, label, lambda k=key: self.open_site(k), size=15, height=36,
                         width=0).pack(side="left", padx=3)

        # 內容區
        self.content = ctk.CTkFrame(r, fg_color="transparent")
        self.content.grid(row=5, column=0, sticky="nsew", padx=18, pady=(10, 0))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent",
                                             scrollbar_button_color=LINE,
                                             scrollbar_button_hover_color=SUB)
        self.scroll.grid_columnconfigure(0, weight=1)
        try:
            # 內建每格滾輪只捲 20 像素，太慢；改成每格約 140 像素（半張卡片）
            self.scroll._parent_canvas.configure(yscrollincrement=7)
        except Exception:
            pass
        self.sec = {}
        for i, (sk, title) in enumerate(SECTIONS + [("fav", "我的收藏")]):
            head = ctk.CTkFrame(self.scroll, fg_color="transparent")
            head.grid_columnconfigure(1, weight=1)
            lbl = ctk.CTkLabel(head, text=title, font=F(19, bold=True), text_color=TX)
            lbl.grid(row=0, column=0, sticky="w", padx=(6, 12))
            ctk.CTkFrame(head, height=1, fg_color=LINE).grid(row=0, column=1, sticky="ew")
            cnt = ctk.CTkLabel(head, text="", font=F(15), text_color=SUB)
            cnt.grid(row=0, column=2, padx=12)
            self.btn(head, "全選這一段", lambda sk=sk: self.check_section(sk), width=120,
                     size=15, height=34).grid(row=0, column=3, padx=(0, 6))
            grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
            for c in range(COLS):
                grid.grid_columnconfigure(c, weight=1, uniform="c")
            note = ctk.CTkLabel(self.scroll, text="", font=F(16), text_color=SUB)
            self.sec[sk] = {"head": head, "grid": grid, "cnt": cnt, "note": note,
                            "cards": [], "row": i * 3}
        self.empty_lbl = ctk.CTkLabel(self.content, text="輸入關鍵字，按 Enter 開始搜尋",
                                      font=F(18), text_color=SUB)
        self.content.bind("<Configure>", self.on_resize, add="+")
        self.settings_frame = self.build_settings(self.content)

        # 動作列
        bar = ctk.CTkFrame(r, fg_color=PANEL, corner_radius=12, border_width=1, border_color=LINE)
        bar.grid(row=6, column=0, sticky="ew", padx=24, pady=(8, 0))
        self.toolbar = bar
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)
        self.b_none = self.btn(inner, "全部取消", self.uncheck_all, width=110)
        self.b_dl = self.btn(inner, "下載", self.download_checked, primary=True, width=200)
        self.b_fav = self.btn(inner, "收藏", self.fav_checked, width=170)
        self.b_unfav = self.btn(inner, "移除收藏", self.unfav_checked, width=190)
        for b in (self.b_none, self.b_dl, self.b_fav):
            b.pack(side="left", padx=4)
        self.more_lbl = ctk.CTkLabel(inner, text="往下捲會自動載入更多", font=F(15), text_color=SUB)
        self.more_lbl.pack(side="right", padx=10)
        self.btn(inner, "開啟下載資料夾", self.open_folder, width=150).pack(side="right", padx=4)

        det = ctk.CTkFrame(r, fg_color="transparent")
        det.grid(row=7, column=0, sticky="ew", padx=24, pady=(8, 12))
        self.detail = det
        det.grid_columnconfigure(1, weight=1)
        self.det_title = ctk.CTkLabel(det, text="點一下圖片看資訊，按兩下看大圖",
                                      font=F(17, bold=True), text_color=TX, anchor="w")
        self.det_title.grid(row=0, column=0, sticky="w", padx=(4, 14))
        self.det_info = ctk.CTkLabel(det, text="", font=F(15), text_color=SUB, anchor="w")
        self.det_info.grid(row=0, column=1, sticky="ew")
        bb = ctk.CTkFrame(det, fg_color="transparent")
        bb.grid(row=0, column=2)
        self.btn(bb, "出處頁", self.open_page, width=100).pack(side="left", padx=(4, 0))

    def layout_chips(self):
        for k, (b, extra) in self.chips.items():
            b.pack_forget()
        self.more_btn.pack_forget()
        for k, (b, extra) in self.chips.items():
            if not extra or self.more_open or self.src_on[k]:
                b.pack(side="left", padx=4)
        self.more_btn.configure(text="收起 ▴" if self.more_open else "更多 ▾")
        self.more_btn.pack(side="left", padx=4)
        for k, (b, extra) in self.chips.items():
            on = self.src_on[k]
            b.configure(text=("✓ " + SRC_NAME[k]) if on else SRC_NAME[k],
                        fg_color=CHIP_ON if on else PANEL,
                        text_color=CHIP_ON_TX if on else SUB,
                        border_color=CHIP_ON if on else LINE,
                        hover_color=CHIP_ON if on else PANEL2)

    def toggle_src(self, k):
        self.src_on[k] = not self.src_on[k]
        self.save_settings()
        self.layout_chips()

    def toggle_more(self):
        self.more_open = not self.more_open
        self.layout_chips()

    def build_settings(self, parent):
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14, border_width=1, border_color=LINE)
        f.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(f, text="設定", font=F(22, bold=True), text_color=TX
                     ).grid(row=0, column=0, columnspan=3, sticky="w", padx=24, pady=(20, 4))
        self.btn(f, "回到搜尋", lambda: self.show_mode("search"), primary=True, width=130
                 ).grid(row=0, column=3, sticky="e", padx=24, pady=(20, 4))
        ctk.CTkLabel(f, text="台灣觀光署不用金鑰。其他圖庫：按「申請金鑰」→ 用 Email 註冊 → 複製金鑰貼到格子裡按 Enter",
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
            self.key_entries[order[(order.index(k) + 1) % len(order)]].focus_set()
        if val == self.keys.get(k, "") and not move:
            return
        if not val:
            self.keys.pop(k, None)
            self.save_settings()
            self.paint_key_status(k)
            return
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

    # ---------- 模式
    def show_mode(self, mode):
        self.mode = mode
        self.scroll.grid_forget()
        self.settings_frame.grid_forget()
        self.empty_lbl.grid_forget()
        if mode == "settings":
            self.settings_frame.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            self.toolbar.grid_remove()
            self.detail.grid_remove()
            return
        self.toolbar.grid()
        self.detail.grid()
        self.scroll.grid(row=0, column=0, sticky="nsew")
        if mode == "favs":
            self.b_fav.pack_forget()
            self.b_unfav.pack(side="left", padx=4, after=self.b_dl)
            self.b_view.configure(text="回到搜尋結果")
            self.more_lbl.configure(text="")
        else:
            self.b_unfav.pack_forget()
            self.b_fav.pack(side="left", padx=4, after=self.b_dl)
            self.b_view.configure(text=f"我的收藏（{len(self.favs)}）")
            self.more_lbl.configure(text="往下捲會自動載入更多")
        self.rebuild_all()

    def toggle_favs(self):
        self.checked.clear()
        self.current = None
        self.update_dl()
        self.show_mode("search" if self.mode == "favs" else "favs")

    # ---------- 圖片牆
    def section_keys(self):
        return ["fav"] if self.mode == "favs" else [s for s, _ in SECTIONS]

    def section_items(self, sk):
        return list(self.favs.values()) if sk == "fav" else self.items[sk]

    def rebuild_all(self):
        for sk, sec in self.sec.items():
            for c in sec["cards"]:
                c["frame"].destroy()
            sec["cards"] = []
            sec["head"].grid_forget()
            sec["grid"].grid_forget()
            sec["note"].grid_forget()
        for sk in self.section_keys():
            self.append_cards(sk)
        self.refresh_sections()
        try:
            self.scroll._parent_canvas.yview_moveto(0)
        except Exception:
            pass

    def refresh_sections(self):
        any_items = False
        for sk in self.section_keys():
            sec = self.sec[sk]
            n = len(self.section_items(sk))
            row = sec["row"]
            if n == 0 and not (self.searching and sk != "fav"):
                sec["head"].grid_forget()
                sec["grid"].grid_forget()
                sec["note"].grid_forget()
                continue
            any_items = any_items or n > 0
            sec["head"].grid(row=row, column=0, sticky="ew", pady=(14, 6), padx=(0, 8))
            sec["cnt"].configure(text=f"{n} 張" if n else "")
            if n:
                sec["note"].grid_forget()
                sec["grid"].grid(row=row + 1, column=0, sticky="ew", padx=(0, 8))
            else:
                sec["grid"].grid_forget()
                sec["note"].configure(text="搜尋中…")
                sec["note"].grid(row=row + 2, column=0, sticky="w", padx=10, pady=4)
        if any_items or self.searching:
            self.empty_lbl.grid_forget()
        else:
            if self.mode == "favs":
                msg = "收藏是空的。勾選圖片後按「收藏已勾選」，就會出現在這裡。"
            elif self.query_en or self.query_zh:
                msg = "沒有找到，可以換個關鍵字，或多勾選幾個來源"
            else:
                msg = "輸入關鍵字，按 Enter 開始搜尋"
            self.empty_lbl.configure(text=msg)
            self.empty_lbl.grid(row=0, column=0)

    def append_cards(self, sk):
        sec = self.sec[sk]
        items = self.section_items(sk)
        for it in items[len(sec["cards"]):]:
            i = len(sec["cards"])
            card = self.make_card(sec["grid"], it)
            card["frame"].grid(row=i // COLS, column=i % COLS, sticky="nsew", padx=6, pady=6)
            sec["cards"].append(card)
            self.cards.append(card)

    def thumb_size(self):
        return self.thumb_w, int(self.thumb_w * 0.66)

    def make_card(self, parent, it):
        f = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14, border_width=1, border_color=LINE)
        f.grid_columnconfigure(0, weight=1)
        img = ctk.CTkLabel(f, text="", fg_color="transparent", cursor="hand2")
        img.grid(row=0, column=0, padx=10, pady=(10, 4))
        var = tk.BooleanVar(value=it.key in self.checked)
        max_em = max(6, (self.thumb_w - 36) / 16.5)
        cb = ctk.CTkCheckBox(f, text=short(it.title, max_em), variable=var, font=F(16, bold=True),
                             text_color=TX, checkbox_width=24, checkbox_height=24, corner_radius=6,
                             fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=SUB)
        cb.grid(row=1, column=0, sticky="w", padx=12)
        meta = ctk.CTkFrame(f, fg_color="transparent")
        meta.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 10))
        ctk.CTkLabel(meta, text=SRC_NAME.get(it.source, it.source), font=F(14),
                     text_color=SUB).pack(side="left")
        bg, fg = {"ok": (OK_BG, OK_TX), "warn": (WARN_BG, WARN_TX)}.get(it.level, (UNK_BG, UNK_TX))
        ctk.CTkLabel(meta, text=f"  {it.lic}  ", font=F(13), corner_radius=6, height=24,
                     fg_color=bg, text_color=fg).pack(side="right")
        card = {"frame": f, "img": img, "var": var, "cb": cb, "item": it, "shown": None}
        img.bind("<Button-1>", lambda e, c=card: self.select(c))
        img.bind("<Double-Button-1>", lambda e, c=card: self.preview(c["item"]))
        cb.configure(command=lambda c=card: self.on_check(c))
        self.show_thumb(card)
        return card

    def on_resize(self, event):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(150, self.apply_resize)

    def scale(self):
        try:
            return ctk.ScalingTracker.get_widget_scaling(self.scroll)
        except Exception:
            return 1.0

    def apply_resize(self):
        self._resize_job = None
        w = self.content.winfo_width() / self.scale() - 24
        tw = int(max(150, (w - 30) / COLS - 34))
        if abs(tw - self.thumb_w) < 4:
            return
        self.thumb_w = tw
        max_em = max(6, (tw - 36) / 16.5)
        for c in self.cards:
            if c["frame"].winfo_exists():
                c["cb"].configure(text=short(c["item"].title, max_em))
                self.show_thumb(c)

    def show_thumb(self, card):
        it = card["item"]
        tw, th = self.thumb_size()
        sig = (it.key, tw)
        if card["shown"] == sig:
            return
        s = self.scale()
        size = (max(1, int(tw * s)), max(1, int(th * s)))
        pil = self.pil.get(it.key)
        if pil is None:
            card["img"].configure(image=self.placeholder(tw, th))
            card["img"]._keep = self.ph_img[1]
            self.load_thumb(it)
            return
        fitted = ImageOps.fit(pil, size, Image.LANCZOS)
        im = ctk.CTkImage(light_image=rounded(fitted, PANEL[0], int(10 * s)),
                          dark_image=rounded(fitted, PANEL[1], int(10 * s)), size=(tw, th))
        card["img"].configure(image=im)
        card["img"]._keep = im
        card["shown"] = sig

    def placeholder(self, tw, th):
        if not self.ph_img or self.ph_img[0] != (tw, th):
            s = self.scale()
            sz = (max(1, int(tw * s)), max(1, int(th * s)))
            l = rounded(Image.new("RGB", sz, PH[0]), PANEL[0], int(10 * s))
            d = rounded(Image.new("RGB", sz, PH[1]), PANEL[1], int(10 * s))
            self.ph_img = ((tw, th), ctk.CTkImage(light_image=l, dark_image=d, size=(tw, th)))
        return self.ph_img[1]

    def load_thumb(self, it):
        if it.key in self.loading:
            return
        self.loading.add(it.key)

        def job():
            try:
                if it.thumb == "mock":
                    colors = ["#B9A88E", "#8FA9BF", "#A7B98F", "#C4A9A0", "#9DA6B8", "#B7AE8F"]
                    im = Image.new("RGB", (600, 400), colors[sum(map(ord, it.key)) % 6])
                    dr = ImageDraw.Draw(im)
                    dr.ellipse([420, 50, 510, 140], fill="#F2E3B3")
                    dr.polygon([(0, 400), (200, 190), (360, 400)], fill="#6F7F63")
                    dr.polygon([(230, 400), (420, 230), (600, 400)], fill="#58684F")
                else:
                    r = requests.get(it.thumb, headers=IMG_UA, timeout=25)
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.thumbnail((700, 700))
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
                        if c["item"].key == a and c["frame"].winfo_exists():
                            self.show_thumb(c)
                elif kind == "thumbfail":
                    pass
                elif kind == "translated":
                    self.en_entry.delete(0, "end")
                    if a:
                        self.en_entry.insert(0, a)
                elif kind == "results":
                    self.merge_results(a, b)
                elif kind == "status":
                    self.set_status(a)
                elif kind == "dl_progress":
                    self.bar_msg(f"下載中 {a} / {b}…", "busy")
                elif kind == "done_download":
                    self.after_download(a, b)
                elif kind == "key_ok":
                    self.keys[a] = b
                    self.save_settings()
                    self.paint_key_status(a)
                elif kind == "key_bad":
                    self.paint_key_status(a, "bad")
                elif kind == "key_net":
                    self.paint_key_status(a, "neterr")
                elif kind == "open":
                    for u in a:
                        webbrowser.open(u)
        except queue.Empty:
            pass
        self.cards = [c for c in self.cards if c["frame"].winfo_exists()]
        self.check_scroll_end()
        self.root.after(120, self.poll)

    def check_scroll_end(self):
        if self.mode != "search" or self.searching or self.exhausted or not self.seen:
            return
        if time.time() - self.last_merge < 1.5:
            return
        if len(self.seen) >= MAX_ITEMS:
            self.exhausted = True
            self.more_lbl.configure(text=f"已顯示 {MAX_ITEMS} 張，想看更多請換個關鍵字")
            return
        try:
            cv = self.scroll._parent_canvas
            bbox = cv.bbox("all")
            if not bbox or bbox[3] - bbox[1] <= cv.winfo_height() + 20:
                return
            bottom = cv.yview()[1]
        except Exception:
            return
        if bottom > 0.93:
            self.load_more()

    def set_status(self, s):
        self.status.configure(text=s)

    # ---------- 搜尋
    def active_sources(self):
        return [s for s in SOURCES if self.src_on[s[0]]]

    def start_search(self, from_en):
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
        self.search_id += 1
        sid = self.search_id
        self.items = {s: [] for s, _ in SECTIONS}
        self.seen, self.fetch_page, self.exhausted = set(), 0, False
        self.current = None
        self.update_dl()
        self.searching = True
        self.query_en = self.query_zh = ""
        self.mode = "search"
        self.show_mode("search")
        self.set_status("搜尋中…")

        def job():
            q_en = en if from_en else text
            q_zh = text if CJK.search(text) else ""
            try:
                if not from_en and q_zh:
                    self.q.put(("status", "翻譯成英文中…", None))
                    q_en = translate(text, "zh-TW", "en")
                if not q_zh:
                    q_zh = translate(q_en, "en", "zh-TW")
            except Exception:
                self.q.put(("status", "翻譯失敗，可以自己在英文欄輸入後按 Enter", None))
            if not from_en:
                self.q.put(("translated", q_en, None))
            self.query_en, self.query_zh = q_en, q_zh or text
            self.fetch_round(srcs, sid)
        threading.Thread(target=job, daemon=True).start()

    def fetch_round(self, srcs, sid):
        self.fetch_page += 1
        page = self.fetch_page
        qe, qz = self.query_en, self.query_zh
        jobs, nokey = [], []
        for k, name, fn, need, d, x, intl in srcs:
            key = self.keys.get(k, "")
            if need and not key:
                nokey.append(name)
                continue
            if k == "tw":
                jobs.append(("tw", name, fn, qz, key))
            elif intl:
                jobs.append(("tw", name, fn, f"{qe} Taiwan", key))
                jobs.append(("asia", name, fn, f"{qe} Asia", key))
                if k == "pixabay":
                    jobs.append(("asia", name, fn, f"{qe} Japan", key))
                jobs.append(("other", name, fn, qe, key))
            else:
                jobs.append(("other", name, fn, qe, key))
        if any(x[0] == "tw" for x in srcs) and not MOCK:
            try:
                TW.ensure(lambda s: self.q.put(("status", s, None)))
            except Exception:
                pass

        def run(j):
            sec, name, fn, q, key = j
            try:
                return sec, name, fn(q, page, key), None
            except Exception as ex:
                return sec, name, [], str(ex)
        results, errors = [], []
        with ThreadPoolExecutor(8) as ex:
            for sec, name, items, err in ex.map(run, jobs):
                results.append((sec, items))
                if err:
                    errors.append(name)
        self.q.put(("results", (sid, results), (sorted(set(errors)), nokey)))

    def merge_results(self, data, info):
        sid, results = data
        if sid != self.search_id:
            return
        errors, nokey = info
        self.searching = False
        self.last_merge = time.time()
        added = 0
        buckets = {s: [] for s, _ in SECTIONS}
        for sec, items in results:
            if QUALITY["on"]:
                items = [x for x in items if x.source == "tw" or not x.width or x.width >= MIN_W]
            buckets[sec].append(items)
        batch = {}
        for sk, _ in SECTIONS:
            lists = buckets[sk]
            i = 0
            while any(i < len(l) for l in lists):
                for l in lists:
                    if i < len(l):
                        it = l[i]
                        if it.key in self.seen or not it.full:
                            continue
                        target = sk
                        if sk == "other":
                            target = region_of(f"{it.title} {it.place}") or "other"
                        self.seen.add(it.key)
                        batch.setdefault(target, []).append(it)
                        added += 1
                i += 1
        for target, its in batch.items():
            if QUALITY["on"]:
                tw_first = [x for x in its if x.source == "tw"]
                rest = sorted([x for x in its if x.source != "tw"], key=lambda x: -x.pop)
                # 台灣觀光署與其他圖庫交錯，熱門的排前面
                mixed, a, b = [], 0, 0
                while a < len(tw_first) or b < len(rest):
                    if a < len(tw_first):
                        mixed.append(tw_first[a]); a += 1
                    for _ in range(2):
                        if b < len(rest):
                            mixed.append(rest[b]); b += 1
                its = mixed
            self.items[target].extend(its)
        if added == 0:
            self.exhausted = True
        if self.mode == "search":
            for sk, _ in SECTIONS:
                self.append_cards(sk)
            self.refresh_sections()
        total = sum(len(v) for v in self.items.values())
        parts = [f"找到 {total} 張"] if total else ["沒有找到，可以換個關鍵字試試"]
        if nokey:
            parts.append(f"{'、'.join(nokey)} 還沒設定金鑰")
        if errors:
            parts.append(f"連不上：{'、'.join(errors)}")
        self.set_status("。".join(parts))

    def load_more(self):
        if self.searching or self.exhausted:
            return
        self.searching = True
        self.set_status("載入更多…")
        srcs = self.active_sources()
        sid = self.search_id
        threading.Thread(target=lambda: self.fetch_round(srcs, sid), daemon=True).start()

    def on_quality(self):
        QUALITY["on"] = self.hq_var.get()
        self.settings["quality"] = QUALITY["on"]
        self.save_settings()
        if self.q_entry.get().strip() or self.en_entry.get().strip():
            self.start_search(bool(self.en_entry.get().strip()) and not self.q_entry.get().strip())

    def toggle_sites(self):
        self.sites_open = not self.sites_open
        if self.sites_open:
            self.sites.grid(row=4, column=0, sticky="ew", padx=24, pady=(10, 0))
            self.b_sites.configure(text="收起網站 ▴")
        else:
            self.sites.grid_forget()
            self.b_sites.configure(text="其他網站 ↗")

    SITE_URLS = {
        "colorhub": ("zh-CN", "https://www.colorhub.me/search?tag={}"),
        "pakutaso": ("ja", "https://www.pakutaso.com/search.html?offset=0&limit=all&search={}"),
        "photoac": ("ja", "https://www.photo-ac.com/main/search?q={}"),
        "stocksnap": ("en", "https://stocksnap.io/search/{}"),
        "burst": ("en", "https://www.shopify.com/stock-photos/photos/search?q={}"),
        "isorepublic": ("en", "https://isorepublic.com/?s={}&post_type=photo"),
    }

    def open_site(self, site):
        text = self.q_entry.get().strip() or self.en_entry.get().strip()
        if not text:
            self.bar_msg("請先在上面輸入關鍵字", "err")
            return
        lang, pattern = self.SITE_URLS[site]
        en = self.en_entry.get().strip()

        def job():
            q = text
            try:
                if lang == "en":
                    q = en or translate(text, "auto", "en")
                elif lang == "ja":
                    q = translate(text, "auto", "ja")
                elif lang == "zh-CN":
                    q = translate(text, "auto", "zh-CN")
            except Exception:
                pass
            qs = urllib.parse.quote(q) if site != "stocksnap" else urllib.parse.quote(q.replace(" ", "-"))
            self.q.put(("open", [pattern.format(qs)], None))
            self.q.put(("status", f"已在瀏覽器打開（關鍵字：{q}）", None))
        threading.Thread(target=job, daemon=True).start()

    # ---------- 勾選與選取
    def targets(self):
        """要處理的照片：有打勾就是打勾的；沒有就是藍框選中的那一張。"""
        if self.checked:
            return list(self.checked.values())
        return [self.current] if self.current else []

    def update_dl(self):
        n = len(self.checked)
        if n:
            self.b_dl.configure(text=f"下載已勾選（{n}）")
            self.b_fav.configure(text=f"收藏已勾選（{n}）")
            self.b_unfav.configure(text=f"移除已勾選（{n}）")
        elif self.current:
            self.b_dl.configure(text="下載這張")
            self.b_fav.configure(text="收藏這張")
            self.b_unfav.configure(text="移除這張收藏")
        else:
            self.b_dl.configure(text="下載")
            self.b_fav.configure(text="收藏")
            self.b_unfav.configure(text="移除收藏")

    def on_check(self, card):
        it = card["item"]
        if card["var"].get():
            self.checked[it.key] = it
        else:
            self.checked.pop(it.key, None)
        self.update_dl()

    def check_section(self, sk):
        for c in self.sec[sk]["cards"]:
            self.checked[c["item"].key] = c["item"]
            c["var"].set(True)
        self.update_dl()

    def uncheck_all(self):
        self.checked.clear()
        for c in self.cards:
            c["var"].set(False)
        self.update_dl()

    def select(self, card):
        it = card["item"]
        for c in self.cards:
            if c["item"] is self.current and c["frame"].winfo_exists():
                c["frame"].configure(border_color=LINE, border_width=1)
        self.current = it
        card["frame"].configure(border_color=ACCENT, border_width=3)
        self.det_title.configure(text=short(it.title, 28))
        info = [SRC_NAME.get(it.source, it.source)]
        if it.place and it.source == "tw":
            info.append(it.place)
        if it.creator and it.source != "tw":
            info.append(f"攝影：{it.creator}")
        if it.size:
            info.append(it.size)
        info.append(it.lic)
        self.det_info.configure(text="　·　".join(info))
        self.update_dl()

    def open_page(self):
        if self.current and self.current.page:
            webbrowser.open(self.current.page)

    def preview(self, it):
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
                if it.full == "mock":
                    im = self.pil.get(it.key) or Image.new("RGB", (1200, 800), "#8FA9BF")
                else:
                    r = requests.get(it.full, headers=IMG_UA, timeout=60)
                    r.raise_for_status()
                    im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im = im.copy()
                im.thumbnail((2000, 2000))

                def show():
                    if win.winfo_exists():
                        w, h = im.size
                        k = min(1060 / w, 700 / h, 1.0)
                        ci = ctk.CTkImage(light_image=im, dark_image=im, size=(int(w * k), int(h * k)))
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
            self.bar_msg("請先勾選照片，或點一下照片", "err")
            return
        for x in items:
            self.favs[x.key] = x
        self.save_favs()
        self.set_status(f"已收藏 {len(items)} 張")
        self.bar_msg(f"✓ 已收藏 {len(items)} 張", "ok")
        if self.mode == "search":
            self.b_view.configure(text=f"我的收藏（{len(self.favs)}）")

    def fav_checked(self):
        self.add_favs(self.targets())

    def unfav_checked(self):
        items = self.targets()
        if not items:
            self.bar_msg("請先勾選或點選要移除的收藏", "err")
            return
        if not messagebox.askyesno(APP_NAME, f"確定要從收藏移除 {len(items)} 張嗎？\n（已下載的檔案不會被刪除）"):
            return
        for x in items:
            self.favs.pop(x.key, None)
        self.checked.clear()
        self.current = None
        self.update_dl()
        self.save_favs()
        self.rebuild_all()

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

    def bar_msg(self, text, kind="info"):
        color = {"info": SUB, "ok": OK_TX, "err": DANGER, "busy": ACCENT}[kind]
        self.more_lbl.configure(text=text, text_color=color,
                                font=F(16, bold=kind in ("ok", "err", "busy")))

    def download_checked(self):
        self.download_items(self.targets())

    def download_items(self, items):
        items = [x for x in items if x]
        if not items:
            self.bar_msg("請先勾選照片，或點一下照片", "err")
            self.set_status("請先勾選要下載的照片")
            return
        d = Path(self.folder())
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception as ex:
            self.bar_msg(f"無法建立下載資料夾：{d}", "err")
            return
        self.bar_msg(f"下載中 0 / {len(items)}…", "busy")
        keys = dict(self.keys)

        def job():
            rows, errors, done = [], [], [0]
            lock = threading.Lock()

            def one(it):
                try:
                    name, row = download_one(it, d, keys)
                    with lock:
                        rows.append(row)
                except Exception as ex:
                    msg = str(ex)
                    if isinstance(ex, requests.HTTPError) and ex.response is not None:
                        msg = f"HTTP {ex.response.status_code}"
                    with lock:
                        errors.append((it, msg))
                with lock:
                    done[0] += 1
                    n = done[0]
                self.q.put(("dl_progress", n, len(items)))
            with ThreadPoolExecutor(4) as ex:
                list(ex.map(one, items))
            if rows:
                credit = d / "出處紀錄.csv"
                new = not credit.exists()
                try:
                    with open(credit, "a", newline="", encoding="utf-8-sig") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(["檔名", "標題", "來源", "授權", "攝影／出處", "出處網址"])
                        w.writerows(rows)
                except Exception:
                    pass
            if errors:
                try:
                    with open(data_dir() / "download_errors.log", "a", encoding="utf-8") as f:
                        for it, msg in errors:
                            f.write(f"{time.strftime('%Y-%m-%d %H:%M')}\t{it.source}\t{msg}\t{it.full}\n")
                except Exception:
                    pass
            self.q.put(("done_download", len(rows), errors))
        threading.Thread(target=job, daemon=True).start()

    def after_download(self, ok, errors):
        fail = len(errors)
        short_dir = self.folder().replace(str(Path.home()), "").strip("\\/") or self.folder()
        if ok and not fail:
            self.bar_msg(f"✓ 已下載 {ok} 張到「{short_dir}」", "ok")
        elif ok:
            self.bar_msg(f"已下載 {ok} 張，{fail} 張失敗", "err")
        else:
            self.bar_msg(f"下載失敗（{errors[0][1][:30]}）", "err")
        self.set_status(f"下載完成：成功 {ok} 張" + (f"，失敗 {fail} 張" if fail else ""))
        self.uncheck_all()
        if SMOKE:
            return
        if ok:
            msg = f"已下載 {ok} 張到：\n{self.folder()}"
        else:
            msg = "這次沒有下載成功。"
        if fail:
            srcs = "、".join(sorted({SRC_NAME.get(it.source, it.source) for it, _ in errors}))
            msg += f"\n\n有 {fail} 張失敗（來源：{srcs}，原因：{errors[0][1][:60]}）。\n可以稍後再試，或按「出處頁」在瀏覽器下載。"
        if ok:
            msg += "\n\n每張的來源和授權記在資料夾裡的「出處紀錄.csv」。\n\n要開啟下載資料夾嗎？"
            if messagebox.askyesno(APP_NAME, msg):
                self.open_folder()
        else:
            messagebox.showwarning(APP_NAME, msg)


def smoke_run(root, app):
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
        app.q_entry.insert(0, "飯店")
        app.start_search(False)
        root.after(4000, step2)

    def step2():
        cards = app.sec["tw"]["cards"]
        if cards:
            cards[0]["var"].set(True)
            app.on_check(cards[0])
            app.select(cards[0])
        root.after(1500, lambda: (shot("results"), step3()))

    def step3():
        app.toggle_sites()
        app.scroll._parent_canvas.yview_moveto(0.45)
        root.after(1500, lambda: (shot("scrolled"), step4()))

    def step4():
        app.download_checked()
        root.after(1500, lambda: (shot("downloaded"), step4b()))

    def step4b():
        app.show_mode("settings")
        root.after(1000, lambda: (shot("settings"), step5()))

    def step5():
        print("SMOKE sections", {k: len(v) for k, v in app.items.items()})
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
        root.after(50, lambda: root.state("zoomed"))
    root.mainloop()


if __name__ == "__main__":
    main()
