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
