import json, requests, io, zipfile
H={"User-Agent":"Mozilla/5.0 ClassicPhotoSearch"}
for name in ("Attraction", "Hotel", "Event"):
    u=f"https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/{name}-json.zip"
    r=requests.get(u, headers=H, timeout=300)
    print("GOT", name, r.status_code, len(r.content))
    z=zipfile.ZipFile(io.BytesIO(r.content))
    print("FILES", z.namelist()[:5])
    raw=z.read(z.namelist()[0]).decode("utf-8-sig","replace")
    j=json.loads(raw)
    print("TOPKEYS", list(j.keys()) if isinstance(j,dict) else type(j))
    # find list of records
    def findlist(o):
        if isinstance(o,list): return o
        if isinstance(o,dict):
            for v in o.values():
                l=findlist(v)
                if l: return l
    recs=findlist(j)
    print("NREC", len(recs))
    withimg=[x for x in recs if x.get("Images")]
    print("WITHIMG", len(withimg))
    print("REC", json.dumps(withimg[0], ensure_ascii=False)[:1800])
    nimg=sum(len(x["Images"]) for x in withimg)
    print("NIMG", nimg)
    im=withimg[0]["Images"][0]
    try:
        rr=requests.get(im.get("URL") or im.get("Url"), headers=H, timeout=30)
        print("IMGFETCH", rr.status_code, rr.headers.get("Content-Type"), len(rr.content))
    except Exception as e:
        print("IMGERR", e)
