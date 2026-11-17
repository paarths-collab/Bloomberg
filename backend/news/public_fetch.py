"""Bounded article fetching with DNS-pinned, public-only connections and redirects."""
import http.client
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

MAX_ARTICLE_BYTES = 2 * 1024 * 1024


class UnsafeArticleURL(ValueError):
    pass


def _is_public_address(value):
    address = ipaddress.ip_address(value)
    if not address.is_global or address.is_multicast:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return _is_public_address(address.ipv4_mapped)
        # Transition/translation addresses can embed a private IPv4 destination
        # even when ipaddress classifies the outer IPv6 address as global.
        if address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network('64:ff9b::/96'):
            return False
    return True


def validate_article_url(url):
    try:
        parts = urlsplit(url)
        port = parts.port
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or port not in (None, 80, 443) or any(ord(c) < 33 for c in url)):
            raise ValueError()
        try:
            address = ipaddress.ip_address(parts.hostname)
        except ValueError:
            address = None
        if address is not None and not _is_public_address(address):
            raise ValueError()
    except ValueError:
        raise UnsafeArticleURL("Article URL must identify a public HTTP(S) server on port 80 or 443")
    return parts


def _public_socket(host, port, timeout):
    # Resolve once and connect directly to that sockaddr. A second DNS lookup would
    # allow a rebinding host to pass validation and then connect to a private IP.
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not _is_public_address(a[4][0]) for a in addresses):
        raise UnsafeArticleURL("Article URL must resolve only to public addresses")
    last_error = None
    for family, socktype, proto, _, address in addresses:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error


class _PublicHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = _public_socket(self.host, self.port, self.timeout)


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        sock = _public_socket(self.host, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def fetch_public_html(url):
    for _ in range(6):
        parts = validate_article_url(url)
        connection_type = _PublicHTTPSConnection if parts.scheme == "https" else _PublicHTTPConnection
        connection = connection_type(parts.hostname, port=parts.port, timeout=10)
        try:
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers={"User-Agent": "Bloomberg-ArticleReader/1.0", "Accept": "text/html"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            if response.status >= 400:
                return None
            body = response.read(MAX_ARTICLE_BYTES + 1)
            if len(body) > MAX_ARTICLE_BYTES:
                return None
            return body.decode("utf-8", errors="replace")
        finally:
            connection.close()
    return None
