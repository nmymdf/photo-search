import photo_search as ps
print("translate:", ps.translate_zh_en("老火車"))
for k, name, fn, zh, cat in ps.SOURCES:
    try:
        items = fn("steam locomotive", 1, True)
        print(f"{name}: {len(items)}", items[0].title if items else "", items[0].lic if items else "", items[0].thumb if items else "")
        if items:
            print("   full:", ps.full_url(items[0]))
    except Exception as e:
        print(f"{name}: ERROR {e}")

for free in (True, False):
    for q in ("train", "landscape"):
        try:
            print("cleveland", q, free, len(ps.src_cleveland(q, 1, free)))
        except Exception as e:
            print("cleveland ERR", e)
try:
    import requests
    r = requests.get("https://openaccess-api.clevelandart.org/api/artworks/", params={"q": "train", "limit": 1}, timeout=20)
    print("cleveland raw", r.status_code, r.text[:600])
except Exception as e:
    print("raw err", e)
for k, name, fn, zh, cat in ps.SOURCES:
    if k == "loc":
        it = fn("steam locomotive", 1, True)[0]
        r = ps.get_with_fallback(ps.full_url(it), it, 60)
        print("loc full bytes", len(r.content), r.url)
