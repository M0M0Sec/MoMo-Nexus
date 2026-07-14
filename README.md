# 🌐 MoMo-Nexus

<p align="center">
  <img src="https://img.shields.io/badge/Role-Communication%20Hub-blue?style=for-the-badge" alt="Role">
  <img src="https://img.shields.io/badge/Channels-LoRa%20%7C%204G%20%7C%20WiFi%20%7C%20BLE-green?style=for-the-badge" alt="Channels">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/Version-1.0.0-blue?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Tests-384%20Passing-success?style=for-the-badge" alt="Tests">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/actions/workflow/status/M0M0Sec/MoMo-Nexus/ci.yml?style=for-the-badge&label=CI" alt="CI">
</p>

<h3 align="center">The Central Communication Hub for MoMo Ecosystem</h3>

<p align="center">
  <strong>Connect Everything. Route Intelligently. Never Lose Contact.</strong><br>
  Multi-Channel • Fleet Management • Smart Routing • Redundancy
</p>

<p align="center">
  <a href="https://github.com/Momo-Master/MoMo">MoMo</a> •
  <a href="https://github.com/Momo-Master/Momo-GhostBridge">GhostBridge</a> •
  <a href="https://github.com/Momo-Master/MoMo-Mimic">Mimic</a>
</p>

---

## 🎯 What is MoMo-Nexus?

MoMo-Nexus is the **central communication hub** that connects all MoMo ecosystem devices (MoMo, GhostBridge, Mimic, Swarm) into a unified, resilient network. It removes the communication burden from individual devices and provides intelligent routing across multiple channels.

### ❌ Before Nexus
> Each device manages its own communication. No redundancy, no coordination.

```
   MoMo          GhostBridge       Mimic          Swarm
     │               │               │               │
     │               │               │               │
     ▼               ▼               ▼               ▼
   ┌───┐           ┌───┐           ┌───┐           ┌───┐
   │ ? │           │ ? │           │ ? │           │ ? │
   └───┘           └───┘           └───┘           └───┘
   
   ⚠️ No failover  ⚠️ No sync  ⚠️ No fleet view
```

### ✅ With Nexus
> All devices connect through one hub. Smart routing, automatic failover.

```
   MoMo          GhostBridge       Mimic          Swarm
   (WiFi)         (Implant)        (USB)          (LoRa)
     │               │               │               │
     └───────────────┴───────┬───────┴───────────────┘
                             │
                             ▼
                   ╔═══════════════════╗
                   ║      NEXUS        ║
                   ║   Central Hub     ║
                   ╠═══════════════════╣
                   ║ 📡 LoRa  │ 10km+  ║
                   ║ 📶 4G    │ Global ║
                   ║ 🌐 WiFi  │ Local  ║
                   ║ 🔵 BLE   │ Close  ║
                   ╚════════╤══════════╝
                            │
                            ▼
                   ┌─────────────────┐
                   │    Operator     │
                   │    📱  💻       │
                   └─────────────────┘

   ✅ Auto-failover  ✅ Fleet sync  ✅ Smart routing
```

---

## ✨ Key Features

### 🔄 Multi-Channel Communication

| Channel | Range | Speed | Use Case |
|---------|-------|-------|----------|
| **LoRa** | 10-15 km | Slow | Off-grid, long range |
| **4G/LTE** | Unlimited | Fast | Primary internet |
| **WiFi** | 100m | Fast | Local network |
| **BLE** | 30m | Medium | Close range, low power |
| **Satellite** | Global | Slow | Last resort |

### 🧠 Intelligent Routing

```
Message In ──► Priority Check ──► Channel Selection ──► Send
                   │                     │
                   ▼                     ▼
              ┌─────────┐         ┌─────────────┐
              │ Critical│ ───────►│ 4G → WiFi   │
              │ High    │         │    → LoRa   │
              ├─────────┤         ├─────────────┤
              │ Normal  │ ───────►│ WiFi → LoRa │
              │ Low     │         │    → 4G     │
              ├─────────┤         ├─────────────┤
              │ Bulk    │ ───────►│ WiFi → 4G   │
              └─────────┘         └─────────────┘
                                        │
                              All fail? │
                                        ▼
                              ┌─────────────────┐
                              │ Queue & Retry   │
                              │ (with backoff)  │
                              └─────────────────┘
```

