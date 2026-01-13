# ITV Stream Link Cache - Update & Serve

A FastAPI service that caches ITV live stream URLs and handles automated token refresh for 24-hour JWT expiration.

## Features

- ✅ Cached stream URLs (6-hour TTL) for 5 ITV channels
- ✅ Automated daily token refresh (via cron + VNC + Chrome)
- ✅ Smart retry logic (5 attempts with exponential backoff)
- ✅ Comprehensive logging with dedicated dashboard page
- ✅ Simple 302 redirects to live streams
- ✅ Web dashboard for monitoring
- ✅ Auto-restart on container failure (`unless-stopped`)
- ✅ Works on ARM (DietPi/Raspberry Pi)
- ✅ Compatible with Portainer stacks

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Linux host (tested on DietPi/Raspberry Pi OS)
- ~1GB RAM available
- ITVX account credentials

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/rocket6317/itv-stream-link-cache-update-serve.git
cd itv-stream-link-cache-update-serve
```

2. **Create configuration file**
```bash
# Create stack.env in the project directory (NOT in Git)
cat > stack.env << EOF
DASHBOARD_USER=your_username
DASHBOARD_PASS=your_password
ITV_ACCESS_TOKEN=your_jwt_token_here
ITV_COOKIE_CONSENT={}
ITV_COOKIE_CLIENT_ID=your_client_id_here
REFRESH_INTERVAL=21300
EOF
```

3. **Get your credentials**
   - **Dashboard username/password**: Your choice for web access
   - **ITV Token**: Extract from browser DevTools (see Token Extraction below)
   - **Client ID**: From `Itv.Cid` cookie on itv.com

4. **Deploy with Docker**
```bash
docker-compose up -d
```

### Token Extraction (First Time)

1. Open https://www.itv.com/watch in Chrome
2. Open DevTools (F12) → Network tab
3. Refresh the page
4. Find request to `simulcast.itv.com`
5. Click it → Payload tab → user → token
6. Copy the JWT (starts with `eyJ`)

Update your `stack.env`:
```bash
# Edit stack.env and paste your token
ITV_ACCESS_TOKEN=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIs...
```

Restart the container:
```bash
docker-compose restart
```

## Usage

### Stream URLs

```
http://your-host:1995/itvx?channel=ITV
http://your-host:1995/itvx?channel=ITV2
http://your-host:1995/itvx?channel=ITV3
http://your-host:1995/itvx?channel=ITV4
http://your-host:1995/itvx?channel=ITVBe
```

### Dashboard

```
http://your-host:1995/dashboard
```

### Token Refresh Logs

View detailed logs from automated token extraction:

```
http://your-host:1995/token-logs
```

Features color-coded events (green=success, red=error, orange=warning, blue=info).

### Health Check

```
http://your-host:1995/health
```

## Automated Token Refresh

This project includes automated token refresh for ARM systems:

### Setup (One-Time)

1. **Install dependencies on host:**
```bash
sudo apt-get update
sudo apt-get install -y xfce4 xfce4-goodies tightvncserver chromium chromium
sudo apt-get install -y xfonts-base xfonts-100dpi xfonts-75dpi
pip3 install websocket-client requests
```

2. **Start VNC:**
```bash
vncserver :1 -geometry 1920x1080 -depth 24
# Set a password when prompted
```

3. **Connect via VNC from your computer:**
```
vnc://your-host-ip:5901
```

4. **In VNC, open Chrome and log in to ITVX**
   - The login session will persist for future automated extractions

5. **Copy the extraction script to your host:**
```bash
# Copy extract_token_via_vnc.py from this repo to your host
# Example: /home/user/itv/extract_token_via_vnc.py
```

6. **Update stack.env location in extract_token_via_vnc.py:**
```python
# Change this line to match your setup:
ENV_FILE = '/path/to/your/stack.env'  # Update this path
```

7. **Set up cron job:**
```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 2 AM):
0 2 * * * python3 /home/dietpi/itv/extract_token_via_vnc.py
```

### How It Works

The automation:
1. Starts Chrome in VNC background (with 60s timeout)
2. Waits for ITV page to load (with 60s timeout)
3. Uses Chrome DevTools Protocol to extract JWT from cookies
4. **Retries up to 5 times** if token not found (delays: 3, 5, 8, 12, 15 seconds)
5. Updates `stack.env` with new token
6. Restarts the Docker container automatically
7. Closes Chrome
8. Logs all events to `/home/dietpi/itv/token_refresh.log`

### Log File

All token extraction events are logged to `token_refresh.log`:
- Chrome startup timing
- Page load timing
- Retry attempts
- Success/failure status
- Token expiration info

View logs in the dashboard at `/token-logs` or via CLI:
```bash
cat /home/dietpi/itv/token_refresh.log | jq
```

## Portainer Users

If using Portainer Git stacks, be aware of the following:

### Volume Mount Issue

Portainer creates numbered stack directories (`/data/compose/35/`, `/data/compose/72/`, etc.) on each deploy. Relative paths may not work correctly.

### Solution: Use Absolute Bind Mount

Edit your `docker-compose.yml`:
```yaml
version: '3.8'

