import json, requests, io, zipfile
H={"User-Agent":"Mozilla/5.0 ClassicPhotoSearch"}
for ds in (7777, 7780, 7778):
    d=requests.get(f"https://data.gov.tw/api/v2/rest/dataset/{ds}", headers=H, timeout=60).json()
    for x in d["result"]["distribution"]:
        print(ds, x.get("resourceDescription"), x.get("resourceFormat"), x.get("resourceDownloadUrl"))
d=requests.get("https://data.gov.tw/api/v2/rest/dataset/7777", headers=H, timeout=60).json()
for x in d["result"]["distribution"]:
    u=x.get("resourceDownloadUrl")
    if (x.get("resourceFormat") or "").upper()=="JSON" or u.lower().endswith(".json"):
        r=requests.get(u, headers=H, timeout=180)
        print("GOT", u, r.status_code, len(r.content), r.headers.get("Content-Type"))
        txt=r.content.decode("utf-8-sig", "replace")
        print(txt[:2500])
        try:
            j=json.loads(txt)
            def walk(o, depth=0):
                if isinstance(o, dict):
                    print("  "*depth, "dict keys:", list(o.keys())[:25])
                    for k,v in list(o.items())[:3]:
                        if isinstance(v,(dict,list)): walk(v, depth+1)
                elif isinstance(o, list):
                    print("  "*depth, "list len", len(o))
                    if o: walk(o[0], depth+1)
            walk(j)
        except Exception as e:
            print("json err", e)
        break
