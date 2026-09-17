# -*- coding: utf-8 -*-
"""مين يعرفني أكثر — خادم محلي للعبة.
شاشة الهوست على الجهاز، واللاعبون يدخلون بالباركود من نفس شبكة الواي فاي."""

import json, os, random, socket, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from questions import CATEGORIES, TOTAL

BASE = os.path.dirname(os.path.abspath(__file__))
ROUND_SECONDS = 40
PORT_RANGE = [8000, 8080, 8090, 5000, 3000, 7777]

COLORS = [
    {"name": "أحمر",    "hex": "#E23B3B", "shape": "▲"},
    {"name": "أزرق",    "hex": "#2E6BFF", "shape": "◆"},
    {"name": "أصفر",    "hex": "#E0A200", "shape": "●"},
    {"name": "أخضر",    "hex": "#1FA463", "shape": "■"},
    {"name": "بنفسجي",  "hex": "#7C5CFF", "shape": "★"},
    {"name": "برتقالي", "hex": "#E9650F", "shape": "⬢"},
]

lock = threading.RLock()
G = {}
JOIN_URL = ""
JOIN_URLS = []


# ─────────────────────────── الحالة ───────────────────────────
def reset(keep_players=False):
    global G
    old = G if (keep_players and G) else None
    G = {
        "phase": "lobby",          # lobby pick owner compose ready play reveal end
        "mode": "solo",            # solo | teams
        "teams": ["الفريق الأزرق", "الفريق الرمادي"],
        "players": [],
        "queue": [],
        "round": -1,
        "deadline": 0,
        "hint_used": False,
        "hint": "",
        "composer": None,          # pid أو "host"
        "version": 1,
    }
    if old:
        G["mode"] = old["mode"]
        G["teams"] = list(old["teams"])
        G["players"] = [dict(p, score=0, answer=None, at=None, correct=None, gain=0)
                        for p in old["players"]]


reset()


def touch():
    G["version"] += 1


def now_ms():
    return int(time.time() * 1000)


def find(pid):
    for p in G["players"]:
        if p["id"] == pid:
            return p
    return None


def cur():
    if 0 <= G["round"] < len(G["queue"]):
        return G["queue"][G["round"]]
    return None


def base_points(q):
    return (2 if q["count"] == 6 else 1) * (2 if q.get("double") else 1)


def clear_answers():
    for p in G["players"]:
        p["answer"] = None
        p["at"] = None
        p["correct"] = None
        p["gain"] = 0


def team_score(i):
    return sum(p["score"] for p in G["players"] if p["team"] == i)


# ─────────────────────────── اللقطات ───────────────────────────
def snap_host():
    q = cur()
    qq = None
    if q:
        show = G["phase"] in ("play", "reveal", "end") or G["composer"] == "host"
        qq = {
            "text": q["text"], "cat": q["cat"], "count": q["count"],
            "owner": q["owner"], "double": q.get("double", False),
            "points": base_points(q),
            "options": q["options"] if show else [],
            "correct": q["correct"] if G["phase"] in ("reveal", "end") else None,
            "pool": q["pool"] if G["composer"] == "host" else [],
            "ready": bool(q["options"]) and q["correct"] is not None,
        }
    answered = sum(1 for p in G["players"]
                   if p["answer"] is not None and (not q or p["id"] != q["owner"]))
    eligible = sum(1 for p in G["players"] if not q or p["id"] != q["owner"])
    return {
        "v": G["version"], "now": now_ms(), "phase": G["phase"], "mode": G["mode"],
        "teams": G["teams"], "teamScores": [team_score(0), team_score(1)],
        "players": [{k: p[k] for k in ("id", "name", "team", "score", "answer", "correct", "gain")}
                    for p in G["players"]],
        "round": G["round"], "total": len(G["queue"]), "q": qq,
        "deadline": G["deadline"], "seconds": ROUND_SECONDS,
        "hint": G["hint"], "hintUsed": G["hint_used"], "composer": G["composer"],
        "answered": answered, "eligible": eligible, "colors": COLORS,
        "joinUrl": JOIN_URL, "joinUrls": JOIN_URLS,
    }


