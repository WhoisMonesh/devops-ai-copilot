# agent/tools/ssl_tool.py
# SSL/TLS Certificate and Security tools for DevOps AI Copilot

import logging
import socket
import ssl
from datetime import datetime
from typing import Optional

import requests
from OpenSSL import crypto
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _get_ssl_context():
    """Create SSL context that doesn't verify certificates."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_cert(host: str, port: int = 443, timeout: int = 10) -> Optional[dict]:
    """Fetch SSL certificate from a host and return parsed info."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ssl.wrap_socket(sock, cert_reqs=ssl.CERT_NONE) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                x509 = crypto.load_certificate(crypto.FILETYPE_ASN1, cert_der)
                return {
                    "subject": dict(x509.get_subject().get_components()),
                    "issuer": dict(x509.get_issuer().get_components()),
                    "serial_number": x509.get_serial_number(),
                    "not_before": datetime.strptime(
                        x509.get_notBefore().decode("ascii"), "%Y%m%d%H%M%SZ"
                    ),
                    "not_after": datetime.strptime(
                        x509.get_notAfter().decode("ascii"), "%Y%m%d%H%M%SZ"
                    ),
                    "version": x509.get_version(),
                    "signature_algorithm": x509.get_signature_algorithm().decode(),
                }
    except Exception as e:
        return {"error": str(e)}


def _days_until_expiry(not_after: datetime) -> int:
    return (not_after - datetime.now()).days


@tool
def ssl_check_host(host: str, port: int = 443) -> str:
    """Check SSL certificate for a host and report expiry status.
    Args:
      host - Hostname (e.g., example.com)
      port - Port number (default: 443)"""
    try:
        cert = _fetch_cert(host, port)
        if not cert or "error" in cert:
            return f"Error fetching SSL cert for {host}:{port} - {cert.get('error', 'Unknown error')}"

        subject = cert["subject"].get(b"CN", b"Unknown").decode()
        issuer = cert["issuer"].get(b"CN", b"Unknown").decode()
        days_left = _days_until_expiry(cert["not_after"])

        lines = [
            f"SSL Certificate for {host}:{port}:",
            f"  Common Name (CN): {subject}",
            f"  Issuer: {issuer}",
            f"  Valid From: {cert['not_before'].strftime('%Y-%m-%d')}",
            f"  Expires: {cert['not_after'].strftime('%Y-%m-%d')}",
            f"  Days Until Expiry: {days_left}",
            f"  Serial: {hex(cert['serial_number'])}",
            f"  Signature Algorithm: {cert['signature_algorithm']}",
        ]

        if days_left < 0:
            lines.append(f"  STATUS: EXPIRED {abs(days_left)} days ago!")
        elif days_left < 7:
            lines.append(f"  STATUS: CRITICAL - expires in {days_left} days!")
        elif days_left < 30:
            lines.append(f"  STATUS: WARNING - expires in {days_left} days")
        elif days_left < 90:
            lines.append(f"  STATUS: NOTICE - expires in {days_left} days")
        else:
            lines.append("  STATUS: OK")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("ssl_check_host failed")
        return f"Error checking SSL cert: {e}"


@tool
def ssl_batch_check(hosts: str, port: int = 443) -> str:
    """Check SSL certificates for multiple hosts.
    Args:
      hosts - Comma-separated list of hostnames (e.g., example.com,google.com)
      port - Port number (default: 443)"""
    try:
        host_list = [h.strip() for h in hosts.split(",")]
        lines = [f"SSL Certificate Check - {len(host_list)} hosts:"]

        for host in host_list:
            cert = _fetch_cert(host, port)
            if not cert or "error" in cert:
                lines.append(f"  {host}: ERROR - {cert.get('error', 'Failed')}")
            else:
                days_left = _days_until_expiry(cert["not_after"])
                expiry = cert["not_after"].strftime("%Y-%m-%d")
                if days_left < 0:
                    status = "EXPIRED"
                elif days_left < 7:
                    status = "CRITICAL"
                elif days_left < 30:
                    status = "WARNING"
                elif days_left < 90:
                    status = "NOTICE"
                else:
                    status = "OK"
                lines.append(f"  {host}: {status} ({days_left}d, expires {expiry})")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("ssl_batch_check failed")
        return f"Error in batch SSL check: {e}"


