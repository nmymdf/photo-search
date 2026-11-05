import requests, urllib.parse as up
B={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
U={"User-Agent":"ClassicPhotoSearch/0.4 (personal desktop app)"}
def g(u, h=B, **kw):
    try:
        r=requests.get(u, headers=h, timeout=30, **kw)
        return r
    except Exception as e:
        print("ERR", u, e); return None
for path in ["images/search?query=hotel","images/search?q=hotel","search?query=hotel","images?query=hotel"]:
    r=g("https://api.lummi.ai/v1/"+path)
    if r is not None: print("LUMMI", path, r.status_code, r.text[:150])
for ps in (20, 24):
    r=g("https://api.openverse.org/v1/images/", U, params={"q":"hotel taiwan","page_size":ps,"license":"cc0,pdm,by,by-sa","size":"large"})
    print("OV", ps, r.status_code, r.text[:200])
for pg in (2,5,12):
    r=g("https://api.openverse.org/v1/images/", U, params={"q":"hotel","page_size":20,"page":pg})
    print("OVpage", pg, r.status_code, r.text[:120])
r=g("https://commons.wikimedia.org/w/api.php", U, params={"action":"query","format":"json","list":"search","srsearch":'hotel Taiwan incategory:"Quality_images"',"srnamespace":6,"srlimit":5})
print("COMMONS-Q", r.status_code, r.text[:400])
r=g("https://commons.wikimedia.org/w/api.php", U, params={"action":"query","format":"json","list":"search","srsearch":'hotel incategory:"Quality_images"',"srnamespace":6,"srlimit":5})
print("COMMONS-Q2", r.status_code, r.text[:300])
q="hotel"; zh="酒店"; ja="ホテル"
sites={
 "colorhub":f"https://www.colorhub.me/search?tag={up.quote(zh)}",
 "cc0cn":f"https://www.cc0.cn/s/{up.quote(zh)}/",
 "cc0cn2":f"https://www.cc0.cn/search/?s={up.quote(zh)}",
 "photock":f"https://www.photock.jp/list/search/?q={up.quote(ja)}",
 "photock2":f"https://www.photock.jp/search/?q={up.quote(ja)}",
 "stocksnap":f"https://stocksnap.io/search/{q}",
 "burst":f"https://www.shopify.com/stock-photos/photos/search?q={q}",
 "burst2":f"https://burst.shopify.com/photos/search?q={q}",
 "isorepublic":f"https://isorepublic.com/?s={q}&post_type=photo",
 "pakutaso":f"https://www.pakutaso.com/search.html?offset=0&limit=all&search={up.quote(ja)}",
 "photoac":f"https://www.photo-ac.com/main/search?q={up.quote(ja)}",
}
import re
for k,u in sites.items():
    r=g(u)
    if r is None: continue
    t=re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S|re.I)
    print("SITE", k, r.status_code, r.url[:90], (t.group(1).strip()[:80] if t else ""), (zh in r.text or ja in r.text or q in r.text.lower()))
