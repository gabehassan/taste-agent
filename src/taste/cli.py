import argparse
import json
import os
import pathlib
import subprocess
import sys

from . import db
from .config import ROOT

PLIST_NAME = "com.gabe.taste-agent"
PLIST_PATH = pathlib.Path.home() / "Library/LaunchAgents" / f"{PLIST_NAME}.plist"


def main():
    ap = argparse.ArgumentParser(prog="taste")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the daemon in the foreground (local mode, or relay mode if TASTE_SERVER_URL is set)")
    sub.add_parser("relay", help="run in relay mode against the server")
    p = sub.add_parser("ingest", help="save a url without iMessage"); p.add_argument("url"); p.add_argument("--note", default=""); p.add_argument("--send", action="store_true")
    p = sub.add_parser("surface", help="send (or print) the next snippet"); p.add_argument("--dry", action="store_true"); p.add_argument("--kind", choices=["snippet", "observation"])
    p = sub.add_parser("profile", help="print the taste profile"); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("chat", help="talk to the agent from the terminal"); p.add_argument("text")
    p = sub.add_parser("send", help="send a raw iMessage to yourself"); p.add_argument("text")
    sub.add_parser("status")
    sub.add_parser("items")
    sub.add_parser("install", help="install + start the launchd agent")
    sub.add_parser("uninstall")
    sub.add_parser("restart")
    sub.add_parser("logs")
    a = ap.parse_args()
    db.init()

    if a.cmd == "relay" or (a.cmd == "run" and os.environ.get("TASTE_SERVER_URL")):
        from .relay import run; run()
    elif a.cmd == "run":
        from .daemon import run; run()
    elif a.cmd == "ingest":
        from .daemon import ingest_url, say, setup_logging
        setup_logging()
        item, ack = ingest_url(a.url, note=a.note)
        print(json.dumps(item, indent=1, default=str)[:3000]); print("\nack:", ack)
        if a.send:
            say(ack)
    elif a.cmd == "surface":
        from . import scheduler
        from .daemon import do_surface, setup_logging
        setup_logging()
        if a.dry:
            kind, item, text = scheduler.next_surface(a.kind)
            print(kind, "\n", text)
        else:
            do_surface(a.kind)
    elif a.cmd == "profile":
        from . import brain
        if a.refresh:
            brain.refresh_profile()
        p = db.latest_profile()
        if not p:
            print("no profile yet"); return
        print(db.get_state("one_liner"), "\n")
        print(p["text"]); print("\nobservations:")
        for o in p["observations"]:
            print(" -", o)
    elif a.cmd == "chat":
        from . import brain
        print(brain.chat(a.text))
    elif a.cmd == "send":
        from .daemon import say, setup_logging
        setup_logging(); say(a.text)
    elif a.cmd == "status":
        from . import scheduler
        print(f"items: {db.count_items()}  unread: {len(db.list_items(limit=1000, status='unread'))}")
        p = db.latest_profile(); print("profile:", f"from {p['item_count']} items" if p else "none")
        print("paused:", db.get_state("paused", False)); print("cursor:", db.get_state("last_rowid"))
        print("plan:", scheduler.todays_plan()[1])
    elif a.cmd == "items":
        for i in db.list_items(limit=50):
            print(f"{i['id']:>4} [{i['kind']:>8}] {i['status']:<7} {i['title'][:60]}  {i.get('url') or ''}")
    elif a.cmd == "install":
        install()
    elif a.cmd == "uninstall":
        subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{PLIST_NAME}"], check=False)
        PLIST_PATH.unlink(missing_ok=True); print("removed")
    elif a.cmd == "restart":
        subprocess.run(["launchctl", "kickstart", "-k", f"gui/{_uid()}/{PLIST_NAME}"], check=False)
    elif a.cmd == "logs":
        subprocess.run(["tail", "-n", "50", "-f", str(ROOT / "data/taste.log")])


def _uid():
    import os; return os.getuid()


def install():
    exe = ROOT / ".venv/bin/taste"
    logs = pathlib.Path.home() / "Library/Logs/taste-agent"; logs.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>{PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array><string>{exe}</string><string>run</string></array>
    <key>WorkingDirectory</key><string>{ROOT}</string>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
    <key>StandardOutPath</key><string>{logs}/out.log</string>
    <key>StandardErrorPath</key><string>{logs}/err.log</string>
  </dict>
</plist>
"""
    PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "bootout", f"gui/{_uid()}/{PLIST_NAME}"], check=False, capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{_uid()}", str(PLIST_PATH)], capture_output=True, text=True)
    print("installed", PLIST_PATH, r.stderr.strip())


if __name__ == "__main__":
    main()
