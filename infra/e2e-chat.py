#!/usr/bin/env python3
"""E2E: SSO-логин → WS-чат с агентом → проверка треда в data layer.

Протокол (chainlit 2.11.1, socket.py): handshake c auth-словарём
{sessionId, threadId, userEnv, clientType}; cookie access_token
авторизует соединение; клиент шлёт "connection_successful" (триггерит
on_chat_start), сообщения — событием "client_message"; сервер стримит
"stream_token"/"new_message".

Зависимость: pip install "python-socketio[client]". Нужны запущенный стек
и Ollama на хосте.
"""

import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import socketio  # python-socketio[client]

CHAINLIT = "http://localhost:8000"
USERNAME = "akadmin"
PASSWORD = "admin"
# Вопрос с вычислением: гоняет полный fast-маршрут, включая ToolNode
# (model -> calculator -> final через Ollama).
PROMPT = "Сколько будет 17 * 23? Посчитай калькулятором."
PROFILE = sys.argv[1] if len(sys.argv) > 1 else "fast"


# --- 1. SSO-логин (повторяет проверенный OAuth-флоу) -----------------------

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


no_redirect = urllib.request.build_opener(
    NoRedirect, urllib.request.HTTPCookieProcessor(jar)
)


def get_location(url):
    try:
        resp = no_redirect.open(url, timeout=15)
        return resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.headers.get("Location")
        raise


authorize_url = get_location(f"{CHAINLIT}/auth/oauth/generic")
flow_redirect = get_location(authorize_url)
parsed = urllib.parse.urlparse(urllib.parse.urljoin(authorize_url, flow_redirect))
next_q = urllib.parse.parse_qs(parsed.query).get("next", ["/"])[0]
flow_slug = [p for p in parsed.path.split("/") if p][-1]
base = f"{parsed.scheme}://{parsed.netloc}"
executor = (
    f"{base}/api/v3/flows/executor/{flow_slug}/"
    f"?query={urllib.parse.quote(urllib.parse.urlencode({'next': next_q}))}"
)

state = json.loads(opener.open(executor, timeout=15).read())
for _ in range(10):
    component = state.get("component")
    if component == "xak-flow-redirect":
        break
    if component == "ak-stage-identification":
        payload = {"uid_field": USERNAME, "component": component}
        if state.get("password_fields"):
            payload["password"] = PASSWORD
    elif component == "ak-stage-password":
        payload = {"password": PASSWORD, "component": component}
    else:
        sys.exit(f"unexpected flow component: {component}")
    req = urllib.request.Request(
        executor,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    state = json.loads(opener.open(req, timeout=15).read())

to = urllib.parse.urljoin(base, state["to"])
callback = get_location(to)
try:
    no_redirect.open(callback, timeout=30)
except urllib.error.HTTPError as e:
    if e.code not in (301, 302, 303, 307, 308):
        raise
user = json.loads(opener.open(f"{CHAINLIT}/user", timeout=15).read())
assert user["identifier"] == USERNAME
cookie_header = "; ".join(f"{c.name}={c.value}" for c in jar)
print(f"1. SSO ok ({user['identifier']})")

# --- 2. WS-чат --------------------------------------------------------------

sio = socketio.Client()
tokens: list[str] = []
done = {"flag": False}


@sio.on("stream_token")
def on_stream(data):
    tokens.append(data.get("token", ""))


@sio.on("update_message")
def on_update(data):
    done["flag"] = True


@sio.on("new_message")
def on_new(data):
    if data.get("type") == "assistant_message" and not data.get("streaming"):
        done["flag"] = True


session_id = uuid.uuid4().hex
sio.connect(
    CHAINLIT,
    socketio_path="/ws/socket.io",
    headers={"Cookie": cookie_header},
    auth={
        "sessionId": session_id,
        "threadId": None,
        "userEnv": "{}",
        "clientType": "webapp",
        "chatProfile": PROFILE,
    },
    wait_timeout=15,
)
sio.emit("connection_successful")
time.sleep(1)  # даём on_chat_start собрать агента
sio.emit(
    "client_message",
    {
        "message": {
            "id": str(uuid.uuid4()),
            "name": USERNAME,
            "type": "user_message",
            "output": PROMPT,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    },
)
deadline = time.time() + 120
while time.time() < deadline and not (done["flag"] and tokens):
    time.sleep(0.5)
sio.disconnect()
answer = "".join(tokens)
assert answer.strip(), "агент не ответил (Ollama запущена?)"
print(f"2. stream ok ({len(tokens)} токенов): {answer[:60]!r}")

# --- 3. Тред записан в data layer -------------------------------------------

req = urllib.request.Request(
    f"{CHAINLIT}/project/threads",
    data=json.dumps({"pagination": {"first": 10}, "filter": {}}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
threads = json.loads(opener.open(req, timeout=15).read())["data"]
assert threads, "тредов нет"
steps = threads[0].get("steps") or []
outputs = [s.get("output", "") for s in steps]
assert any(PROMPT in o for o in outputs), "user-сообщение не в data layer"
print(f"3. thread ok (id={threads[0]['id'][:8]}…, steps={len(steps)})")
print("E2E CHAT OK")
