"""Общая механика скриптов: SSO-логин и вопрос агенту через WS Chainlit.

Используется e2e-chat.py и eval-agents.py. Зависимость:
pip install "python-socketio[client]".
"""

import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import socketio

CHAINLIT = "http://localhost:8000"
USERNAME = "akadmin"
PASSWORD = "admin"


def login() -> str:
    """SSO-логин через authentik; возвращает Cookie-заголовок для WS/REST."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    no_redirect = urllib.request.build_opener(
        NoRedirect, urllib.request.HTTPCookieProcessor(jar)
    )

    def loc(url):
        try:
            return no_redirect.open(url, timeout=15).headers.get("Location")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e.headers.get("Location")
            raise

    authorize_url = loc(f"{CHAINLIT}/auth/oauth/generic")
    flow_redirect = loc(authorize_url)
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
            raise RuntimeError(f"unexpected flow component: {component}")
        req = urllib.request.Request(
            executor,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        state = json.loads(opener.open(req, timeout=15).read())

    to = urllib.parse.urljoin(base, state["to"])
    callback = loc(to)
    try:
        no_redirect.open(callback, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
    user = json.loads(opener.open(f"{CHAINLIT}/user", timeout=15).read())
    assert user["identifier"] == USERNAME, user
    return "; ".join(f"{c.name}={c.value}" for c in jar)


def ask(cookie_header: str, profile: str, question: str, timeout: int = 180) -> str:
    """Новая WS-сессия с профилем; шлёт вопрос, возвращает собранный ответ."""
    sio = socketio.Client()
    tokens: list[str] = []
    # Конец ответа = update_message (out.update() на бэкенде) с полным
    # текстом. new_message приходит В НАЧАЛЕ (пустое сообщение перед
    # стримом) — сигналом завершения не является.
    final: dict = {"text": None}

    @sio.on("stream_token")
    def on_stream(data):
        tokens.append(data.get("token", ""))

    @sio.on("update_message")
    def on_update(data):
        if data.get("type") == "assistant_message":
            final["text"] = data.get("output") or "".join(tokens)

    sio.connect(
        CHAINLIT,
        socketio_path="/ws/socket.io",
        headers={"Cookie": cookie_header},
        auth={
            "sessionId": uuid.uuid4().hex,
            "threadId": None,
            "userEnv": "{}",
            "clientType": "webapp",
            "chatProfile": profile,
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
                "output": question,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        },
    )
    deadline = time.time() + timeout
    while time.time() < deadline and final["text"] is None:
        time.sleep(0.5)
    sio.disconnect()
    return final["text"] or "".join(tokens)