### 📊 Fleet Management

- Real-time device status
- Health monitoring
- Command dispatch
- Centralized logging
- Map visualization

### 🛡️ Redundancy & Resilience

- Automatic failover
- Store-and-forward
- Message acknowledgment
- Retry with backoff
- No single point of failure

### ☁️ Cloud Integration

| Service | Function | Status |
|---------|----------|--------|
| **Hashcat GPU** | Remote WPA/WPA2 cracking | ✅ API Ready |
| **Evilginx VPS** | AiTM phishing campaigns | ✅ API Ready |
| **WireGuard** | GhostBridge tunnel | ✅ Planned |

### 🔄 Sync API

Endpoints for field device data upload:
- `/api/sync/handshake` - Captured handshakes
- `/api/sync/credential` - Stolen credentials  
- `/api/sync/crack-result` - Cracking results
- `/api/sync/loot` - Generic exfiltrated data
- `/api/sync/status` - Device heartbeats
- `/api/sync/ghost/beacon` - GhostBridge check-ins
- `/api/sync/mimic/trigger` - Mimic payload events

---

## 🏗️ Architecture

### System Overview

```
╔═══════════════════════════════════════════════════════════════╗
║                      NEXUS ARCHITECTURE                        ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                 ║
║  ┌─────────────────── CHANNEL LAYER ──────────────────────┐   ║
║  │                                                         │   ║
║  │   LoRa      4G/LTE     WiFi       BLE       Satellite  │   ║
║  │    📡         📶        🌐         🔵          🛰️      │   ║
║  │     │          │         │          │           │       │   ║
║  └─────┴──────────┴─────────┴──────────┴───────────┴───────┘   ║
║                              │                                  ║
║                              ▼                                  ║
║  ┌─────────────────── ROUTING ENGINE ─────────────────────┐   ║
║  │                                                         │   ║
║  │   Channel Monitor    Message Queue    Priority Router  │   ║
║  │         │                 │                  │          │   ║
║  └─────────┴─────────────────┴──────────────────┴──────────┘   ║
║                              │                                  ║
║                              ▼                                  ║
║  ┌─────────────────── APPLICATION ────────────────────────┐   ║
║  │                                                         │   ║
║  │   Fleet Manager      Command Dispatch    Web Dashboard │   ║
║  │   Device Registry    Message Store       Alert System  │   ║
║  │   Notifications      Cloud Proxy         Sync API      │   ║
║  │                                                         │   ║
║  └─────────────────────────────────────────────────────────┘   ║
║                                                                 ║
╚═══════════════════════════════════════════════════════════════╝
```

### Message Flow

**Inbound:** Device → Operator
```
MoMo 📡 ───LoRa───► NEXUS ───4G/Push───► Operator 📱
                      │
                Parse → Route → Queue → ACK
```

**Outbound:** Operator → Device
```
Operator 📱 ───API───► NEXUS ───Best Channel───► Device 📡
                         │
                   Route → Encrypt → Send → Wait ACK
```

**Priority-Based Routing:**
| Priority | Preferred Channels | Use Case |
|----------|-------------------|----------|
| `critical` | 4G → WiFi → LoRa | Alerts, emergencies |
| `high` | 4G → WiFi → LoRa | Commands, captures |
| `normal` | WiFi → LoRa → 4G | Status updates |
| `low` | LoRa → WiFi | Heartbeats |
| `bulk` | WiFi → 4G | File transfers |

---

## 🛠️ Hardware Options

### Option A: Raspberry Pi Based (Recommended)

```
    ┌──────────────────────────────────────────┐
    │          Raspberry Pi 4/5                │
    │                                          │
    │   USB Ports:                             │
    │   ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐   │
    │   │LoRa  │ │ 4G   │ │ GPS  │ │ SSD  │   │
    │   │T-Beam│ │7600  │ │u-blox│ │256GB │   │
    │   └──────┘ └──────┘ └──────┘ └──────┘   │
    │                                          │
    │   Built-in: WiFi • BT 5.0 • Gigabit ETH │
    └──────────────────────────────────────────┘
```

