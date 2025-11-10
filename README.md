# ITV Redirect Dashboard

A lightweight, real-time dashboard for monitoring stream URL changes across ITV channels. Built with Python, Gunicorn, and a simple HTML frontend, this app tracks updates, highlights differences, and displays historical changes with timestamps.

---

## 🚀 Features

- 🔍 Detects and logs stream URL changes per channel
- 🕒 Displays timestamp and time elapsed since last update
- 📊 Shows total number of unique links per channel
- 🧠 Highlights character-level differences in updated URLs
- 🔐 Password protected dashboard via environment variables
- 📦 Easy to deploy with Docker or Portainer

---

🔐 Authentication for Dashboard

Basic login is enforced using environment variables:

•  DASHBOARD_USER: Username
•  DASHBOARD_PASS: Password

Don't forget to add these Environment variables and set your own username and password.

Example: 
DASHBOARD_USER=admin
DASHBOARD_PASS=itv123

## 📸 Dashboard Preview

Address: http://your-server-ip:1995/dashboard

Each channel is displayed in its own table.


### 📺 Using with IPTV Players

To stream ITV channels directly in your IPTV player, use the following format:

https://your-server-ip:1995/itvx?channel=ITV

Replace `your-server-ip` with your actual server IP or domain name.

Examples:
- ITV1: `https://your-server-ip:1995/itvx?channel=ITV`
- ITV2: `https://your-server-ip:1995/itvx?channel=ITV2`
- ITV3: `https://your-server-ip:1995/itvx?channel=ITV3`

Paste these links into any IPTV-compatible app like VLC, TiviMate, IPTV Smarters, or Kodi.


📜 License

MIT — free to use, modify, and share.

🙋‍♂️ Contribute

Pull requests welcome! Ideas for auto-refresh, CSV export, or mobile layout? Let’s build it together.