@tool
def ssl_get_cert_chain(host: str, port: int = 443) -> str:
    """Get full SSL certificate chain for a host.
    Args:
      host - Hostname
      port - Port number (default: 443)"""
    try:
        with socket.create_connection((host, port), timeout=10):
            cert_der = ssl.get_server_certificate((host, port)).encode()
            x509 = crypto.load_certificate(crypto.FILETYPE_PEM, cert_der)

            subject = x509.get_subject()
            issuer = x509.get_issuer()

            subject_cn = subject.commonName if hasattr(subject, 'commonName') else dict(subject.get_components()).get(b"CN", b"?").decode()
            issuer_cn = issuer.commonName if hasattr(issuer, 'commonName') else dict(issuer.get_components()).get(b"CN", b"?").decode()

            lines = [
                f"SSL Certificate Chain for {host}:{port}:",
                f"  Subject CN: {subject_cn}",
                f"  Issuer CN: {issuer_cn}",
                f"  Version: {x509.get_version() + 1}",
                f"  Serial: {hex(x509.get_serial_number())}",
                f"  Valid: {datetime.strptime(x509.get_notBefore().decode('ascii'), '%Y%m%d%H%M%SZ').strftime('%Y-%m-%d')} to {datetime.strptime(x509.get_notAfter().decode('ascii'), '%Y%m%d%H%M%SZ').strftime('%Y-%m-%d')}",
            ]
            return "\n".join(lines)
    except Exception as e:
        logger.exception("ssl_get_cert_chain failed")
        return f"Error getting cert chain: {e}"


@tool
def dns_lookup(hostname: str, record_type: str = "A") -> str:
    """Perform DNS lookup for a hostname.
    Args:
      hostname - Hostname to lookup
      record_type - DNS record type: A, AAAA, CNAME, MX, TXT, NS (default: A)"""
    try:
        import dns.resolver
        resolver = dns.resolver.Resolver()
        resolver.timeout = 5
        resolver.lifetime = 10

        answers = resolver.resolve(hostname, record_type)

        lines = [f"DNS Lookup: {hostname} ({record_type})"]
        for rdata in answers:
            lines.append(f"  -> {rdata}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("dns_lookup failed")
        return f"DNS lookup failed for {hostname}: {e}"


@tool
def http_headers_check(url: str) -> str:
    """Check HTTP headers and security headers for a URL.
    Args:
      url - Full URL to check (e.g., https://example.com)"""
    try:
        resp = requests.head(url, timeout=15, verify=False, allow_redirects=True)
        resp.raise_for_status()

        security_headers = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "X-XSS-Protection",
            "Referrer-Policy",
        ]

        lines = [f"HTTP Headers for {url}:", f"  Status: {resp.status_code}"]

        # Standard headers
        standard = ["Server", "Content-Type", "Content-Length", "Cache-Control", "Set-Cookie"]
        for h in standard:
            if h in resp.headers:
                lines.append(f"  {h}: {resp.headers[h]}")

        # Security headers
        lines.append("  Security Headers:")
        found_security = False
        for h in security_headers:
            if h in resp.headers:
                lines.append(f"    {h}: {resp.headers[h]}")
                found_security = True
        if not found_security:
            lines.append("    (none found)")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("http_headers_check failed")
        return f"Error checking HTTP headers: {e}"


SSL_TOOLS = [
    ssl_check_host,
    ssl_batch_check,
    ssl_get_cert_chain,
    dns_lookup,
    http_headers_check,
]
