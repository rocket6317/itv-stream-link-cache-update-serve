# ITV Stream Link Cache

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M31NTEGN)

A FastAPI service that caches ITV live stream URLs with automated token refresh. Works on ARM devices (DietPi/Raspberry Pi).

## Features

- Cached stream URLs for configured ITV channels
- On-demand cache population for additional ITV channel IDs requested by players
- Automated token refresh via cron + VNC
- Web dashboard for monitoring
- Auto-restart on container failure
- Compatible with Portainer

## Quick Start

### 1. Clone and Configure

```bash
git clone https://github.com/rocket6317/itv-stream-link-cache-update-serve.git
cd itv-stream-link-cache-update-serve
```

Create `stack.env`:
```bash
cat > stack.env << EOF
DASHBOARD_USER=admin
DASHBOARD_PASS=your_password
ITV_ACCESS_TOKEN=your_jwt_token_here
EOF
```

### 2. Get Your Token

1. Open https://www.itv.com/watch in Chrome
2. Open DevTools (F12) → Network tab
3. Find request to `simulcast.itv.com`
4. Copy the token from Payload → user → token (starts with `eyJ`)

### 3. Deploy

```bash
docker-compose up -d
```

Access the dashboard at `http://your-host:1995/dashboard`

## Stream URLs

```
http://your-host:1995/itvx?channel=ITV
http://your-host:1995/itvx?channel=ITV2
http://your-host:1995/itvx?channel=ITV3
http://your-host:1995/itvx?channel=ITV4
http://your-host:1995/itvx?channel=ITVBe
```

Additional ITV channel IDs can be requested with the same endpoint. If the
channel is not already cached, the service will fetch it from ITVX, cache it,
and redirect the player when the upstream request succeeds:

```
http://your-host:1995/itvx?channel=FAST3
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHBOARD_USER` | Yes | Dashboard username |
| `DASHBOARD_PASS` | Yes | Dashboard password |
| `ITV_ACCESS_TOKEN` | Yes | JWT from ITVX |
| `REFRESH_INTERVAL` | No | Cache refresh interval (default: 21300) |

## Automated Token Refresh (Optional)

For automated token refresh on ARM systems:

1. Install VNC and Chrome:
```bash
sudo apt-get install -y xfce4 tightvncserver chromium
pip3 install websocket-client requests
```

2. Start VNC and login to ITVX in Chrome:
```bash
vncserver :1
# Connect via VNC, open Chrome, login to ITVX
```

3. Set up cron for daily token refresh:
```bash
crontab -e
# Add: 0 2 * * * python3 /path/to/extract_token_via_vnc.py
```

## Dashboard Pages

- `/dashboard` - Stream cache status with URL expiration
- `/stats` - URL refresh statistics
- `/token-logs` - Token extraction logs
- `/health` - Health check endpoint

## Portainer Users

If using Portainer, deploy the stack from this Git repository and provide
`stack.env` alongside `docker-compose.yml` in the stack directory. Keep
`stack.env` private and do not commit it to GitHub.

## Requirements

- Docker & Docker Compose
- Linux host (tested on DietPi/Raspberry Pi OS)
- ~1GB RAM
- ITVX account

## License

MIT License
