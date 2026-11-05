import time, requests
import photo_search as ps
print("translate:", ps.translate("海邊飯店", "zh-TW", "en"), ps.translate("hotel", "en", "zh-TW"), ps.translate("海邊飯店", "auto", "ja"))
t = time.time()
ps.TW.ensure(print)
print("TW entries", len(ps.TW.entries), "load sec", round(time.time() - t, 1))
for q in ("飯店", "日月潭", "夜市", "海邊 民宿"):
    items = ps.src_tw(q, 1, "")
    print("TW", q, len(items), [i.title for i in items[:5]], [i.place for i in items[:3]])
items = ps.src_tw("飯店", 1, "")
ok = 0
for it in items[:6]:
    try:
        r = requests.get(it.thumb, headers=ps.UA, timeout=20)
        ok += r.ok
    except Exception as e:
        pass
print("TW thumbs ok", ok, "/ 6")
try:
    print("commons", len(ps.src_commons("hotel Taiwan", 1, "")))
except Exception as e:
    print("commons ERR", e)
for k in ("pexels", "unsplash", "pixabay"):
    try:
        ps.test_key(k, "badkey123")
    except requests.HTTPError as e:
        print(k, "bad key ->", e.response.status_code)
print("region", ps.region_of("Hotel in Tokyo"), ps.region_of("Taipei 101"), ps.region_of("Paris"))
import tempfile
d = tempfile.mkdtemp()
for it in ps.src_tw("日月潭", 1, "")[:3] + ps.src_commons("hotel Taiwan", 1, "")[:2]:
    try:
        name, row = ps.download_one(it, d, {})
        import os
        print("DL OK", it.source, name, os.path.getsize(os.path.join(d, name)))
    except Exception as e:
        print("DL FAIL", it.source, e, it.full)
