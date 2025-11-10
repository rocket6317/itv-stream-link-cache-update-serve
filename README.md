# 📺 ITV Redirect Dashboard

Use this tool to generate valid, auto-refreshing stream links for ITV channels. It handles token expiry automatically (gets/caches/refreshes/serves the links) and provides a simple dashboard to monitor stream activity.

---

## ✅ What It Does

- Generates valid ITV stream links to be used with **clearkey capable IPTV players**
- Automatically refreshes links when they expire
- Tracks how many times each link is used
- Shows expiry time and stream history in a web dashboard

---

## 🔗 How to Use

### 1. Get a valid stream link

After getting Flask (Gunicorn) up and running use below links in your m3u file to generate stream links
Replace `your-server-ip` with your actual server IP or domain name.

- http://your-server-ip:1995/itvx?channel=ITV
- http://your-server-ip:1995/itvx?channel=ITV2
- http://your-server-ip:1995/itvx?channel=ITV3
- http://your-server-ip:1995/itvx?channel=ITV4
- http://your-server-ip:1995/itvx?channel=ITVBe

These links redirect to the latest valid MPD stream for each channel.

---

### 2. Use in IPTV players

You must use a **Clearkey-capable IPTV player**, such as:

- **OTT Navigator**
- **TiviMate (with Clearkey support)**

These players must support **DASH + Clearkey DRM**.

You’ll need to insert the decryption keys manually into your `.m3u` playlist file. Example:


---

### 3. Monitor with the dashboard

Visit:

http://your-server-ip:1995/dashboard

This shows:

- Current stream link
- Expiry time (human-readable)
- Request count
- Link history and changes

---

## 🔐 Set Username & Password

Basic login is enforced using environment variables. After deploying the stack:

1. **Stop the container**
2. Go to the **Environment Variables (Env)** section
3. Set your chosen username and password.
   
DASHBOARD_USER=your_chosen_username  
DASHBOARD_PASS=your_chosen_password

5. **Restart the container**

> ⚠️ If you don’t set your own username and password, the container will use default values that is given above.

---

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/M4M31NTEGN)

---

## 📜 License

MIT — free to use, modify, and share.

---