| Pros | Cons |
|------|------|
| ✅ Full Linux OS | ❌ Higher power (~10W) |
| ✅ Web dashboard | ❌ Larger form factor |
| ✅ Easy development | ❌ Needs stable power |
| ✅ Database + SQLite | |
| ✅ All USB peripherals | |

**Cost:** ~$150-200

### Option B: ESP32 Based (Compact)

```
    ┌──────────────────────────────────────────┐
    │          Custom PCB                       │
    │                                          │
    │   ┌──────────┐    ┌──────────┐          │
    │   │ ESP32-S3 │    │  SX1262  │          │
    │   │ (MCU)    │    │  (LoRa)  │          │
    │   └──────────┘    └──────────┘          │
    │   ┌──────────┐    ┌──────────┐          │
    │   │ SIM7600  │    │ NEO-M8N  │          │
    │   │ (4G LTE) │    │ (GPS)    │          │
    │   └──────────┘    └──────────┘          │
    │   ┌────────────────────────┐            │
    │   │  18650 x2 + Solar      │            │
    │   └────────────────────────┘            │
    └──────────────────────────────────────────┘
```

| Pros | Cons |
|------|------|
| ✅ Ultra low power (~1W) | ❌ Limited processing |
| ✅ Compact size | ❌ No full OS |
| ✅ Battery powered | ❌ Simpler dashboard |
| ✅ Deployable anywhere | ❌ Complex development |

**Cost:** ~$80-120

### Bill of Materials (Pi-Based)

| Component | Model | Purpose | Cost |
|-----------|-------|---------|------|
| SBC | Raspberry Pi 4 (4GB) | Main processor | ~$55 |
| LoRa | Lilygo T-Beam | LoRa + GPS | ~$35 |
| 4G Modem | SIM7600E-H | LTE connectivity | ~$40 |
| SSD | 256GB NVMe | Storage | ~$30 |
| Case | Weatherproof | Protection | ~$20 |
| Antennas | LoRa + 4G | Range | ~$20 |
| **Total** | | | **~$200** |

---

## 🔗 Device Integration

### Supported Devices

| Device | Connection | Protocol | Status |
|--------|------------|----------|--------|
| **MoMo** | LoRa / WiFi | Nexus Protocol | ✅ Integrated |
| **GhostBridge** | 4G / WiFi / LoRa | Nexus Protocol | ✅ Integrated |
| **Mimic** | WiFi / BLE | Nexus Protocol | ✅ Integrated |
| **Swarm** | LoRa Mesh | Meshtastic | ✅ **Merged into Nexus** |

> **Note:** Swarm functionality is now built directly into Nexus via the `nexus.swarm` module. No separate Swarm device needed!

### Registration Flow

```
Device                           Nexus
   │                               │
   │ 1. HELLO (broadcast)          │
   │ ─────────────────────────────►│
   │                               │
   │ 2. CHALLENGE (nonce)          │
   │ ◄───────────────────────────  │
   │                               │
   │ 3. AUTH (signed credentials)  │
   │ ─────────────────────────────►│
   │                               │
   │ 4. REGISTERED (ack + config)  │
   │ ◄───────────────────────────  │
   │                               │
   │ 5. Normal operation begins    │
   │ ════════════════════════════► │
```

---

## 📡 Communication Protocol

### Message Format

```json
{
  "v": 1,
  "id": "msg-uuid-here",
  "src": "momo-001",
  "dst": "nexus",
  "ts": 1702900000,
  "ch": "lora",
  "pri": "normal",
  "type": "alert",
  "ack": true,
  "data": {
    "event": "handshake_captured",
    "ssid": "TARGET-WIFI",
    "bssid": "AA:BB:CC:DD:EE:FF"
  }
}
```

### Priority Levels

