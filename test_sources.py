import json, requests
import photo_search as ps
print("translate:", ps.translate_zh_en("海邊飯店"))
for k, name, fn, need, d, x in ps.SOURCES:
    if need:
        continue
    try:
        items = fn("hotel", 1, "")
        print(f"{name}: {len(items)}", [i.title for i in items[:4]])
    except Exception as e:
        print(f"{name}: ERROR {e}")
for k in ("pexels", "unsplash", "pixabay"):
    try:
        ps.test_key(k, "badkey123")
        print(k, "bad key accepted?!")
    except requests.HTTPError as e:
        print(k, "bad key ->", e.response.status_code)
    except Exception as e:
        print(k, "other", e)
for u in ["https://tcmbdata.culture.tw/v3/api-docs", "https://tcmbdata.culture.tw/v2/api-docs"]:
    try:
        r = requests.get(u, timeout=20)
        print("TW", u, r.status_code)
        if r.ok:
            d = r.json()
            for path, v in list(d.get("paths", {}).items())[:30]:
                for m, op in v.items():
                    print("  ", m, path, [p.get("name") for p in op.get("parameters", [])])
            break
    except Exception as e:
        print("TW err", e)
