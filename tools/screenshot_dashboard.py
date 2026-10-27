#!/usr/bin/env python3
"""Screenshot the public Metabase dashboard via the Chrome DevTools protocol.

Metabase renders client-side, so the shot is taken after the fetches have
actually landed: navigate, wait in real time, then capture.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.request

import websocket

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def capture(url: str, output: str, wait_seconds: float = 12.0, width: int = 1440, height: int = 1080) -> str:
    profile = "/tmp/sikt-chrome-profile"
    chrome = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--remote-debugging-port=9222", f"--user-data-dir={profile}",
        f"--window-size={width},{height}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                targets = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except (OSError, ValueError):
                time.sleep(0.5)
        socket = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30)
        call_id = 0

        def send(method: str, params: dict | None = None) -> dict:
            nonlocal call_id
            call_id += 1
            socket.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
            while True:
                message = json.loads(socket.recv())
                if message.get("id") == call_id:
                    return message.get("result", {})

        send("Page.enable")
        send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })
        send("Page.navigate", {"url": url})
        time.sleep(wait_seconds)
        shot = send("Page.captureScreenshot", {"format": "png"})
        with open(output, "wb") as handle:
            handle.write(base64.b64decode(shot["data"]))
        socket.close()
        return output
    finally:
        chrome.terminate()
        chrome.wait(timeout=10)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wait", type=float, default=12.0)
    args = parser.parse_args()

    print(capture(args.url, args.output, wait_seconds=args.wait))


if __name__ == "__main__":
    main()