| Priority | Description | Channel Preference |
|----------|-------------|--------------------|
| `critical` | Immediate delivery | 4G → WiFi → LoRa |
| `high` | Fast delivery | 4G → WiFi → LoRa |
| `normal` | Standard delivery | Best available |
| `low` | When convenient | LoRa (save data) |
| `bulk` | Large data transfer | WiFi → 4G |

---

## ⚡ Getting Started

### Requirements

- Python **3.11+**
- Optional extras per feature: `lora` (Meshtastic), `ble` (Bleak), `api` (FastAPI + Uvicorn)

### Installation

```bash
git clone https://github.com/M0M0Sec/MoMo-Nexus.git
cd MoMo-Nexus

python -m venv .venv && source .venv/bin/activate

# Core only
pip install -e .

# With the REST/WebSocket API server
pip install -e ".[api]"

# Everything (LoRa + BLE + API)
pip install -e ".[full]"
```

> On hardware-less machines the LoRa/BLE/cellular drivers fall back to mock channels,
> so the hub, routing engine, and API run fully without any radios attached.

### CLI

The `nexus` command is installed with the package:

| Command | Description |
|---------|-------------|
| `nexus run` | Start the hub (add `--api` to serve the REST/WebSocket API) |
| `nexus status` | Show hub status |
| `nexus config --show` | Show current config (`--generate` writes a default) |
| `nexus devices` | List registered devices |
| `nexus messages` | List recent messages |
| `nexus test --channel mock` | Test channel connectivity |
| `nexus --version` | Print version |

```bash
# Generate a config, then start with the API enabled
nexus config --generate --output nexus.yml
nexus run --config nexus.yml --api
```

---

## 🌐 Web Dashboard

**Status:** ✅ Complete | **Tech Stack:** React 18 + TypeScript + Vite + Tailwind CSS

### Features

| Feature | Description | Status |
|---------|-------------|--------|
| **Dashboard** | Real-time fleet overview, stats, activity feed | ✅ |
| **Fleet** | Device grid/list view, status monitoring | ✅ |
| **Captures** | Handshake table, password reveal | ✅ |
| **Cracking** | Job queue, progress tracking | ✅ |
| **Phishing** | Evilginx sessions, phishlet management | ✅ |
| **Analytics** | Charts, statistics, reports | ✅ |
| **Settings** | Channels, cloud, security, theme | ✅ |
| **Device Map** | Leaflet + OpenStreetMap dark theme | ✅ |
| **Toast Notifications** | Real-time event alerts | ✅ |
| **Mobile Navigation** | Responsive bottom nav | ✅ |
| **Theme Toggle** | Dark / Light / System | ✅ |
| **Keyboard Shortcuts** | Ctrl+H, Ctrl+F, etc. | ✅ |
| **Export** | CSV/JSON data export | ✅ |

### Design

- **Cyberpunk aesthetic** - Neon colors, glassmorphism, matrix grid
- **Dark-first theme** - Optimized for night operations
- **Pi 4 optimized** - Code splitting, lazy loading, minimal bundle
- **Mobile responsive** - Tablet and phone support

### Quick Start

```bash
cd MoMo-Nexus/dashboard
npm install --legacy-peer-deps
npm run dev    # → http://localhost:5173/
npm run build  # → dist/ (production)
```

### Dashboard Preview

```
╔══════════════════════════════════════════════════════════════╗
║  🌐 NEXUS DASHBOARD                         admin ▼   ⚙️  🔔 ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                ║
║  │  3/4   │ │   47   │ │   12   │ │   2    │                ║
║  │ Online │ │Captures│ │Cracked │ │ Alerts │                ║
║  └────────┘ └────────┘ └────────┘ └────────┘                ║
║                                                              ║
║  ┌─────────────────────┐  ┌─────────────────────────┐       ║
║  │   🗺️ Device Map     │  │  📨 Activity Feed       │       ║
║  │                     │  │                         │       ║
║  │   📍 MoMo-001       │  │  🤝 Handshake: CORP     │       ║
║  │   📍 Ghost-001      │  │  🔓 Cracked: Home-WiFi  │       ║
║  │       [Dark Map]    │  │  📡 momo-001 online     │       ║
║  │                     │  │  ⚠️ mimic low battery   │       ║
║  └─────────────────────┘  └─────────────────────────┘       ║
║                                                              ║
║  [🔍 Scan]  [📡 Capture]  [🔑 Crack]  [📤 Export]           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**Theme:** Cyberpunk dark with neon accents (green/cyan/magenta)

---

## 🧪 Testing & Development

The backend ships with a full async test suite. Runs are gated in CI on every push and PR.

```bash
pip install -e ".[dev,api]"

