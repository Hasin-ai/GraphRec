"""End-to-end check of a running Reel storefront against the live GraphRec API.

Runs the demo acts through Reel's HTTP API (as the browser would) and prints what
GraphRec answered. Uses a fresh anonymous session, then Sam. NOTE: Act 3 adds three
permanent events to Sam's history (Maya stays clean for the demo) in this tenant; re-run bootstrap_reel.py to reset.

    docker cp apps/reel-storefront/scripts/e2e_check.py reel-reel-1:/tmp/ && docker exec reel-reel-1 python /tmp/e2e_check.py
"""
import http.cookiejar, json, sys, urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5290"
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
films = {}


def call(method, path, body=None):
    req = urllib.request.Request(BASE + "/api/reel" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    with op.open(req, timeout=60) as r:
        return json.loads(r.read())


def fid(title, year):
    page = call("GET", "/films?q=" + urllib.parse.quote(title) + "&limit=20")["data"]["items"]
    return next(f["id"] for f in page if f["title"] == title and f["year"] == year)


def recs(label):
    d = call("POST", "/recommendations", {"shelf": "home"})["data"]
    if d.get("available") is False:
        print(f"{label}: UNAVAILABLE {d}"); sys.exit(1)
    t = d["trace"]
    print(f"{label}: {d['title']} | strategy={t['strategy']} fallback={t['fallbackUsed']} "
          f"version={t['modelVersionId']} {t['latencyMs']}ms | {d['diff']['summary']}")
    print("   " + " | ".join(i["title"] for i in d["items"]))
    return d


import urllib.parse  # noqa: E402
call("GET", "/session")
a1 = recs("Act 1 anonymous")
for t, y in [("Tarzan", 1999), ("Emperor's New Groove, The", 2000)]:
    r = call("POST", "/watch", {"filmId": fid(t, y)})["data"]
    print(f"   watch {t}: accepted={r['accepted']} duplicate={r['duplicate']} {r['latencyMs']}ms")
a1b = recs("Act 1 after 2 films")
s = call("POST", "/session/persona", {"persona": "sam", "carrySession": True})
print(f"Act 2 carried {len(s['meta']['carried'])} events into Sam")
recs("Act 2 Sam")
for t, y in [("Gattaca", 1997), ("Contact", 1997), ("Dark City", 1998)]:
    call("POST", "/watch", {"filmId": fid(t, y)})
a3 = recs("Act 3 Sam after 3 sci-fi")
dup = call("POST", "/watch/replay")["data"]
print(f"Act 5 replay: accepted={dup['accepted']} duplicate={dup['duplicate']}")
seq = call("GET", "/insight/sequence")["data"]
print(f"Sequence: {seq['total']} events, {seq['liveCount']} live, window {sum(i['inWindow'] for i in seq['items'])}/{seq['window']}")
st = call("GET", "/insight/status")["data"]
print(f"Status: tenant={st['tenant']} graphrec={st['graphrec']} version={st['modelVersionTag']}")
ok = (a1["trace"]["fallbackUsed"] and a1b["trace"]["strategy"] == "session" and a3["trace"]["strategy"] == "personalized"
      and a3["diff"]["changed"] > 0 and dup["duplicate"])
print("RESULT:", "PASS" if ok else "CHECK OUTPUT")