def snap_player(pid):
    p = find(pid)
    q = cur()
    out = {
        "v": G["version"], "now": now_ms(), "phase": G["phase"], "colors": COLORS,
        "joined": bool(p), "deadline": G["deadline"], "seconds": ROUND_SECONDS,
        "count": q["count"] if q else 4,
        "teams": G["teams"], "mode": G["mode"],
    }
    if not p:
        return out
    out["me"] = {"id": p["id"], "name": p["name"], "team": p["team"],
                 "score": p["score"], "answer": p["answer"],
                 "correct": p["correct"], "gain": p["gain"]}
    out["isOwner"] = bool(q and q["owner"] == p["id"])
    if q and G["composer"] == pid and G["phase"] == "compose":
        out["compose"] = {"text": q["text"], "pool": q["pool"], "count": q["count"],
                          "options": q["options"], "correct": q["correct"],
                          "cat": q["cat"], "double": q.get("double", False)}
    if q and G["phase"] in ("reveal", "end"):
        out["result"] = {"correct": q["correct"], "points": base_points(q)}
    if G["phase"] == "end":
        ranked = sorted(G["players"], key=lambda x: -x["score"])
        out["rank"] = [r["id"] for r in ranked]
    return out


# ─────────────────────────── الأوامر ───────────────────────────
def act(a):
    t = a.get("action")

    # ---------- اللاعبون ----------
    if t == "join":
        name = (a.get("name") or "").strip()[:20]
        if not name:
            return {"error": "الاسم مطلوب"}
        same = next((p for p in G["players"] if p["name"] == name), None)
        if same:
            return {"pid": same["id"]}
        pid = "p%d%03d" % (len(G["players"]) + 1, random.randint(0, 999))
        G["players"].append({"id": pid, "name": name, "team": len(G["players"]) % 2,
                             "score": 0, "answer": None, "at": None,
                             "correct": None, "gain": 0})
        touch()
        return {"pid": pid}

    if t == "answer":
        p, q = find(a.get("pid")), cur()
        if not (p and q) or G["phase"] != "play":
            return {"error": "مو وقت الإجابة"}
        if p["id"] == q["owner"] or p["answer"] is not None:
            return {"ok": True}
        if now_ms() > G["deadline"] + 900:
            return {"error": "انتهى الوقت"}
        i = int(a.get("index", -1))
        if 0 <= i < q["count"]:
            p["answer"] = i
            p["at"] = now_ms()
            touch()
        return {"ok": True}

    if t == "submit_compose":
        q = cur()
        if not q or G["phase"] != "compose":
            return {"error": "مو وقت الكتابة"}
        if G["composer"] not in ("host", a.get("pid")):
            return {"error": "مو دورك"}
        opts = [str(x).strip()[:60] for x in a.get("options", [])]
        count = 6 if int(a.get("count", 4)) == 6 else 4
        correct = a.get("correct")
        opts = (opts + [""] * count)[:count]
        if any(not o for o in opts) or correct is None or not (0 <= int(correct) < count):
            return {"error": "عبّي كل الخيارات وحدد الصح"}
        q["count"], q["options"], q["correct"] = count, opts, int(correct)
        G["phase"] = "ready"
        touch()
        return {"ok": True}

    # ---------- الهوست ----------
    if t == "set_mode":
        G["mode"] = "teams" if a.get("mode") == "teams" else "solo"
    elif t == "set_team_name":
        i = 1 if int(a.get("i", 0)) else 0
        G["teams"][i] = (a.get("name") or "").strip()[:20] or G["teams"][i]
    elif t == "set_team":
        p = find(a.get("pid"))
        if p:
            p["team"] = 1 if int(a.get("team", 0)) else 0
    elif t == "kick":
        G["players"] = [p for p in G["players"] if p["id"] != a.get("pid")]
    elif t == "add_local":
        name = (a.get("name") or "").strip()[:20]
        if name:
            pid = "l%d%03d" % (len(G["players"]) + 1, random.randint(0, 999))
            G["players"].append({"id": pid, "name": name, "team": len(G["players"]) % 2,
                                 "score": 0, "answer": None, "at": None,
                                 "correct": None, "gain": 0})
    elif t == "goto_pick":
        if len(G["players"]) < 2:
            return {"error": "تحتاجون لاعبين على الأقل"}
        G["phase"] = "pick"
    elif t == "back_lobby":
        G["phase"] = "lobby"
    elif t == "start":
        picks = a.get("picks") or []
        if not picks:
            return {"error": "اختر سؤال على الأقل"}
        queue = []
        for i, pk in enumerate(picks):
            if pk.get("custom"):
                text = (pk.get("text") or "").strip()[:140]
                pool = [str(x).strip()[:60] for x in (pk.get("pool") or []) if str(x).strip()]
                cat = "من عندكم"
            else:
                c = CATEGORIES[int(pk["c"])]
                item = c["questions"][int(pk["q"])]
                text, pool, cat = item["q"], list(item["pool"]), c["name"]
            queue.append({"text": text, "pool": pool, "cat": cat,
                          "owner": G["players"][i % len(G["players"])]["id"],
                          "count": 4, "options": [], "correct": None, "double": False})
        G["queue"] = queue
        G["round"] = 0
        G["phase"] = "owner"
        G["composer"] = None
        G["hint"] = ""
        G["hint_used"] = False
        for p in G["players"]:
            p["score"] = 0
        clear_answers()
    elif t == "set_owner":
        q = cur()
        if q and find(a.get("pid")):
            q["owner"] = a["pid"]
    elif t == "toggle_double":
        q = cur()
        if q:
            q["double"] = not q.get("double", False)
    elif t == "send_compose":
        q = cur()
        if q:
            G["composer"] = "host" if a.get("where") == "host" else q["owner"]
            q["options"] = []
            q["correct"] = None
            G["phase"] = "compose"
    elif t == "back_owner":
        G["phase"] = "owner"
        G["composer"] = None
    elif t == "start_round":
        q = cur()
        if q and q["options"] and q["correct"] is not None:
            clear_answers()
            G["hint"] = ""
            G["phase"] = "play"
            G["deadline"] = now_ms() + ROUND_SECONDS * 1000
    elif t == "hint":
        txt = (a.get("text") or "").strip()[:160]
        if txt and not G["hint_used"]:
            G["hint"] = txt
            G["hint_used"] = True
    elif t == "reveal":
        q = cur()
        if q and G["phase"] == "play":
            for p in G["players"]:
                if p["id"] == q["owner"]:
                    p["correct"] = None
                else:
                    p["correct"] = (p["answer"] == q["correct"])
            G["phase"] = "reveal"
    elif t == "toggle_correct":
        p = find(a.get("pid"))
        if p and G["phase"] == "reveal":
            p["correct"] = not bool(p["correct"])
    elif t == "next":
        q = cur()
        if q and G["phase"] == "reveal":
            pts = base_points(q)
            for p in G["players"]:
                if p["correct"]:
                    p["score"] += pts
                    p["gain"] = pts
                else:
                    p["gain"] = 0
            if G["round"] >= len(G["queue"]) - 1:
                G["phase"] = "end"
            else:
                G["round"] += 1
                G["phase"] = "owner"
                G["composer"] = None
    elif t == "end_now":
        q = cur()
        if q and G["phase"] == "reveal":
            pts = base_points(q)
            for p in G["players"]:
                if p["correct"]:
                    p["score"] += pts
        G["phase"] = "end"
    elif t == "again":
        reset(keep_players=True)
        G["phase"] = "pick"
    elif t == "new_game":
        reset(keep_players=False)
    else:
        return {"error": "أمر غير معروف"}

    touch()
    return {"ok": True}