make test        # pytest
make test-cov    # pytest with coverage
make lint        # ruff check
make format      # ruff format
```

- **384 passing**, **77 skipped** (hardware-dependent: real LoRa/BLE/cellular) — 461 tests total
- **Lint:** `ruff` clean (hard gate in CI)
- **Types:** `mypy --strict` (declared; migration in progress, non-blocking in CI)
- **CI:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the Python backend (pytest + ruff)
  and the dashboard TypeScript check on Ubuntu

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [README.md](README.md) | This file |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Technical architecture |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Hardware assembly |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Deployment guide |
| [docs/ECOSYSTEM.md](docs/ECOSYSTEM.md) | Ecosystem integration |
| [docs/REMEDIATION_PLAN.md](docs/REMEDIATION_PLAN.md) | Phased reliability & security hardening plan |

---

## 🚀 Roadmap

| Phase | Description | Status |
|-------|-------------|--------|
| 0.1.0 | Documentation & Design | ✅ Complete |
| 0.2.0 | Core Routing Engine | ✅ Complete |
| 0.3.0 | Channel Drivers (LoRa, 4G, WiFi, BLE) | ✅ Complete |
| 0.4.0 | Fleet Management | ✅ Complete |
| 0.5.0 | GPS & Geofencing | ✅ Complete |
| 0.6.0 | Security Layer (HMAC, Encryption) | ✅ Complete |
| 0.7.0 | Plugin System | ✅ Complete |
| 0.8.0 | Swarm Integration (LoRa Mesh) | ✅ Complete |
| 0.9.0 | Sync API (MoMo, GhostBridge, Mimic) | ✅ Complete |
| 1.0.0 | Cloud API (Hashcat, Evilginx) | ✅ Complete |
| 1.1.0 | Web Dashboard | ✅ Complete |
| 1.1.1 | Reliability & Security Hardening (channel/swarm fixes, API hardening, CI) | ✅ Complete |
| 1.2.0 | Mobile App | 📅 Planned |

---

## 🌐 MoMo Ecosystem

Nexus is the central hub that connects all MoMo ecosystem devices.

| Project | Description | Platform | Status |
|---------|-------------|----------|--------|
| **[MoMo](https://github.com/Momo-Master/MoMo)** | WiFi/BLE/SDR Audit Platform | Pi 5 | ✅ v1.5.2 |
| **[MoMo-Nexus](https://github.com/M0M0Sec/MoMo-Nexus)** | Central Communication Hub | Pi 4 | ✅ v1.0.0 |
| **[MoMo-GhostBridge](https://github.com/Momo-Master/Momo-GhostBridge)** | Network Implant | NanoPi R2S | ✅ v0.5.0 |
| **[MoMo-Mimic](https://github.com/Momo-Master/MoMo-Mimic)** | USB Attack Platform | Pi Zero 2W | ✅ v1.0.0 |

---

## ⚠️ Legal Notice

MoMo-Nexus is designed for authorized security testing and research only. Ensure compliance with local regulations regarding radio frequency usage (LoRa, 4G).

---

<p align="center">
  <strong>Part of the 🔥 MoMo Ecosystem</strong><br>
  <sub>The Hub That Connects Everything</sub>
</p>

<p align="center">
  <a href="https://github.com/Momo-Master/MoMo">MoMo</a> •
  <a href="https://github.com/M0M0Sec/MoMo-Nexus">Nexus</a> •
  <a href="https://github.com/Momo-Master/Momo-GhostBridge">GhostBridge</a> •
  <a href="https://github.com/Momo-Master/MoMo-Mimic">Mimic</a>
</p>

