<div align="center">

# 🌐 DNS Benchmarker — Web Edition

**A local full-stack web app that audits DNS resolvers for bypass capability across sanctioned domains.**

Live-streaming results, tier-ranked server cards, and one-click system DNS application.

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react)](https://react.dev)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## ✨ What It Does

DNS Benchmarker probes a set of DNS resolvers against a list of target domains — measuring DNS resolution speed, then performing a full TLS/HTTPS probe to determine whether each domain is actually reachable through that resolver.

Results are classified and grouped into **Tier A / B / F** cards. With one click, the best server is applied as your system DNS directly from the browser.

Built for users in regions with filtered or sanctioned internet access (e.g. Iran).

---

## 🏗️ Architecture

```
dns-benchmarker-web/
├── api.py            ← FastAPI backend — benchmark engine + OS DNS management
├── start.py          ← Launcher with dependency checker
├── requirements.txt  ← Python dependencies
├── index.html        ← Single-file React dashboard (no build step)
└── README.md
```

**Stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.9+, FastAPI, asyncio, dnspython |
| Transport | Server-Sent Events (SSE) — live probe streaming |
| DNS Probing | `dns.asyncresolver` — bypasses system resolver, queries servers directly |
| HTTP Probing | Raw asyncio sockets + TLS/SNI (no httpx dependency) |
| OS Integration | PowerShell (Windows) · networksetup (macOS) · resolvectl / resolv.conf (Linux) |
| Frontend | React 18, vanilla CSS, JetBrains Mono + Inter — single HTML file via CDN |

**Data flow:**
```
Browser ──POST /api/benchmark/stream──▶ FastAPI
        ◀── SSE: one event per probe ──  asyncio × semaphore (20 concurrent)
        ──POST /api/dns/apply        ──▶ subprocess (OS DNS setter)
        ──POST /api/dns/reset        ──▶ subprocess (DHCP revert + cache flush)
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or newer
- A modern browser (Chrome, Firefox, Edge)

### Step 1 — Install dependencies

```bash
pip install -r requirements.txt
```

Or individually:

```bash
pip install fastapi uvicorn dnspython
```

> On Windows with multiple Python installations, use the full path:
> ```
> C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe -m pip install fastapi uvicorn dnspython
> ```

### Step 2 — Start the backend

```bash
python start.py
```

You should see:
```
  ┌─────────────────────────────────────────┐
  │   DNS-Benchmarker Web — Backend v1.0    │
  └─────────────────────────────────────────┘

  API:      http://localhost:8765
  Docs:     http://localhost:8765/docs
```

> **To enable DNS apply + reset**, run the backend with administrator privileges:
>
> **Windows** — right-click your terminal → *Run as Administrator*, then `python start.py`
>
> **macOS / Linux** — `sudo python3 start.py`

### Step 3 — Open the frontend

Open `index.html` directly in your browser.  
No dev server. No npm. No bundler.

---

## ✅ Features

| Feature | Description |
|---|---|
| **Live SSE stream** | Probe results appear in real-time as each (server × domain) completes |
| **Tier A / B / F cards** | Servers grouped by bypass performance with expandable per-domain breakdown |
| **One-click DNS apply** | Sets primary + secondary IPs system-wide via OS subprocess |
| **DHCP reset** | Reverts all manual DNS entries and flushes OS cache |
| **Cache flush** | Standalone cache flush without changing DNS settings |
| **Custom servers** | Add any IP (primary + optional secondary) before benchmarking |
| **Admin detection** | UI adapts in real-time — apply buttons and lock icons update every 10s |
| **Smart interface detection** | Prioritizes Wi-Fi/Ethernet, skips virtual adapters (WSL, Hyper-V, VPN, TAP) |
| **OS-agnostic** | Windows · macOS · Linux — all handled automatically |

---

## 🔍 Status Classification

| Status | Icon | Meaning |
|---|---|---|
| `BYPASS` | ✓ Green | HTTP 2xx/3xx — domain is fully reachable through this DNS |
| `SANCTIONED` | ⊘ Amber | HTTP 403/451 — DNS resolves but destination blocks the IP |
| `BLOCKED` | ✕ Red | Connection timeout / TLS error — traffic is intercepted |
| `FILTERED` | 🔒 Purple | Resolved to a known block-page IP |
| `DNS_FAILED` | – Gray | DNS resolution failed (NXDOMAIN, timeout, no answer) |
| `PROBE_ERROR` | ⚠ Yellow | Unexpected error during HTTP probe phase |

### Tier Classification

| Tier | Rule |
|---|---|
| **A — Full Bypass** | 100% of domains return `BYPASS` through this server |
| **B — Partial Bypass** | At least one domain bypasses, but not all |
| **F — No Bypass** | Zero domains reachable — all blocked, filtered, or DNS failed |

---

## ⚙️ Customization

Edit the constants at the top of `api.py`:

```python
# ── DNS servers to benchmark ──────────────────────────────────────────────────
DEFAULT_DNS_SERVERS = [
    {"name": "Shecan",     "ip": "178.22.122.100", "secondary_ip": "178.22.122.101"},
    {"name": "Electro",    "ip": "78.157.42.100",  "secondary_ip": "78.157.42.104"},
    {"name": "Cloudflare", "ip": "1.1.1.1",        "secondary_ip": "1.0.0.1"},
    {"name": "Google",     "ip": "8.8.8.8",        "secondary_ip": "8.8.4.4"},
    # Add your own:
    {"name": "MyDNS",      "ip": "1.2.3.4",        "secondary_ip": "5.6.7.8"},
]

# ── Domains to probe ──────────────────────────────────────────────────────────
DEFAULT_TARGET_DOMAINS = [
    "youtube.com",
    "hub.docker.com",
    "registry.npmjs.org",
    "pypi.org",
    "github.com",
    "api.openai.com",
]

# ── Performance tuning ────────────────────────────────────────────────────────
DNS_TIMEOUT    = 3.0   # seconds per DNS query
HTTP_TIMEOUT   = 5.0   # seconds per HTTPS probe
MAX_CONCURRENT = 20    # max parallel probes
```

Custom servers can also be added at runtime through the UI without editing any code.

---

## 🔌 API Reference

Interactive Swagger docs: `http://localhost:8765/docs`

| Method | Endpoint | Admin | Description |
|---|---|---|---|
| `GET` | `/api/config` | — | Built-in servers, domains, OS type, admin status |
| `POST` | `/api/benchmark/stream` | — | SSE stream — one event per probe + final tier summary |
| `POST` | `/api/dns/apply` | ✓ | Apply a DNS server system-wide |
| `POST` | `/api/dns/reset` | ✓ | Revert to DHCP + flush OS DNS cache |
| `POST` | `/api/dns/flush-cache` | — | Flush OS DNS cache only |
| `GET` | `/api/health` | — | Health check (includes admin status) |

---

## 🛠️ Troubleshooting

**`No module named 'dns'` or `No module named 'fastapi'`**
```bash
pip install fastapi uvicorn dnspython
```

**"Cannot connect to backend" in the browser**
- Make sure `python start.py` is still running
- Check that nothing else is using port 8765
- Open browser DevTools (F12 → Console) to see the exact error

**Apply / Reset DNS buttons are greyed out or locked**
- **Windows:** Close terminal → right-click → *Run as Administrator* → `python start.py`
- **macOS / Linux:** `sudo python3 start.py`

**DNS apply succeeds but Windows Settings still shows "Automatic (DHCP)"**
Run this in PowerShell to check active adapter names:
```powershell
Get-NetAdapter | Select-Object Name, InterfaceDescription, Status | Format-Table
```

**CORS error in browser console**
Open `index.html` directly via `file://` (double-click the file). The backend already allows all origins.

**Port 8765 already in use**
Edit the port in `start.py` and update the `API` constant at the top of `index.html` to match.

---

## 🔒 Privacy & Security

- **Runs entirely locally.** No data leaves your machine — all DNS and HTTP probes originate from your own device.
- **No telemetry.** The app does not phone home or collect any usage data.
- **Minimal admin scope.** Elevated privileges are used only for the OS DNS setter and cache flush commands. Benchmarking itself requires no admin.

---

## 📄 License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---

<div align="center">
Built with Python · FastAPI · React · asyncio
</div>
