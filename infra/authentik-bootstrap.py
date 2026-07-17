#!/usr/bin/env python3
"""
Bootstrap локального authentik: создаёт OAuth2-провайдера и приложение,
чтобы Chainlit (generic OAuth) работал сразу после `docker compose up`.

Запускается one-shot init-контейнером после готовности authentik.
Идемпотентен: если приложение уже существует — no-op.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

AUTHENTIK_URL = os.environ.get("AUTHENTIK_INTERNAL_URL", "http://authentik-server:9000")
API_TOKEN = os.environ["AUTHENTIK_BOOTSTRAP_TOKEN"]
CLIENT_ID = os.environ["AUTHENTIK_CLIENT_ID"]
CLIENT_SECRET = os.environ["AUTHENTIK_CLIENT_SECRET"]
APP_SLUG = os.environ.get("AUTHENTIK_APP_SLUG", "lore")
APP_NAME = os.environ.get("AUTHENTIK_APP_NAME", "Lore Chat")
REDIRECT_URI = os.environ.get(
    "AUTHENTIK_REDIRECT_URI", "http://localhost:8000/auth/oauth/generic/callback"
)
FRONTEND_URL = os.environ.get("LORE_FRONTEND_URL", "http://localhost:3000")

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def api_request(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{AUTHENTIK_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"API error {e.code} on {method} {path}: {error_body}", file=sys.stderr)
        raise


def wait_for_authentik(timeout: int = 300) -> None:
    # /-/health/ready/ становится ready раньше, чем worker просеет bootstrap
    # API-токен, поэтому дополнительно поллим аутентифицированный endpoint.
    print("Waiting for authentik to be ready...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{AUTHENTIK_URL}/-/health/ready/")
            with urllib.request.urlopen(req, timeout=5):
                break
        except Exception:
            time.sleep(5)
    else:
        print("ERROR: authentik did not become ready in time!", file=sys.stderr)
        sys.exit(1)

    while time.time() < deadline:
        req = urllib.request.Request(
            f"{AUTHENTIK_URL}/api/v3/core/applications/?page_size=1", headers=HEADERS
        )
        try:
            with urllib.request.urlopen(req, timeout=5):
                print("authentik is ready!")
                return
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise
        except Exception:
            pass
        time.sleep(5)
    print("ERROR: bootstrap token was not accepted in time!", file=sys.stderr)
    sys.exit(1)


def app_exists() -> bool:
    result = api_request("GET", f"/api/v3/core/applications/?slug={APP_SLUG}")
    return result["pagination"]["count"] > 0


def get_flow(designation: str, prefer_keyword: str = "") -> str:
    result = api_request(
        "GET", f"/api/v3/flows/instances/?designation={designation}&ordering=slug"
    )
    flows = result.get("results", [])
    if prefer_keyword:
        for flow in flows:
            if prefer_keyword in flow["slug"]:
                return flow["pk"]
    if flows:
        return flows[0]["pk"]
    raise RuntimeError(f"No {designation} flow found in authentik!")


PROPERTY_MAPPING_PATHS = (
    "/api/v3/propertymappings/provider/scope/?ordering=scope_name&page_size=100",
    "/api/v3/propertymappings/scope/?ordering=scope_name&page_size=100",
)
REQUIRED_SCOPE_NAMES = frozenset({"openid", "profile", "email"})


def get_scope_mappings(timeout: int = 120) -> list[str]:
    """Дождаться дефолтных OIDC scope-маппингов и вернуть их UUID.

    Worker authentik сеет openid/profile/email асинхронно после health-ready.
    Если создать провайдера раньше — в userinfo не будет preferred_username.
    """
    working_path: str | None = None
    for path in PROPERTY_MAPPING_PATHS:
        try:
            api_request("GET", path)
        except urllib.error.HTTPError:
            continue
        working_path = path
        break
    if working_path is None:
        print("ERROR: no propertymappings API path responded.", file=sys.stderr)
        sys.exit(1)

    print("Waiting for default OIDC scope mappings to be seeded...")
    deadline = time.time() + timeout
    present: set[str] = set()
    results: list[dict] = []
    while time.time() < deadline:
        results = api_request("GET", working_path).get("results", [])
        present = {r.get("scope_name") for r in results if r.get("scope_name")}
        if REQUIRED_SCOPE_NAMES.issubset(present):
            return [r["pk"] for r in results]
        time.sleep(2)

    missing = sorted(REQUIRED_SCOPE_NAMES - present)
    print(
        f"ERROR: default OIDC scope mappings not seeded in time, missing: {missing}",
        file=sys.stderr,
    )
    sys.exit(1)


def get_signing_key() -> str | None:
    result = api_request(
        "GET",
        "/api/v3/crypto/certificatekeypairs/?has_key=true&ordering=name&page_size=10",
    )
    pairs = result.get("results", [])
    for pair in pairs:
        if "authentik" in pair["name"].lower() or "self-signed" in pair["name"].lower():
            return pair["pk"]
    if pairs:
        return pairs[0]["pk"]
    return None


def create_provider(
    auth_flow: str,
    invalidation_flow: str,
    scope_mappings: list[str],
    signing_key: str | None,
) -> int:
    provider_data = {
        "name": APP_NAME,
        "authorization_flow": auth_flow,
        "invalidation_flow": invalidation_flow,
        "client_type": "confidential",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [{"matching_mode": "strict", "url": REDIRECT_URI}],
        "sub_mode": "user_username",
        "include_claims_in_id_token": True,
        "access_code_validity": "minutes=1",
        "access_token_validity": "minutes=10",
        "refresh_token_validity": "days=30",
    }
    if scope_mappings:
        provider_data["property_mappings"] = scope_mappings
    if signing_key:
        provider_data["signing_key"] = signing_key

    result = api_request("POST", "/api/v3/providers/oauth2/", provider_data)
    return result["pk"]


def create_application(provider_id: int) -> None:
    api_request(
        "POST",
        "/api/v3/core/applications/",
        {
            "name": APP_NAME,
            "slug": APP_SLUG,
            "provider": provider_id,
            "meta_launch_url": FRONTEND_URL,
        },
    )


def main() -> None:
    wait_for_authentik()

    if app_exists():
        print(f"Application '{APP_SLUG}' already exists, skipping setup.")
        return

    print("Setting up authentik OAuth2 provider and application...")

    auth_flow = get_flow("authorization", prefer_keyword="implicit")
    print(f"  Authorization flow: {auth_flow}")

    invalidation_flow = get_flow("invalidation")
    print(f"  Invalidation flow: {invalidation_flow}")

    scope_mappings = get_scope_mappings()
    print(f"  Scope mappings: {len(scope_mappings)} found")

    signing_key = get_signing_key()
    print(f"  Signing key: {signing_key or 'none (will use default)'}")

    provider_id = create_provider(
        auth_flow, invalidation_flow, scope_mappings, signing_key
    )
    print(f"  Created OAuth2 provider (id={provider_id})")

    create_application(provider_id)
    print(f"  Created application (slug={APP_SLUG})")

    print()
    print("authentik setup complete!")
    print(f"  App slug:      {APP_SLUG}")
    print(f"  Client ID:     {CLIENT_ID}")
    print("  Admin user:    akadmin")
    print("  Admin console: http://localhost:9100/if/admin/")


if __name__ == "__main__":
    main()
