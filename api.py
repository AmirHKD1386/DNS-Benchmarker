"""
DNS-Benchmarker — FastAPI Backend
Wraps the existing async benchmarking logic into REST + SSE endpoints.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import platform
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional, AsyncGenerator

# ── Ensure this file's directory is always on sys.path ───────────────────────
# Prevents "No module named 'dns'" when uvicorn is launched from a parent dir.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

import dns.asyncresolver
import dns.exception
import dns.resolver

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Windows stability fix ─────────────────────────────────────────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

app = FastAPI(title="DNS-Benchmarker API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Default configuration ─────────────────────────────────────────────────────
DEFAULT_DNS_SERVERS: list[dict] = [
    {"name": "Shecan",     "ip": "178.22.122.100", "secondary_ip": "178.22.122.101"},
    {"name": "Electro",    "ip": "78.157.42.100",  "secondary_ip": "78.157.42.104"},
    {"name": "RadarGame",  "ip": "10.10.10.10",    "secondary_ip": None},
    {"name": "Cloudflare", "ip": "1.1.1.1",        "secondary_ip": "1.0.0.1"},
    {"name": "Google",     "ip": "8.8.8.8",        "secondary_ip": "8.8.4.4"},
    {"name": "OpenDNS",    "ip": "208.67.222.222", "secondary_ip": "208.67.220.220"},
]

DEFAULT_TARGET_DOMAINS: list[str] = [
    "youtube.com",
    "hub.docker.com",
    "registry.npmjs.org",
    "pypi.org",
    "github.com",
    "githubusercontent.com",
    "api.openai.com",
]

DNS_TIMEOUT: float = 3.0
HTTP_TIMEOUT: float = 5.0
MAX_CONCURRENT: int = 20

BLOCK_PAGE_IPS: set[str] = set()
BLOCK_PAGE_KEYWORDS: list[str] = [
    "blocked", "access denied", "this site is not available",
    "the content is not available", "due to sanctions", "restricted",
]
SUCCESS_CODES: set[int] = {200, 301, 302, 303, 307, 308}
SANCTION_CODES: set[int] = {403, 451}


# ── Enums & Dataclasses ───────────────────────────────────────────────────────
class ConnectionStatus(str, Enum):
    BYPASS_SUCCESS = "BYPASS"
    SANCTIONED = "SANCTIONED"
    BLOCKED = "BLOCKED"
    FILTERED = "FILTERED"
    DNS_FAILED = "DNS_FAILED"
    PROBE_ERROR = "PROBE_ERROR"


@dataclass(frozen=True)
class DNSServer:
    name: str
    ip: str
    secondary_ip: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "DNSServer":
        return cls(name=d["name"], ip=d["ip"], secondary_ip=d.get("secondary_ip"))


@dataclass
class DNSResult:
    server_name: str
    server_ip: str
    domain: str
    resolved_ip: Optional[str]
    latency_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class HTTPResult:
    domain: str
    resolved_ip: str
    status_code: Optional[int]
    latency_ms: float
    error_msg: Optional[str] = None


@dataclass
class ProbeResult:
    dns: DNSResult
    http: Optional[HTTPResult]
    status: ConnectionStatus

    @property
    def is_bypass(self) -> bool:
        return self.status == ConnectionStatus.BYPASS_SUCCESS

    def to_dict(self) -> dict:
        return {
            "server_name": self.dns.server_name,
            "server_ip": self.dns.server_ip,
            "domain": self.dns.domain,
            "resolved_ip": self.dns.resolved_ip,
            "dns_latency_ms": round(self.dns.latency_ms, 1),
            "dns_success": self.dns.success,
            "dns_error": self.dns.error,
            "http_status_code": self.http.status_code if self.http else None,
            "http_latency_ms": round(self.http.latency_ms, 1) if self.http else None,
            "http_error": self.http.error_msg if self.http else None,
            "status": self.status.value,
            "is_bypass": self.is_bypass,
        }


# ── Core Logic ────────────────────────────────────────────────────────────────
def classify_result(dns: DNSResult, http: Optional[HTTPResult]) -> ConnectionStatus:
    if not dns.success or http is None:
        return ConnectionStatus.DNS_FAILED
    if http.status_code is None:
        err = (http.error_msg or "").lower()
        if any(k in err for k in ["timed out", "timeout", "connection refused", "reset", "ssl", "certificate"]):
            return ConnectionStatus.BLOCKED
        return ConnectionStatus.PROBE_ERROR
    if http.status_code in SANCTION_CODES:
        return ConnectionStatus.SANCTIONED
    if http.resolved_ip in BLOCK_PAGE_IPS:
        return ConnectionStatus.FILTERED
    if http.status_code in SUCCESS_CODES:
        return ConnectionStatus.BYPASS_SUCCESS
    return ConnectionStatus.PROBE_ERROR


async def resolve_domain(server: DNSServer, domain: str) -> DNSResult:
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = [server.ip]
    resolver.timeout = DNS_TIMEOUT
    resolver.lifetime = DNS_TIMEOUT

    start = time.perf_counter()
    try:
        answers = await resolver.resolve(domain, "A")
        latency_ms = (time.perf_counter() - start) * 1000
        if answers:
            return DNSResult(server_name=server.name, server_ip=server.ip,
                             domain=domain, resolved_ip=str(answers[0]),
                             latency_ms=latency_ms, success=True)
        return DNSResult(server_name=server.name, server_ip=server.ip,
                         domain=domain, resolved_ip=None, latency_ms=latency_ms,
                         success=False, error="No A records")
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return DNSResult(server_name=server.name, server_ip=server.ip,
                         domain=domain, resolved_ip=None, latency_ms=latency_ms,
                         success=False, error=str(exc)[:80])


async def probe_http(domain: str, resolved_ip: str) -> HTTPResult:
    http_request = (
        f"GET / HTTP/1.1\r\nHost: {domain}\r\n"
        f"User-Agent: DNS-Benchmarker/2.0\r\nAccept: */*\r\nConnection: close\r\n\r\n"
    ).encode()

    start = time.perf_counter()
    try:
        ssl_ctx = ssl.create_default_context()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(resolved_ip, 443, ssl=ssl_ctx, server_hostname=domain),
            timeout=HTTP_TIMEOUT,
        )
        writer.write(http_request)
        await writer.drain()
        response_data = await asyncio.wait_for(reader.read(4096), timeout=HTTP_TIMEOUT)
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except Exception:
            pass

        latency_ms = (time.perf_counter() - start) * 1000
        if not response_data:
            return HTTPResult(domain=domain, resolved_ip=resolved_ip,
                              status_code=None, latency_ms=latency_ms, error_msg="Empty response")

        status_line = response_data[:response_data.find(b"\r\n") or 128].decode("utf-8", errors="replace")
        parts = status_line.split(" ", 2)
        if len(parts) >= 2:
            try:
                code = int(parts[1])
                return HTTPResult(domain=domain, resolved_ip=resolved_ip,
                                  status_code=code, latency_ms=latency_ms)
            except ValueError:
                pass
        return HTTPResult(domain=domain, resolved_ip=resolved_ip,
                          status_code=None, latency_ms=latency_ms, error_msg="Parse error")

    except asyncio.TimeoutError:
        latency_ms = (time.perf_counter() - start) * 1000
        return HTTPResult(domain=domain, resolved_ip=resolved_ip,
                          status_code=None, latency_ms=latency_ms, error_msg="Connection timed out")
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return HTTPResult(domain=domain, resolved_ip=resolved_ip,
                          status_code=None, latency_ms=latency_ms, error_msg=str(exc)[:80])


async def probe_one(server: DNSServer, domain: str) -> ProbeResult:
    dns_result = await resolve_domain(server, domain)
    http_result = None
    if dns_result.success and dns_result.resolved_ip:
        http_result = await probe_http(domain, dns_result.resolved_ip)
    status = classify_result(dns_result, http_result)
    return ProbeResult(dns=dns_result, http=http_result, status=status)


def compute_tier_info(results: list[ProbeResult], servers_config: list[dict]) -> list[dict]:
    ip_lookup = {s["name"]: s["ip"] for s in servers_config}
    secondary_lookup = {s["name"]: s.get("secondary_ip") for s in servers_config}

    server_data: dict[str, dict] = {}
    for r in results:
        name = r.dns.server_name
        if name not in server_data:
            server_data[name] = {"bypass": 0, "total": 0, "dns_ms": 0.0,
                                  "http_ms": 0.0, "http_count": 0, "per_domain": {}}
        d = server_data[name]
        d["total"] += 1
        d["dns_ms"] += r.dns.latency_ms
        if r.http:
            d["http_ms"] += r.http.latency_ms
            d["http_count"] += 1
        if r.is_bypass:
            d["bypass"] += 1
        d["per_domain"][r.dns.domain] = {
            "status": r.status.value,
            "dns_ms": round(r.dns.latency_ms, 1),
            "http_ms": round(r.http.latency_ms, 1) if r.http else None,
            "http_code": r.http.status_code if r.http else None,
            "resolved_ip": r.dns.resolved_ip,
        }

    infos = []
    for name, d in server_data.items():
        avg_dns = d["dns_ms"] / d["total"] if d["total"] else 0
        avg_http = d["http_ms"] / d["http_count"] if d["http_count"] else 0
        bypass_pct = (d["bypass"] / d["total"] * 100) if d["total"] else 0
        tier = "A" if d["bypass"] == d["total"] and d["bypass"] > 0 else (
               "F" if d["bypass"] == 0 else "B")
        infos.append({
            "name": name,
            "ip": ip_lookup.get(name, "?"),
            "secondary_ip": secondary_lookup.get(name),
            "bypass_count": d["bypass"],
            "total_count": d["total"],
            "bypass_pct": round(bypass_pct, 0),
            "avg_dns_ms": round(avg_dns, 1),
            "avg_http_ms": round(avg_http, 1),
            "tier": tier,
            "per_domain": d["per_domain"],
        })
    return infos


# ── OS / Admin helpers ────────────────────────────────────────────────────────
def is_admin() -> bool:
    try:
        if sys.platform == "win32":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def get_active_windows_interface() -> Optional[str]:
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | Select-Object -First 1 -ExpandProperty Name"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def set_system_dns(dns_ips: list[str], server_name: str) -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Windows":
            interface = get_active_windows_interface()
            if not interface:
                return False, "Could not detect active network interface."
            ips_ps = "'" + "', '".join(dns_ips) + "'"
            cmd = ["powershell", "-Command",
                   f"Set-DnsClientServerAddress -InterfaceAlias '{interface}' -ServerAddresses ({ips_ps})"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode != 0:
                return False, result.stderr.strip()
            return True, f"DNS set on interface '{interface}'"

        elif system == "Linux":
            lines = [f"nameserver {ip}" for ip in dns_ips]
            with open("/etc/resolv.conf", "w") as f:
                f.write("\n".join(lines) + "\n")
            return True, "Written to /etc/resolv.conf"

        elif system == "Darwin":
            result = subprocess.run(["networksetup", "-listallnetworkservices"],
                                    capture_output=True, text=True, timeout=10)
            services = [s.strip() for s in result.stdout.strip().split("\n")[1:]
                        if s.strip() and not s.startswith("*")]
            if not services:
                return False, "No network services found."
            target = next((s for s in services if "wi-fi" in s.lower() or "ethernet" in s.lower()), services[0])
            cmd = ["networksetup", "-setdnsservers", target] + dns_ips
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0, result.stderr.strip() or f"Set on '{target}'"

        return False, f"Unsupported OS: {system}"
    except PermissionError:
        return False, "Permission denied. Run the backend with administrator/sudo privileges."
    except Exception as exc:
        return False, str(exc)


def reset_system_dns() -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Windows":
            interface = get_active_windows_interface()
            if not interface:
                return False, "Could not detect active network interface."
            subprocess.run(
                ["powershell", "-Command",
                 f"Set-DnsClientServerAddress -InterfaceAlias '{interface}' -ResetServerAddresses"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return True, f"DNS reverted to DHCP on '{interface}', cache flushed."

        elif system == "Linux":
            try:
                subprocess.run(["resolvectl", "revert"], capture_output=True, timeout=10)
            except Exception:
                pass
            try:
                subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=10)
            except Exception:
                pass
            return True, "DNS reverted (resolvectl) and cache flushed."

        elif system == "Darwin":
            result = subprocess.run(["networksetup", "-listallnetworkservices"],
                                    capture_output=True, text=True, timeout=10)
            services = [s.strip() for s in result.stdout.strip().split("\n")[1:]
                        if s.strip() and not s.startswith("*")]
            if services:
                target = next((s for s in services if "wi-fi" in s.lower() or "ethernet" in s.lower()), services[0])
                subprocess.run(["networksetup", "-setdnsservers", target, "Empty"],
                               capture_output=True, timeout=10)
            subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=10)
            return True, "DNS reverted to DHCP, mDNS cache flushed."

        return False, f"Unsupported OS: {system}"
    except Exception as exc:
        return False, str(exc)


def flush_dns_cache() -> tuple[bool, str]:
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        elif system == "Linux":
            subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=10)
        elif system == "Darwin":
            subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=10)
        return True, f"DNS cache flushed on {system}."
    except Exception as exc:
        return False, str(exc)


# ── Pydantic request models ───────────────────────────────────────────────────
class CustomServer(BaseModel):
    name: str
    ip: str
    secondary_ip: Optional[str] = None


class BenchmarkRequest(BaseModel):
    custom_servers: list[CustomServer] = []
    include_defaults: bool = True
    target_domains: Optional[list[str]] = None


class ApplyDNSRequest(BaseModel):
    server_name: str
    primary_ip: str
    secondary_ip: Optional[str] = None


# ── API Endpoints ─────────────────────────────────────────────────────────────
@app.get("/api/config")
async def get_config():
    return {
        "dns_servers": DEFAULT_DNS_SERVERS,
        "target_domains": DEFAULT_TARGET_DOMAINS,
        "dns_timeout": DNS_TIMEOUT,
        "http_timeout": HTTP_TIMEOUT,
        "max_concurrent": MAX_CONCURRENT,
        "os": platform.system(),
        "is_admin": is_admin(),
    }


@app.post("/api/benchmark/stream")
async def benchmark_stream(request: BenchmarkRequest):
    """SSE endpoint — streams probe results as they complete."""

    servers_config: list[dict] = []
    if request.include_defaults:
        servers_config.extend(DEFAULT_DNS_SERVERS)
    for cs in request.custom_servers:
        try:
            ipaddress.ip_address(cs.ip)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid IP: {cs.ip}")
        servers_config.append({"name": cs.name or f"Custom-{cs.ip}", "ip": cs.ip,
                                "secondary_ip": cs.secondary_ip})

    if not servers_config:
        raise HTTPException(status_code=400, detail="No DNS servers specified.")

    domains = request.target_domains or DEFAULT_TARGET_DOMAINS

    async def event_stream() -> AsyncGenerator[str, None]:
        total = len(servers_config) * len(domains)
        completed = 0
        t0 = time.perf_counter()
        all_results: list[ProbeResult] = []

        # Send config header
        yield f"data: {json.dumps({'type': 'start', 'total': total, 'servers': len(servers_config), 'domains': len(domains)})}\n\n"

        sem = asyncio.Semaphore(MAX_CONCURRENT)
        result_queue: asyncio.Queue = asyncio.Queue()

        async def probe_and_enqueue(server: DNSServer, domain: str):
            async with sem:
                result = await probe_one(server, domain)
                await result_queue.put(result)

        tasks = [
            asyncio.create_task(probe_and_enqueue(DNSServer.from_dict(s), domain))
            for s in servers_config
            for domain in domains
        ]

        while completed < total:
            result = await result_queue.get()
            all_results.append(result)
            completed += 1
            elapsed = time.perf_counter() - t0

            payload = {
                "type": "probe",
                "completed": completed,
                "total": total,
                "elapsed_s": round(elapsed, 1),
                **result.to_dict(),
            }
            yield f"data: {json.dumps(payload)}\n\n"

        await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - t0

        tier_info = compute_tier_info(all_results, servers_config)
        yield f"data: {json.dumps({'type': 'complete', 'elapsed_s': round(elapsed, 2), 'tiers': tier_info})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/dns/apply")
async def apply_dns(request: ApplyDNSRequest):
    if not is_admin():
        raise HTTPException(status_code=403,
                            detail="Administrator privileges required. Restart the backend with sudo/admin.")
    dns_ips = [request.primary_ip]
    if request.secondary_ip:
        dns_ips.append(request.secondary_ip)
    success, message = set_system_dns(dns_ips, request.server_name)
    if not success:
        raise HTTPException(status_code=500, detail=message)
    return {"success": True, "message": message, "applied_ips": dns_ips}


@app.post("/api/dns/reset")
async def reset_dns():
    if not is_admin():
        raise HTTPException(status_code=403,
                            detail="Administrator privileges required. Restart the backend with sudo/admin.")
    success, message = reset_system_dns()
    if not success:
        raise HTTPException(status_code=500, detail=message)
    return {"success": True, "message": message}


@app.post("/api/dns/flush-cache")
async def flush_cache():
    success, message = flush_dns_cache()
    return {"success": success, "message": message}


@app.get("/api/health")
async def health():
    return {"status": "ok", "os": platform.system(), "is_admin": is_admin()}
