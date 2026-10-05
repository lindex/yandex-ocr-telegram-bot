"""Самопроверка: uv run python test_bot.py"""
import base64
import os

for k, v in {"TG_TOKEN": "1:x", "TG_API_ID": "1", "TG_API_HASH": "x", "YC_API_KEY": "x", "YC_FOLDER_ID": "x"}.items():
    os.environ.setdefault(k, v)

from TelethonFakeTLS.FakeTLS import MTProxyFakeTLSClientCodec  # noqa: E402

from bot import parse_proxy  # noqa: E402

key, domain = "0123456789abcdef0123456789abcdef", b"www.google.com".hex()

cls, proxy = parse_proxy(f"tg://proxy?server=1.2.3.4&port=443&secret=ee{key}{domain}")
assert cls.__name__ == "ConnectionTcpMTProxyFakeTLS" and proxy == ("1.2.3.4", 443, key + domain)
codec = MTProxyFakeTLSClientCodec(proxy[2])
assert codec.secret.hex() == key and codec.domain == b"www.google.com"

b64 = base64.urlsafe_b64encode(bytes.fromhex(f"ee{key}{domain}")).decode().rstrip("=")
assert parse_proxy(f"https://t.me/proxy?server=h&port=443&secret={b64}")[1][2] == key + domain
assert parse_proxy(f"tg://proxy?server=h&port=1&secret=dd{key}")[0].__name__ == "ConnectionTcpMTProxyRandomizedIntermediate"
assert parse_proxy(f"tg://proxy?server=h&port=1&secret={key}")[0].__name__ == "ConnectionTcpMTProxyIntermediate"
print("ok")

from bot import Settings  # noqa: E402

s = Settings(tg_admins="1, 2", tg_allowed_users="3", access_mode="private")
assert s.tg_admins == [1, 2] and s.is_allowed(1) and s.is_allowed(3) and not s.is_allowed(4)
assert Settings(access_mode="public").is_allowed(4)
assert Settings(tg_admins="").tg_admins == [] and not Settings(tg_admins="").is_allowed(1)
print("access ok")
