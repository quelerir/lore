import jwt

from config import get_settings


def verify_ticket(token: str) -> dict[str, str]:
    """Validate a datacraft-issued HS256 ticket, return {sub, username}.

    Raises jwt.InvalidTokenError (or subclass) on any validation failure.
    """
    s = get_settings()
    payload = jwt.decode(
        token,
        s.jwt_secret,
        algorithms=["HS256"],
        audience=s.jwt_audience,
        issuer=s.jwt_issuer,
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    return {
        "sub": str(payload["sub"]),
        "username": str(payload.get("username", payload["sub"])),
    }
