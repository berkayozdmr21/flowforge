"""Bounded HTTP JSON requests to public hosts; no proxies or redirects."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from urllib.parse import urlsplit, quote

MAX_RESPONSE = 1024 * 1024
MAX_REQUEST = 1024 * 1024
RESERVED = {
    "host",
    "authorization",
    "cookie",
    "proxy-authorization",
    "connection",
    "content-length",
    "transfer-encoding",
    "accept-encoding",
    "idempotency-key",
}


def public_address(address):
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not getattr(address, "ipv4_mapped", None)
        and not getattr(address, "sixtofour", None)
        and not getattr(address, "teredo", None)
    )


def validate_url(url):
    try:
        parts = urlsplit(url)
        port = parts.port
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.fragment
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)
            or "\\" in url
            or port not in {None, 80, 443}
        ):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
        if host.lower().rstrip(".") == "localhost":
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not public_address(address):
            raise ValueError()
        return parts
    except (ValueError, UnicodeError):
        raise ValueError(
            "HTTP URL geçersiz: genel bir http/https adresi ve 80/443 portu kullan."
        ) from None


def validate_headers(headers):
    for key, value in headers.items():
        if (
            not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,100}", key)
            or key.lower() in RESERVED
            or len(value) > 2000
            or any(ord(c) < 32 or ord(c) > 126 for c in value)
        ):
            raise ValueError(
                "HTTP başlıkları geçersiz; kimlik doğrulama için token ortam değişkenini kullan."
            )


def resolve_public(host, port):
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise OSError("HTTP sunucusunun DNS adresi çözülemedi.") from None
    addresses = list(dict.fromkeys(item[4][0] for item in results))
    if not addresses or any(
        not public_address(ipaddress.ip_address(ip)) for ip in addresses
    ):
        raise ValueError(
            "HTTP isteği özel, yerel veya ayrılmış ağ adreslerine gönderilemez."
        )
    return addresses[0]


class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self.ip = ip

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)


class PinnedHTTPS(PinnedHTTP):
    def connect(self):
        super().connect()
        try:
            self.sock = ssl.create_default_context().wrap_socket(
                self.sock, server_hostname=self.host
            )
        except BaseException:
            self.sock.close()
            raise


def response_records(value, path):
    for key in path.split(".") if path else []:
        if not isinstance(value, dict) or key not in value:
            raise ValueError("HTTP yanıtında seçilen alan yolu bulunamadı.")
        value = value[key]
    rows = [value] if isinstance(value, dict) else value
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(
            "HTTP JSON yanıtı bir nesne veya nesne listesi olmalı; gerekirse yanıt yolunu seç."
        )
    if len(rows) > 10000:
        raise ValueError("HTTP yanıtı 10.000 kayıt sınırını aşıyor.")
    return rows


def request_json(config, inputs, request_key):
    started = time.monotonic()
    parts = validate_url(config["url"])
    validate_headers(config["headers"])
    host = parts.hostname.encode("idna").decode("ascii")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    headers = {
        "Accept": "application/json",
        "User-Agent": "FlowForge/1.0",
        "Accept-Encoding": "identity",
        **config["headers"],
    }
    if config["tokenEnv"]:
        token = os.environ.get("FLOWFORGE_HTTP_TOKEN_" + config["tokenEnv"])
        if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("HTTP token ortam değişkeni eksik veya geçersiz.")
        if parts.scheme != "https":
            raise ValueError("Token yalnızca HTTPS üzerinden gönderilebilir.")
        headers["Authorization"] = "Bearer " + token
    body = None
    if config["method"] == "POST":
        value = (
            (inputs[0]["records"] if inputs else [])
            if config["bodySource"] == "records"
            else config["body"]
        )
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(body) > MAX_REQUEST:
            raise ValueError("HTTP istek gövdesi 1 MB sınırını aşıyor.")
        headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = request_key
    connection = None
    try:
        ip = resolve_public(host, port)
        remaining = config["timeoutSeconds"] - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError()
        connection = (PinnedHTTPS if parts.scheme == "https" else PinnedHTTP)(
            host, port, ip, remaining
        )
        target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            target += "?" + quote(parts.query, safe="%=&?/:@!$'()*+,;~-._")
        connection.request(config["method"], target, body=body, headers=headers)
        response = connection.getresponse()
        status = response.status
        if not 200 <= status < 300:
            message = f"HTTP {status}: API başarılı bir yanıt döndürmedi."
            if config["method"] == "GET" and (status in {408, 429} or status >= 500):
                raise OSError(message)
            raise ValueError(message)
        content_type = (
            response.getheader("Content-Type", "").split(";")[0].strip().lower()
        )
        if content_type != "application/json" and not content_type.endswith("+json"):
            raise ValueError("HTTP yanıtının Content-Type değeri JSON olmalı.")
        chunks, size = [], 0
        while True:
            remaining = config["timeoutSeconds"] - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError()
            if connection.sock:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError("HTTP yanıtı 1 MB sınırını aşıyor.")
        try:
            value = json.loads(
                b"".join(chunks),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
            json.dumps(value, allow_nan=False)
        except (UnicodeError, ValueError, RecursionError):
            raise ValueError("HTTP yanıtı geçerli JSON içermiyor.") from None
        rows = response_records(value, config["responsePath"])
        return {
            "schemaVersion": 1,
            "records": rows,
            "meta": {
                "count": len(rows),
                "inputCount": sum(len(x["records"]) for x in inputs),
                "http": {
                    "status": status,
                    "method": config["method"],
                    "bytes": size,
                    "durationMs": round((time.monotonic() - started) * 1000),
                },
            },
        }, "out"
    except (OSError, http.client.HTTPException) as exc:
        # Never persist third-party response bodies, headers, URLs or token values in errors.
        message = (
            str(exc)
            if str(exc).startswith("HTTP ")
            else "HTTP bağlantısı tamamlanamadı veya zaman aşımına uğradı."
        )
        if config["method"] == "POST":
            raise ValueError(
                message
                + " POST otomatik yeniden denenmez; uzak işlem durumunu kontrol et."
            ) from None
        raise OSError(message) from None
    finally:
        if connection:
            connection.close()
