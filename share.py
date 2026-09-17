# -*- coding: utf-8 -*-
"""تشغيل اللعبة برابط عام يشتغل من أي مكان.

يشغّل نفس الخادم المحلي، ويفتح له نفقًا عبر Cloudflare فيصير له رابط
https مؤقت تقدر ترسله لأي أحد — بدون حساب ولا استضافة ولا شرط واي فاي مشترك.
الرابط يعيش ما دامت هذي النافذة مفتوحة، ويتغيّر كل مرة تشغّلها."""

import os, re, subprocess, sys, threading, time, urllib.request, webbrowser
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as S

BASE = os.path.dirname(os.path.abspath(__file__))
CF_EXE = os.path.join(BASE, "cloudflared.exe")
CF_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/download/"
          "cloudflared-windows-amd64.exe")
URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")


def ensure_tool():
    """ينزّل أداة Cloudflare الرسمية أول مرة فقط."""
    if os.path.exists(CF_EXE) and os.path.getsize(CF_EXE) > 1_000_000:
        return True
    S.say("   أول مرة فقط: أنزّل أداة المشاركة من Cloudflare (~55 ميجا)…")
    tmp = CF_EXE + ".part"
    try:
        with urllib.request.urlopen(CF_URL, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    sys.stdout.write("\r   التحميل: %d%%   " % (got * 100 // total))
                    sys.stdout.flush()
        os.replace(tmp, CF_EXE)
        sys.stdout.write("\r" + " " * 30 + "\r")
        return True
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        S.say("   ما قدرت أنزّل الأداة: %s" % e)
        S.say("   تأكد من الإنترنت، أو شغّل START-GAME.bat للّعب المحلي.")
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    bar = "═" * 52
    S.say("\n" + bar)
    S.say("   مين يعرفني أكثر — مشاركة برابط عام")
    S.say(bar)

    if not ensure_tool():
        input("اضغط Enter للخروج...")
        return

    # 1) شغّل الخادم محليًا
    srv = None
    for port in S.PORT_RANGE:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), S.Handler)
            break
        except OSError:
            continue
    if not srv:
        S.say("   ما قدرت أفتح أي منفذ. سكّر البرامج الثانية وحاول مرة ثانية.")
        input("اضغط Enter للخروج...")
        return
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # 2) افتح النفق العام
    S.say("   أجهّز الرابط العام…")
    proc = subprocess.Popen(
        [CF_EXE, "tunnel", "--url", "http://127.0.0.1:%d" % port, "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    public = {"url": None}

    def pump():
        """يقرأ مخرجات الأداة ويلتقط الرابط — ولازم يستمر بالقراءة حتى لا تمتلئ القناة."""
        for line in proc.stdout:
            if not public["url"]:
                m = URL_RE.search(line)
                if m:
                    public["url"] = m.group(0)

    threading.Thread(target=pump, daemon=True).start()

    for _ in range(60):                      # ننتظر الرابط حتى 30 ثانية
        if public["url"]:
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not public["url"]:
        S.say("   تعذّر إنشاء الرابط العام. جرّب مرة ثانية، أو استخدم START-GAME.bat للّعب المحلي.")
        try:
            proc.terminate()
        except Exception:
            pass
        input("اضغط Enter للخروج...")
        return

    join = public["url"] + "/p"
    S.JOIN_URLS = [join]
    S.JOIN_URL = join

    S.say(bar)
    S.say("   شاشة المستضيف :  http://localhost:%d" % port)
    S.say("   رابط اللاعبين  :  %s" % join)
    S.say(bar)
    S.say("   أرسل رابط اللاعبين لأي أحد — يشتغل من أي شبكة وأي مكان.")
    S.say("   نفس الرابط داخل الباركود على الشاشة.")
    S.say("")
    S.say("   ملاحظات:")
    S.say("   • الرابط يعيش ما دامت هذي النافذة مفتوحة، ويتغيّر كل تشغيل.")
    S.say("   • لا تسكّر النافذة أثناء اللعب.")
    S.say("   للإيقاف: اضغط Ctrl + C\n")

    try:
        webbrowser.open("http://localhost:%d" % port)
    except Exception:
        pass

    try:
        while proc.poll() is None:
            time.sleep(0.5)
        S.say("\nانقطع الرابط العام. سكّر النافذة وشغّلها مرة ثانية.")
    except KeyboardInterrupt:
        S.say("\nتم إيقاف اللعبة. مع السلامة!")
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    main()
