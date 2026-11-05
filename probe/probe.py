import json, requests
H={"User-Agent":"Mozilla/5.0 ClassicPhotoSearch"}
def show(u, n=1500, **kw):
    try:
        r=requests.get(u, headers=H, timeout=60, **kw)
        print("==", u, r.status_code, r.headers.get("Content-Type"), len(r.content))
        print(r.text[:n])
        return r
    except Exception as e:
        print("== ERR", u, e)
for ds in (7777, 7778, 7779, 7780):
    r=show(f"https://data.gov.tw/api/v2/rest/dataset/{ds}", 2500)
for u in ["https://tcmbdata.culture.tw/opendata/openapi/cultureMedia?search=飯店&page=0&size=2",
          "https://tcmbdata.culture.tw/opendata/openapi/cultureObject?search=廟&page=0&size=2",
          "https://tcmbdata.culture.tw/opendata/openapi/culturePlace?search=日月潭&page=0&size=2",
          "https://tcmbdata.culture.tw/opendata/dataSet/culture?page=0&size=1"]:
    show(u, 3000)
r=requests.get("https://tcmbdata.culture.tw/v3/api-docs", headers=H, timeout=30)
d=r.json()
for p in ("/opendata/openapi/cultureMedia","/opendata/openapi/culturePlace"):
    print(p, json.dumps(d["paths"][p], ensure_ascii=False)[:1500])
print(json.dumps(d.get("components",{}).get("securitySchemes",{})))
for u in ["https://www.pakutaso.com/search.html?offset=0&limit=all&search=%E3%83%9B%E3%83%86%E3%83%AB",
          "https://www.photo-ac.com/main/search?q=%E3%83%9B%E3%83%86%E3%83%AB"]:
    show(u, 300)