services:
  itv:
    build: .
    ports:
      - "1995:8000"
    volumes:
      # Use absolute path to your stack.env
      - /absolute/path/to/stack.env:/app/stack.env:ro
```

### Alternative: Symlinks (Advanced)

If you prefer symlinks, you'll need to create one for each new stack number:
```bash
# After each deploy, find your stack number:
ls -la /data/compose/

# Create symlink:
ln -s /your/actual/stack.env /data/compose/STACK_NUMBER/stack.env
```

**Note:** This must be repeated after each deploy. The bind mount method above is recommended.

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHBOARD_USER` | Yes | Username for dashboard access |
| `DASHBOARD_PASS` | Yes | Password for dashboard access |
| `ITV_ACCESS_TOKEN` | Yes | JWT token from ITVX |
| `ITV_COOKIE_CONSENT` | No | Cookie consent (default: `{}`) |
| `ITV_COOKIE_CLIENT_ID` | No | Client ID from `Itv.Cid` cookie |
| `REFRESH_INTERVAL` | No | Cache refresh interval in seconds (default: 21300) |

### Ports

- **1995**: Main application port

## Troubleshooting

### 401 Errors

Token has expired. Extract a new token and update `stack.env`.

### Container Won't Start

Check that `stack.env` exists and has correct format:
```bash
cat stack.env
docker-compose logs
```

### Token Extraction Fails

- Make sure VNC is running: `ps aux | grep Xvnc`
- Check Chrome can start: `export DISPLAY=:1 && chromium --version`
- Verify you're logged into ITVX in Chrome
- Check the extraction script logs

### Portainer Volume Errors

```
error mounting "/data/compose/35/stack.env" to rootfs
```

**Solution:** Use absolute bind mount path in docker-compose.yml (see Portainer section above).

### Restart Policy

The container is configured with `restart: unless-stopped`:
- Automatically restarts if it crashes
- Starts on system boot
- Does NOT restart if manually stopped with `docker stop`

## Project Structure

```
├── docker-compose.yml           # Docker configuration
├── main.py                      # FastAPI application
├── client.py                    # ITV API client
├── cache.py                     # URL caching logic
├── dashboard.py                 # Dashboard UI
├── change_log.py                # Event tracking system
├── refresh_token.py             # Token refresh (legacy, deprecated)
├── extract_token_via_vnc.py     # Token refresh (ARM automation, primary)
├── templates/                   # HTML templates
│   ├── dashboard.html           # Main dashboard
│   ├── logs.html                # Change logs view
│   ├── stats.html               # Statistics view
│   └── token_logs.html          # Token refresh logs view (NEW)
└── .gitignore                   # Excludes stack.env and token_refresh.log
```

## Security Notes

- ⚠️ **Never commit `stack.env`** to Git (it's in `.gitignore`)
- ⚠️ **Dashboard is not HTTPS** - Use reverse proxy for internet exposure
- ⚠️ **VNC should be firewalled** - Don't expose port 5901 to internet
- ⚠️ **Tokens expire naturally** - 24-hour limit reduces risk

## Supported Channels

- ITV
- ITV2
- ITV3
- ITV4
- ITVBe

## License

MIT License - feel free to use and modify.



Original project for ITV stream caching and automation.
