from flask import Flask, request, jsonify, abort
import time, os, threading, hashlib, sys
from datetime import datetime
import requests
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw

app = Flask(__name__)

# --- Load config from .env ---
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)
# Required - must be in the .env file
EXPECTED_TOKEN = os.environ["GLASSES_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# If not in the .env file, these will be used as defaults:
OPENAI_MODEL   = os.environ.get("OPENAI_MODEL", "gpt-4.1")
MAX_CHARS      = int(os.environ.get("MAX_CHARS", 400))
PORT           = int(os.environ.get("PORT", 4567))

# --- Logging ---
# Log file is saved where the script runs from
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smartglasses.log")
_log_lock = threading.Lock()

def log(msg):
    """Append a timestamped line to the log file."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _log_lock:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass  # Stops logging from crashing any request

# --- Memory settings ---
MAX_TURNS      = 12    # How many user+assistant message pairs to remember
SESSION_TTL    = 600   # Number of seconds of inactivity before a conversation is forgotten

SYSTEM_PROMPT = (
    "You are a voice assistant running on Even Realities smart glasses with a tiny "
    "heads-up display. The user speaks to you and reads short replies on the lens. "
    f"Keep every response under {MAX_CHARS} characters. Be direct and conversational. "
    "No markdown, no bullet points, no formatting symbols, no emojis. Give plain "
    "sentences only. If the answer is long, give the single most useful summary."
)

_sessions = {}
_lock = threading.Lock()

# --- Even sometimes sends duplicate requests - this suppresses the second one ---
_recent = {}            # { sig: (timestamp, reply_or_None, threading.Event) }
_recent_lock = threading.Lock()
DEDUP_WINDOW = 10       # seconds


def get_history(key):
    now = time.time()
    with _lock:
        sess = _sessions.get(key)
        if sess and (now - sess["last_seen"]) < SESSION_TTL:
            return list(sess["messages"])
        _sessions[key] = {"messages": [], "last_seen": now}
        return []


def save_turn(key, user_msg, assistant_msg):
    now = time.time()
    with _lock:
        sess = _sessions.setdefault(key, {"messages": [], "last_seen": now})
        sess["messages"].append({"role": "user", "content": user_msg})
        sess["messages"].append({"role": "assistant", "content": assistant_msg})
        sess["messages"] = sess["messages"][-(MAX_TURNS * 2):]
        sess["last_seen"] = now


def cleanup_sessions():
    now = time.time()
    with _lock:
        stale = [k for k, v in _sessions.items() if now - v["last_seen"] > SESSION_TTL]
        for k in stale:
            del _sessions[k]


def signal_done(sig, reply):
    with _recent_lock:
        entry = _recent.get(sig)
        ev = entry[2] if entry else threading.Event()
        _recent[sig] = (time.time(), reply, ev)
        ev.set()


@app.route("/v1/chat/completions", methods=["POST"])
def chat():
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {EXPECTED_TOKEN}":
        abort(401)

    data = request.get_json(force=True)
    incoming_msgs = data.get("messages", [])

    user_msg = ""
    for m in reversed(incoming_msgs):
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break

    agent_id = request.headers.get("x-openclaw-agent-id", "main")
    session_key = agent_id

    sig = hashlib.sha256(f"{session_key}|{user_msg}".encode()).hexdigest()
    now = time.time()

    wait_event = None
    is_first = False
    with _recent_lock:
        for k in [k for k, v in _recent.items() if now - v[0] > DEDUP_WINDOW]:
            del _recent[k]

        existing = _recent.get(sig)
        if existing:
            ts, cached_reply, ev = existing
            if cached_reply is not None:
                return _completion(cached_reply, data)
            else:
                wait_event = ev
        else:
            _recent[sig] = (now, None, threading.Event())
            is_first = True

    # Only the FIRST request logs the incoming question (ie. only logged once)
    if is_first:
        log(f"USER [{agent_id}]: {user_msg}")

    if wait_event is not None:
        wait_event.wait(timeout=28)
        with _recent_lock:
            entry = _recent.get(sig)
        reply = entry[1] if entry and entry[1] is not None else "Sorry, please try again."
        return _completion(reply, data)

    cleanup_sessions()
    history = get_history(session_key)

    messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": user_msg}]
    )

    # --- Call OpenAI API, with one retry on timeout ---
    reply = None
    for attempt in range(2):   # try up to twice
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENAI_MODEL,
                    "messages": messages,
                    "max_completion_tokens": 150,
                },
                timeout=15,
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"].strip()
            break   # If successful leave the loop
        except requests.exceptions.Timeout:
            log("Timeout on first attempt, retrying..." if attempt == 0
                else "Timeout on retry, giving up.")
            continue
        except requests.exceptions.HTTPError as e:
            log(f"ERROR: OpenAI HTTP error: {e} | body: {resp.text}")
            break
        except Exception as e:
            log(f"ERROR: {e}")
            break

    # If we never got a reply (timed out twice, or errored)
    if reply is None:
        reply = "Sorry, that took too long. Please ask again."
        signal_done(sig, reply)
        log(f"REPLY [{agent_id}]: {reply}")
        return _completion(reply, data)

    # --- Success path ---
    if len(reply) > MAX_CHARS:
        reply = reply[:MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"

    save_turn(session_key, user_msg, reply)
    signal_done(sig, reply)
    # Log the reply we sent
    log(f"REPLY [{agent_id}]: {reply}")

    return _completion(reply, data)


def _completion(reply, data):
    return jsonify({
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("model", "openclaw"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": reply},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    })


def run_server():
    app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False)


def make_icon_image():
    """This generates a simple glasses-style icon so we don't need an external ICO file."""
    img = Image.new("RGB", (64, 64), color=(30, 30, 30))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 24, 28, 46), outline=(0, 200, 255), width=4)
    d.ellipse((36, 24, 58, 46), outline=(0, 200, 255), width=4)
    d.line((28, 32, 36, 32), fill=(0, 200, 255), width=4)
    return img


def open_log(icon, _item):
    """Opens the log file in the default editor (eg. Notepad)."""
    try:
        if not os.path.exists(LOG_PATH):
            open(LOG_PATH, "a", encoding="utf-8").close()
        os.startfile(LOG_PATH)
    except Exception:
        pass


def on_quit(icon, _item):
    log("=== Server stopped ===")
    icon.stop()
    os._exit(0)


def main():
    log("=== Server started ===")

    t = threading.Thread(target=run_server, daemon=True)
    t.start()

    menu = pystray.Menu(
        item(f"Smart Glasses AI  (port {PORT})", None, enabled=False),
        item("Open Log", open_log),
        item("Quit", on_quit),
    )
    icon = pystray.Icon(
        "smartglasses",
        make_icon_image(),
        "Smart Glasses AI server",
        menu,
    )
    icon.run()


if __name__ == "__main__":
    main()
