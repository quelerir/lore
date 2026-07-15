import time
import jwt
import pytest
import auth

SECRET = "test-secret-that-is-32-bytes-long!!"


def _token(**over):
    payload = {
        "sub": "42",
        "username": "alice",
        "aud": "chainlit",
        "iss": "datacraft",
        "exp": int(time.time()) + 60,
    }
    payload.update(over)
    return jwt.encode(payload, SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", SECRET)
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")


def test_valid_ticket_returns_sub_and_username():
    claims = auth.verify_ticket(_token())
    assert claims == {"sub": "42", "username": "alice"}


def test_expired_ticket_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(exp=int(time.time()) - 10))


def test_wrong_audience_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(aud="someone-else"))


def test_wrong_issuer_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(_token(iss="attacker"))


def test_bad_signature_rejected():
    bad = jwt.encode(
        {"sub": "1", "aud": "chainlit", "iss": "datacraft"},
        "wrong-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_ticket(bad)
