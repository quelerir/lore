import os
import jwt


def verify_ticket(token: str) -> dict[str, str]:
    """Validate a datacraft-issued HS256 ticket, return {sub, username}.

    Raises jwt.InvalidTokenError (or subclass) on any validation failure.
    """
    payload = jwt.decode(
        token,
        os.environ["CHAINLIT_JWT_SECRET"],
        algorithms=["HS256"],
        audience=os.environ["CHAINLIT_JWT_AUDIENCE"],
        issuer=os.environ["CHAINLIT_JWT_ISSUER"],
        options={"require": ["exp", "sub", "aud", "iss"]},
    )
    return {
        "sub": str(payload["sub"]),
        "username": str(payload.get("username", payload["sub"])),
    }
