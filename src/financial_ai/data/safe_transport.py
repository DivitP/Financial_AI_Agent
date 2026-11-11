"""Allowlisted HTTPS downloads pinned to validated public IPs (no environment proxies)."""

import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

from financial_ai.data.http import HttpRequest, HttpResponse, HttpResponseTooLargeError


class UnsafeDestination(ValueError):
    pass


class SafeTransport:
    def __init__(
        self, hosts, *, resolver=socket.getaddrinfo, max_redirects=2, return_redirects=False
    ):
        self.hosts = frozenset(hosts)
        self.resolver = resolver
        self.max_redirects = max_redirects
        self.return_redirects = return_redirects
        if not self.hosts or any(
            not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", h) for h in self.hosts
        ):
            raise UnsafeDestination("Configure explicit lowercase document hostnames")
        if not 0 <= max_redirects <= 3:
            raise ValueError("At most three redirects are permitted")

    def resolve(self, url):
        if len(url) > 4096 or re.search(r"[\x00-\x20\x7f\\]", url):
            raise UnsafeDestination("Invalid document URL")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.port not in (None, 443)
            or parsed.hostname not in self.hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise UnsafeDestination("Document URL is outside the approved HTTPS hosts")
        addresses = self.resolver(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise UnsafeDestination("Document host has no public addresses")
        for _, _, _, _, address in addresses:
            ip = ipaddress.ip_address(address[0])
            if (
                not ip.is_global
                or ip.is_multicast
                or getattr(ip, "ipv4_mapped", None)
                or getattr(ip, "sixtofour", None)
                or getattr(ip, "teredo", None)
                or (ip.version == 6 and ip in ipaddress.ip_network("64:ff9b::/96"))
            ):
                raise UnsafeDestination("Non-public document destination blocked")
        return parsed, addresses[0]

    @staticmethod
    def _connection(host, address, timeout):
        family, socktype, protocol, _, sockaddr = address
        connection = http.client.HTTPSConnection(
            host, timeout=timeout, context=ssl.create_default_context()
        )

        def pinned_socket(*args, **kwargs):
            sock = socket.socket(family, socktype, protocol)
            try:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                return sock
            except BaseException:
                sock.close()
                raise

        # TLS still verifies the original hostname and sends its SNI.
        connection._create_connection = pinned_socket  # type: ignore[attr-defined]
        return connection

    def __call__(self, request: HttpRequest, timeout: float, max_bytes: int) -> HttpResponse:
        if request.method != "GET" or request.body is not None:
            raise UnsafeDestination("Document downloads are read-only GET requests")
        if timeout <= 0 or max_bytes <= 0:
            raise ValueError("Download limits must be positive")
        deadline = time.monotonic() + timeout
        url = request.url
        for hop in range(self.max_redirects + 1):
            parsed, address = self.resolve(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Document download timed out")
            connection = self._connection(parsed.hostname, address, remaining)
            try:
                headers = {
                    k: v
                    for k, v in request.headers.items()
                    if k.lower() in {"user-agent", "accept"}
                }
                headers["Accept-Encoding"] = "identity"
                connection.request(
                    "GET",
                    parsed.path or "/"
                    if not parsed.query
                    else (parsed.path or "/") + "?" + parsed.query,
                    headers=headers,
                )
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    if self.return_redirects:
                        # Callers that explicitly handle redirects must recheck
                        # destination policy (including robots) before another GET.
                        return HttpResponse(response.status, dict(response.getheaders()), b"")
                    location = response.getheader("Location")
                    if hop == self.max_redirects or not location:
                        raise UnsafeDestination("Document redirect limit exceeded")
                    url = urljoin(url, location)
                    continue
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise UnsafeDestination("Compressed document downloads are not permitted")
                mime = response.getheader("Content-Type", "").split(";")[0].lower()
                if mime not in {
                    "text/html",
                    "text/plain",
                    "application/json",
                    "application/xml",
                    "text/xml",
                    "application/rss+xml",
                    "application/atom+xml",
                    "application/xhtml+xml",
                }:
                    raise UnsafeDestination("Unsupported document content type")
                length = response.getheader("Content-Length")
                if length and (not length.isdecimal() or int(length) > max_bytes):
                    raise HttpResponseTooLargeError("Document exceeds download limit")
                body = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("Document download timed out")
                    if connection.sock:
                        connection.sock.settimeout(remaining)
                    block = response.read1(min(65536, max_bytes + 1 - len(body)))
                    body.extend(block)
                    if len(body) > max_bytes:
                        raise HttpResponseTooLargeError("Document exceeds download limit")
                    if not block:
                        break
                return HttpResponse(response.status, dict(response.getheaders()), bytes(body))
            finally:
                connection.close()
        raise UnsafeDestination("Document redirect limit exceeded")
