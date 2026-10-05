"""Самопроверка: uv run python test_bot.py"""
import base64
import os
import tempfile

DATA = tempfile.mkdtemp()
for k, v in {"TG_TOKEN": "1:x", "TG_API_ID": "1", "TG_API_HASH": "x", "YC_API_KEY": "x", "YC_FOLDER_ID": "x",
             "TG_ADMINS": "1, 2", "ACCESS_MODE": "private", "DATA_DIR": DATA}.items():
    os.environ[k] = v

from TelethonFakeTLS.FakeTLS import MTProxyFakeTLSClientCodec  # noqa: E402

import bot  # noqa: E402

# Разбор tg://proxy
key, domain = "0123456789abcdef0123456789abcdef", b"www.google.com".hex()

cls, proxy = bot.parse_proxy(f"tg://proxy?server=1.2.3.4&port=443&secret=ee{key}{domain}")
assert cls.__name__ == "ConnectionTcpMTProxyFakeTLS" and proxy == ("1.2.3.4", 443, key + domain)
codec = MTProxyFakeTLSClientCodec(proxy[2])
assert codec.secret.hex() == key and codec.domain == b"www.google.com"

b64 = base64.urlsafe_b64encode(bytes.fromhex(f"ee{key}{domain}")).decode().rstrip("=")
assert bot.parse_proxy(f"https://t.me/proxy?server=h&port=443&secret={b64}")[1][2] == key + domain
assert bot.parse_proxy(f"tg://proxy?server=h&port=1&secret=dd{key}")[0].__name__ == "ConnectionTcpMTProxyRandomizedIntermediate"
assert bot.parse_proxy(f"tg://proxy?server=h&port=1&secret={key}")[0].__name__ == "ConnectionTcpMTProxyIntermediate"

# Доступ
assert bot.settings.tg_admins == [1, 2]
assert bot.is_allowed(1) and not bot.is_allowed(3)
bot.users.add(3)
assert bot.is_allowed(3)
assert bot.Users(bot.users.path).ids == {3}, "список должен переживать рестарт"
assert bot.users.remove(3) and not bot.users.remove(3) and not bot.is_allowed(3)
bot.settings.access_mode = "public"
assert bot.is_allowed(3)
print("ok")