# ─────────────────────────── الخادم ───────────────────────────
def read_file(name):
    with open(os.path.join(BASE, name), "rb") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json; charset=utf-8", code=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        path, qs = u.path, parse_qs(u.query)
        try:
            if path in ("/", "/index.html"):
                return self._send(read_file("host.html"), "text/html; charset=utf-8")
            if path in ("/p", "/p/"):
                return self._send(read_file("player.html"), "text/html; charset=utf-8")
            if path == "/qrcode.min.js":
                return self._send(read_file("qrcode.min.js"), "application/javascript; charset=utf-8")
            if path == "/bank":
                data = [{"name": c["name"], "icon": c["icon"],
                         "questions": [{"q": x["q"], "pool": x["pool"]} for x in c["questions"]]}
                        for c in CATEGORIES]
                return self._send(json.dumps({"cats": data, "total": TOTAL}, ensure_ascii=False))
            if path == "/state":
                with lock:
                    role = (qs.get("role") or ["host"])[0]
                    s = snap_host() if role == "host" else snap_player((qs.get("pid") or [""])[0])
                return self._send(json.dumps(s, ensure_ascii=False))
            if path == "/favicon.ico":
                return self._send(b"", "image/x-icon")
        except FileNotFoundError:
            return self._send('{"error":"ملف مفقود"}', code=404)
        self._send('{"error":"غير موجود"}', code=404)

    def do_POST(self):
        if urlparse(self.path).path != "/act":
            return self._send('{"error":"غير موجود"}', code=404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception:
            data = {}
        with lock:
            try:
                res = act(data)
            except Exception as e:
                res = {"error": "خطأ: %s" % e}
        self._send(json.dumps(res, ensure_ascii=False))


def lan_ip():
    """العنوان على الكرت اللي يوصل للراوتر."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def all_ips():
    """كل عناوين الشبكة المحلية — بعض الأجهزة فيها أكثر من كرت (واي فاي، إيثرنت، VPN)،
    فنعرضها كلها والهوست يختار اللي يمسك مع جوالاتهم."""
    found = []
    primary = lan_ip()
    if not primary.startswith("127."):
        found.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith(("127.", "169.254.")):
                found.append(ip)
    except Exception:
        pass

    def rank(ip):                      # الشبكات المنزلية أولًا
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 2
        return 3

    found.sort(key=rank)
    return found or ["127.0.0.1"]


def say(*parts):
    """طباعة آمنة مهما كان ترميز نافذة الأوامر."""
    line = " ".join(str(x) for x in parts)
    try:
        print(line)
    except Exception:
        try:
            sys.stdout.buffer.write(line.encode("utf-8", "replace"))
            sys.stdout.buffer.write(b"\n")
            sys.stdout.flush()
        except Exception:
            print(line.encode("ascii", "replace").decode("ascii"))


def main():
    global JOIN_URL, JOIN_URLS
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    srv = None
    for port in PORT_RANGE:
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            break
        except OSError:
            continue
    if not srv:
        say("ما قدرت أفتح أي منفذ. سكّر البرامج الثانية وحاول مرة ثانية.")
        input("اضغط Enter للخروج...")
        return
    port = srv.server_address[1]
    ips = all_ips()
    ip = ips[0]
    JOIN_URLS = ["http://%s:%d/p" % (x, port) for x in ips]
    JOIN_URL = JOIN_URLS[0]
    bar = "═" * 46
    say("\n" + bar)
    say("   مين يعرفني أكثر — الخادم شغّال")
    say(bar)
    say("   شاشة الهوست :  http://localhost:%d" % port)
    for i, u in enumerate(JOIN_URLS):
        say("   رابط اللاعبين:  %s%s" % (u, "" if i == 0 else "   (عنوان بديل)"))
    say("   عدد الأسئلة  :  %d سؤال" % TOTAL)
    say(bar)
    say("   لا تسكّر هذي النافذة أثناء اللعب.")
    say("   للإيقاف: اضغط Ctrl + C\n")
    try:
        webbrowser.open("http://localhost:%d" % port)
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        say("\nتم إيقاف اللعبة. مع السلامة!")


if __name__ == "__main__":
    main()
