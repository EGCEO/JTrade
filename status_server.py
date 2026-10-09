#!/usr/bin/env python3
"""Minimal status page for the AutoTrade bot (headless app preview entry point).

Serves a simple HTML status page on port 3000 showing whether the bot
process is alive and tailing its recent log output. Uses only the Python
standard library so it needs no extra dependencies.
"""
import http.server
import html
import os

PORT = int(os.environ.get("PORT", "3000"))
BOT_LOG = os.environ.get("BOT_LOG", "/tmp/bot.log")
BOT_PID_FILE = os.environ.get("BOT_PID_FILE", "/tmp/bot.pid")


def bot_alive():
    try:
        with open(BOT_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True, pid
    except Exception:
        return False, None


def tail_log(n=40):
    try:
        with open(BOT_LOG) as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        alive, pid = bot_alive()
        log_lines = tail_log()
        status = "RUNNING" if alive else "STOPPED"
        log_html = html.escape("".join(log_lines))
        body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>AutoTrade Bot</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; background: #f8fafc;
         color: #0f172a; max-width: 820px; margin: 0 auto; padding: 40px 20px; }}
  h1 {{ margin: 0 0 4px; }}
  .sub {{ color: #64748b; margin-top: 0; }}
  .badge {{ display: inline-block; padding: 4px 14px; border-radius: 999px;
            color: #fff; font-weight: 600; font-size: 14px; }}
  .running {{ background: #16a34a; }}
  .stopped {{ background: #dc2626; }}
  pre {{ background: #0f172a; color: #e2e8f0; padding: 16px; border-radius: 10px;
         overflow: auto; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }}
  .meta {{ color: #475569; font-size: 14px; }}
</style>
</head>
<body>
  <h1>🚀 AutoTrade Bot</h1>
  <p class="sub">BSC / PancakeSwap whale-tracking trading bot</p>
  <p>Status: <span class="badge {status.lower()}">{status}</span></p>
  <p class="meta">Bot PID: {pid if pid else "N/A"} &middot; status refreshed on every request</p>
  <h3>Recent log output</h3>
  <pre>{log_html or "(no output yet)"}</pre>
</body>
</html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Status server listening on :{PORT}")
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
