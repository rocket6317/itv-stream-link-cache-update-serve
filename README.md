# ITV Redirect Dashboard

Stream ITV channels on IPTV players that support **clearkey**.  
A lightweight FastAPI dashboard for managing and monitoring ITV stream redirects via JWT-based MPD links. Designed for IPTV setups using expiry-based caching — no background polling required.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M31NTEGN)

---

## 🚀 Features

-  🔗 Automatically gets, caches, refreshes and serves the up-to-date ITV stream URLs that can be used in IPTV players. 
-  📊 Dashboard: /dashboard endpoint shows info about URLs. ie. live stream history, expiry, request count
-  🔐 Password-protected dashboard via environment variables 
-  🧠 Expiry-aware caching: Uses exp= timestamp from JWT to determine validity
-  🕒 Request tracking: Counts how many times each cached link is used
-  🌙 Dark mode + 🔄 Auto-refresh every 60 seconds
-  📦 Easy to deploy with Docker or Portainer  

---

## USAGE ##
Replace `your-server-ip` with your actual server IP or domain name.

### Examples:
- ITV1: `https://your-server-ip:1995/itvx?channel=ITV`
- ITV2: `https://your-server-ip:1995/itvx?channel=ITV2`
- ITV3: `https://your-server-ip:1995/itvx?channel=ITV3`
- ITV4: `https://your-server-ip:1995/itvx?channel=ITV4`
- ITV Quiz: `https://your-server-ip:1995/itvx?channel=ITVBe`

Paste these links into any **clearkey capable IPTV player**. You need to insert clearkeys in the m3u file. This app will only give you the streaming links.

## 🔐 Authentication for Dashboard

Basic login is enforced using environment variables. After deploying the stack:

1. **Stop the container**
2. Go to the **Environment Variables (Env)** section
3. Set your chosen username and password.
   
DASHBOARD_USER=your_chosen_username  
DASHBOARD_PASS=your_chosen_password

5. **Restart the container**

> ⚠️ If you don’t set your own username and password, the container will use default values that is given above.

---

## 📸 Dashboard Preview

**Address:**

http://your-server-ip:1995/dashboard

---

## 📜 License

MIT — free to use, modify, and share.

---

## 🙋‍♂️ Contribute

Pull requests welcome!  
Ideas for auto-refresh, CSV export, or mobile layout? Let’s build it together.
