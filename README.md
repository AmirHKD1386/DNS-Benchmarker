# DNS Benchmarker — Web Edition

A full-stack local web application that transforms the DNS-Benchmarker CLI into a
premium dark-mode dashboard. A FastAPI backend wraps all async benchmarking logic
and OS-level DNS commands; a single-file React frontend delivers live progress,
tier-ranked results, and one-click DNS application.

---

## Architecture

```
dns-benchmarker-web/
├── backend/
│   ├── api.py           ← FastAPI backend (all benchmark + OS logic)
│   ├── start.py         ← Launcher script
│   └── dns_resolver.py  ← Original CLI (kept for reference)
├── frontend/
│   └── index.html       ← Single-file React + Tailwind dashboard
└── README.md
```

**Data flow:**
```
Browser (index.html)
  └─ POST /api/benchmark/stream  ──▶  FastAPI (api.py)
       SSE stream of probe results ◀──   asyncio probes
  └─ POST /api/dns/apply         ──▶  subprocess (PowerShell / networksetup / resolv.conf)
  └─ POST /api/dns/reset         ──▶  subprocess DHCP revert + cache flush
  └─ POST /api/dns/flush-cache   ──▶  ipconfig/resolvectl/mDNSResponder
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install fastapi uvicorn dnspython
```

### 2. Start the backend

**Standard (benchmark only — no DNS apply):**
```bash
cd backend
python start.py
```

**With admin privileges (enables DNS apply + reset):**
```bash
# Windows — run terminal as Administrator, then:
python start.py

# macOS / Linux:
sudo python start.py
```

Backend runs at `http://localhost:8765`

### 3. Open the frontend

Open `frontend/index.html` in any modern browser.
No build step. No npm. No bundler.

---

## Features

| Feature | Description |
|---|---|
| **Live SSE stream** | Probe results appear in real-time as each (server × domain) completes |
| **Tier A / B / F cards** | Servers grouped by bypass capability with expandable domain breakdowns |
| **One-click DNS apply** | Sets primary + secondary IPs via OS subprocess (requires admin) |
| **DHCP reset** | Reverts all manual DNS entries and flushes OS cache |
| **Cache flush** | Standalone cache flush without changing DNS settings |
| **Custom servers** | Add any IP (primary + optional secondary) before benchmarking |
| **Admin detection** | UI adapts — apply buttons disabled when backend lacks privileges |
| **OS-agnostic** | Windows (PowerShell), macOS (networksetup), Linux (resolvectl / resolv.conf) |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET  | `/api/config` | Returns built-in server list, domains, OS info, admin status |
| POST | `/api/benchmark/stream` | SSE stream of all probe results + final tier summary |
| POST | `/api/dns/apply` | Apply a DNS server system-wide (requires admin) |
| POST | `/api/dns/reset` | Revert to DHCP + flush cache (requires admin) |
| POST | `/api/dns/flush-cache` | Flush OS DNS cache only |
| GET  | `/api/health` | Health check |
| GET  | `/docs` | Swagger UI (auto-generated) |

### POST /api/benchmark/stream

```json
{
  "custom_servers": [
    { "name": "MyDNS", "ip": "1.2.3.4", "secondary_ip": "5.6.7.8" }
  ],
  "include_defaults": true,
  "target_domains": null
}
```

SSE events emitted:
```
data: {"type": "start", "total": 42, "servers": 6, "domains": 7}
data: {"type": "probe", "completed": 1, "total": 42, "server_name": "Cloudflare", "domain": "youtube.com", "status": "BYPASS", ...}
data: {"type": "complete", "elapsed_s": 8.3, "tiers": [...]}
```

### POST /api/dns/apply

```json
{ "server_name": "Shecan", "primary_ip": "178.22.122.100", "secondary_ip": "178.22.122.101" }
```

### Tier Summary Object

```json
{
  "name": "Cloudflare",
  "ip": "1.1.1.1",
  "secondary_ip": "1.0.0.1",
  "bypass_count": 7,
  "total_count": 7,
  "bypass_pct": 100,
  "avg_dns_ms": 42.1,
  "avg_http_ms": 310.5,
  "tier": "A",
  "per_domain": {
    "youtube.com": {
      "status": "BYPASS",
      "dns_ms": 38.2,
      "http_ms": 290.1,
      "http_code": 301,
      "resolved_ip": "142.250.185.46"
    }
  }
}
```

---

## Customization

Edit the top of `backend/api.py`:

```python
DEFAULT_DNS_SERVERS = [
    {"name": "MyDNS", "ip": "1.2.3.4", "secondary_ip": "5.6.7.8"},
    ...
]

DEFAULT_TARGET_DOMAINS = [
    "youtube.com",
    "instagram.com",
    ...
]

DNS_TIMEOUT  = 3.0   # seconds
HTTP_TIMEOUT = 5.0   # seconds
MAX_CONCURRENT = 20  # parallel probes
```

---

## Status Classification

| Status | Meaning |
|---|---|
| `BYPASS` | HTTP 200/301/302/307/308 — site is reachable through this DNS |
| `SANCTIONED` | HTTP 403/451 — DNS works but destination blocks your IP (US sanctions) |
| `BLOCKED` | Connection timeout / refused / TLS error — traffic is intercepted |
| `FILTERED` | Resolved to a known block-page IP or censorship keywords in body |
| `DNS_FAILED` | DNS resolution itself failed — NXDOMAIN, timeout, no answer |
| `PROBE_ERROR` | Unexpected error during the HTTP probe |

---

## Troubleshooting

**"Cannot connect to backend"**
→ Make sure `python start.py` is running in the `backend/` directory.

**Apply DNS buttons are greyed out**
→ Backend needs to run with admin/sudo privileges.
→ Windows: open terminal as Administrator before `python start.py`
→ Linux/macOS: `sudo python start.py`

**CORS error in browser**
→ Open `index.html` directly (file://) or serve it locally.
→ The backend already allows all origins.

**`dns` module not found**
→ `pip install dnspython`

**`fastapi` / `uvicorn` not found**
→ `pip install fastapi uvicorn`
