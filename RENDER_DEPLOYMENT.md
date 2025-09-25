# 🚀 Render Deployment Guide for PumpShield Pro

## 📋 **REQUIRED ENVIRONMENT VARIABLES FOR RENDER**

### 🔑 **MANDATORY VARIABLES:**
```bash
# Telegram Bot Token (REQUIRED)
TELEGRAM_TOKEN=7293922941:AAEwsYykk-3bdN_ngeI1o1OON0CV0h_WLnM

# Python Environment
PYTHON_VERSION=3.12
```

### ⚙️ **OPTIONAL SECURITY VARIABLES:**
```bash
# Admin User ID (optional - restricts bot to one user)
ADMIN_USER_ID=123456789

# Trading Limits (optional - defaults shown)
MAX_SOL_PER_TRADE=1.0

# Rate Limiting (optional - defaults shown)
RATE_LIMIT_REQUESTS=10
RATE_LIMIT_WINDOW=60
```

---

## 🌐 **RENDER DEPLOYMENT STEPS**

### 1️⃣ **Create Web Service on Render**
1. Go to [render.com](https://render.com)
2. Click "New +" → "Web Service"
3. Connect your GitHub repository: `stusseligmini/ShieldPump`
4. Configure settings:

### 2️⃣ **Render Configuration**
```yaml
Name: pumpshield-pro-bot
Environment: Python 3
Region: Oregon (US West)
Branch: main
Build Command: pip install -r requirements.txt
Start Command: python main_user_friendly.py
```

### 3️⃣ **Environment Variables in Render**
Add these in Render Dashboard → Environment:

| Variable | Value | Required |
|----------|-------|----------|
| `TELEGRAM_TOKEN` | `7293922941:AAEwsYykk-3bdN_ngeI1o1OON0CV0h_WLnM` | ✅ YES |
| `PYTHON_VERSION` | `3.12` | ✅ YES |
| `ADMIN_USER_ID` | Your Telegram user ID | ❌ Optional |
| `MAX_SOL_PER_TRADE` | `1.0` | ❌ Optional |
| `RATE_LIMIT_REQUESTS` | `10` | ❌ Optional |
| `RATE_LIMIT_WINDOW` | `60` | ❌ Optional |

### 4️⃣ **Auto-Deploy Settings**
- ✅ Auto-Deploy: Yes
- ✅ Branch: main

---

## 📝 **RENDER BUILD CONFIGURATION FILES**

### Create `render.yaml` (optional but recommended):
```yaml
services:
- type: web
  name: pumpshield-pro-bot
  env: python
  plan: free
  buildCommand: pip install -r requirements.txt
  startCommand: python main_user_friendly.py
  envVars:
  - key: PYTHON_VERSION
    value: "3.12"
  - key: TELEGRAM_TOKEN
    sync: false  # Set this in dashboard for security
```

### Create `runtime.txt`:
```
python-3.12.0
```

---

## 🔧 **UPDATED REQUIREMENTS.TXT FOR RENDER**

Make sure your requirements.txt includes all dependencies:
```txt
python-telegram-bot==20.7
python-dotenv==1.1.1
solders==0.26.0
solana==0.36.7
requests==2.32.4
aiohttp==3.12.15
asyncio-throttle==1.0.2
retry==0.9.2
pydantic==2.11.9
cryptography==46.0.1
```

---

## 🚀 **DEPLOYMENT CHECKLIST**

### Before Deploying:
- [ ] Fork/clone the repository to your GitHub
- [ ] Get your Telegram Bot Token from @BotFather
- [ ] (Optional) Get your Telegram User ID from @userinfobot

### In Render Dashboard:
- [ ] Create new Web Service
- [ ] Connect GitHub repository
- [ ] Set build command: `pip install -r requirements.txt`
- [ ] Set start command: `python main_user_friendly.py`
- [ ] Add environment variables (especially TELEGRAM_TOKEN)
- [ ] Deploy!

### After Deployment:
- [ ] Check logs in Render dashboard
- [ ] Test bot by sending /start in Telegram
- [ ] Verify all commands work
- [ ] Enable auto-deploy for future updates

---

## 🔍 **TROUBLESHOOTING**

### If bot doesn't start:
1. Check Render logs for errors
2. Verify TELEGRAM_TOKEN is correct
3. Ensure all dependencies are in requirements.txt
4. Check Python version compatibility

### If commands don't work:
1. Verify bot is running (check logs)
2. Test /start command first
3. Check rate limiting settings
4. Verify admin access if ADMIN_USER_ID is set

### Common Issues:
- **Build fails**: Missing dependencies in requirements.txt
- **Bot silent**: Wrong TELEGRAM_TOKEN
- **Access denied**: ADMIN_USER_ID set but you're not admin
- **Timeout errors**: Network/RPC issues (temporary)

---

## 💡 **PRO TIPS FOR RENDER**

### 1. **Free Tier Limitations:**
- Render free tier sleeps after 15 minutes of inactivity
- Consider upgrading for 24/7 bot operation

### 2. **Keep Bot Active:**
Create a simple health check endpoint or use Render's paid plan

### 3. **Environment Security:**
- Never commit TELEGRAM_TOKEN to git
- Use Render's environment variables feature
- Keep admin user ID private

### 4. **Monitoring:**
- Check Render logs regularly
- Set up alerts for deployment failures
- Monitor bot responsiveness

---

## 🎯 **FINAL DEPLOYMENT COMMAND**

If you want to deploy via CLI (alternative):
```bash
# Install Render CLI
npm install -g @render/cli

# Login and deploy
render login
render deploy
```

**🚀 Your PumpShield Pro bot will be live on Render in minutes!**