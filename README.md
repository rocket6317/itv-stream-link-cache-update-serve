# ITV Redirect Dashboard

Stream ITV channels on IPTV players that support **clearkey**.  
Also features a lightweight, real-time dashboard for monitoring stream URL changes across ITV channels. Built with Python, Gunicorn, and a simple HTML frontend, this app tracks updates, highlights differences, and displays historical changes with timestamps.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M31NTEGN)

---

## 🚀 Features

- 🔍 Detects and logs stream URL changes per channel  
- 🕒 Displays timestamp and time elapsed since last update  
- 📊 Shows total number of unique links per channel  
- 🧠 Highlights character-level differences in updated URLs  
- 🔐 Password-protected dashboard via environment variables  
- 📦 Easy to deploy with Docker or Portainer  

---

## 🔐 Authentication for Dashboard

Basic login is enforced using environment variables. After deploying the stack:

1. **Stop the container**
2. Go to the **Environment Variables (Env)** section
3. Add the following entries:

DASHBOARD_USER=your_chosen_username  
DASHBOARD_PASS=your_chosen_password

4. **Restart the container**

> ⚠️ If you don’t set a username and password, the container will crash and stop.

---

## 📸 Dashboard Preview

**Address:**

http://your-server-ip:1995/dashboard

Replace `your-server-ip` with your actual server IP or domain name.

### Examples:
- ITV1: `https://your-server-ip:1995/itvx?channel=ITV`
- ITV2: `https://your-server-ip:1995/itvx?channel=ITV2`
- ITV3: `https://your-server-ip:1995/itvx?channel=ITV3`

Paste these links into any IPTV-compatible app like **VLC**, **TiviMate**, **IPTV Smarters**, or **Kodi**.

---

## 📜 License

MIT — free to use, modify, and share.

---

## 🙋‍♂️ Contribute

Pull requests welcome!  
Ideas for auto-refresh, CSV export, or mobile layout? Let’s build it together.
