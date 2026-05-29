# 🚀 Server Setup Guide - LLM Visibility Audit Tool

This guide walks you through setting up the LLM Visibility Audit Tool on a server for automated weekly execution.

---

## 📋 Table of Contents

1. [Choose a Server](#1-choose-a-server)
2. [Initial Server Setup](#2-initial-server-setup)
3. [Install Dependencies](#3-install-dependencies)
4. [Upload and Configure the Script](#4-upload-and-configure-the-script)
5. [Test the Script](#5-test-the-script)
6. [Set Up Automated Weekly Runs](#6-set-up-automated-weekly-runs)
7. [Monitoring and Maintenance](#7-monitoring-and-maintenance)

---

## 1. Choose a Server

### Recommended VPS Providers (Budget-Friendly)

| Provider | Minimum Plan | Price | Notes |
|----------|-------------|-------|-------|
| **DigitalOcean** | Basic Droplet | $4/month | Easy setup, good docs |
| **Linode** | Nanode | $5/month | Great performance |
| **Vultr** | Cloud Compute | $5/month | Global locations |
| **Hetzner** | CX11 | €3.29/month | Best value (EU) |
| **AWS Lightsail** | Small | $3.50/month | AWS ecosystem |

### Minimum Requirements
- **RAM**: 1GB (2GB recommended)
- **CPU**: 1 vCPU
- **Storage**: 20GB SSD
- **OS**: Ubuntu 22.04 LTS (recommended)

---

## 2. Initial Server Setup

### Connect to Your Server
```bash
ssh root@your_server_ip
```

### Create a Non-Root User (Recommended)
```bash
# Create user
adduser visibility_audit

# Add to sudo group
usermod -aG sudo visibility_audit

# Switch to new user
su - visibility_audit
```

### Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### Install Required System Packages
```bash
sudo apt install -y python3 python3-pip python3-venv git curl wget
```

### Install Chromium Dependencies (for screenshots)
```bash
sudo apt install -y \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0
```

---

## 3. Install Dependencies

### Create Project Directory
```bash
mkdir -p ~/visibility_audit
cd ~/visibility_audit
```

### Set Up Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### Install Python Packages
```bash
pip install --upgrade pip
pip install openai anthropic google-generativeai requests python-dotenv playwright
```

### Install Playwright Browser
```bash
playwright install chromium
```

---

## 4. Upload and Configure the Script

### Option A: Upload via SCP (from your local machine)
```bash
# Run this on your LOCAL machine
scp /Users/up2721/Desktop/test-script/visibility_audit2.0.py visibility_audit@your_server_ip:~/visibility_audit/
scp /Users/up2721/Desktop/test-script/requirements.txt visibility_audit@your_server_ip:~/visibility_audit/
```

### Option B: Copy-Paste or Use Git
```bash
# On the server, create the file
nano ~/visibility_audit/visibility_audit2.0.py
# Paste the script content
```

### Create Environment File
```bash
nano ~/visibility_audit/.env
```

Add your configuration:
```bash
# LLM API Keys (add the ones you have)
OPENAI_API_KEY=sk-your-openai-key
ANTHROPIC_API_KEY=sk-ant-your-anthropic-key
GOOGLE_API_KEY=your-google-key
XAI_API_KEY=your-xai-key
PERPLEXITY_API_KEY=pplx-your-perplexity-key

# Email Configuration (for Gmail, use App Password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_16_char_app_password
EMAIL_TO=recipient@example.com

# Archive Settings
ARCHIVE_RETENTION_WEEKS=12
```

### Secure the .env File
```bash
chmod 600 ~/visibility_audit/.env
```

---

## 5. Test the Script

### Activate Virtual Environment
```bash
cd ~/visibility_audit
source venv/bin/activate
```

### Test Email Configuration
```bash
python visibility_audit2.0.py --test-email
```

### Run a Full Test
```bash
python visibility_audit2.0.py
```

### Check Output Files
```bash
ls -la
# Should see: visibility_dashboard.html, audit_results.json, archives/
```

---

## 6. Set Up Automated Weekly Runs

### Option A: Cron Job (Simple)

```bash
# Edit crontab
crontab -e
```

Add this line (runs every Sunday at 6 AM server time):
```bash
0 6 * * 0 cd /home/visibility_audit/visibility_audit && /home/visibility_audit/visibility_audit/venv/bin/python visibility_audit2.0.py >> /home/visibility_audit/visibility_audit/cron.log 2>&1
```

#### Common Cron Schedules:
```bash
# Every Sunday at 6:00 AM
0 6 * * 0

# Every Monday at 9:00 AM
0 9 * * 1

# Every Saturday at midnight
0 0 * * 6

# Every day at 8:00 AM (for testing)
0 8 * * *
```

### Option B: Systemd Timer (More Robust)

#### Create Service File
```bash
sudo nano /etc/systemd/system/visibility-audit.service
```

```ini
[Unit]
Description=LLM Visibility Audit
After=network.target

[Service]
Type=oneshot
User=visibility_audit
WorkingDirectory=/home/visibility_audit/visibility_audit
ExecStart=/home/visibility_audit/visibility_audit/venv/bin/python visibility_audit2.0.py
StandardOutput=append:/home/visibility_audit/visibility_audit/audit.log
StandardError=append:/home/visibility_audit/visibility_audit/audit.log

[Install]
WantedBy=multi-user.target
```

#### Create Timer File
```bash
sudo nano /etc/systemd/system/visibility-audit.timer
```

```ini
[Unit]
Description=Run LLM Visibility Audit Weekly

[Timer]
OnCalendar=Sun 06:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

#### Enable Timer
```bash
sudo systemctl daemon-reload
sudo systemctl enable visibility-audit.timer
sudo systemctl start visibility-audit.timer

# Check status
sudo systemctl status visibility-audit.timer
sudo systemctl list-timers
```

#### Manual Run (to test)
```bash
sudo systemctl start visibility-audit.service
```

---

## 7. Monitoring and Maintenance

### View Logs
```bash
# Cron logs
tail -f ~/visibility_audit/cron.log

# Application logs
tail -f ~/visibility_audit/visibility_audit.log

# Systemd logs (if using timer)
journalctl -u visibility-audit.service -f
```

### Check Archive Size
```bash
du -sh ~/visibility_audit/archives/
```

### View Recent Results
```bash
ls -lt ~/visibility_audit/archives/ | head -10
```

### Download Dashboard to View Locally
```bash
# From your LOCAL machine
scp visibility_audit@your_server_ip:~/visibility_audit/visibility_dashboard.html ./
```

### Or Set Up Simple Web Server to View Dashboard
```bash
# On server
cd ~/visibility_audit
python3 -m http.server 8080 &

# Then access: http://your_server_ip:8080/visibility_dashboard.html
```

---

## 🔧 Troubleshooting

### Script Fails to Run
```bash
# Check Python path
which python3

# Check virtual environment
source ~/visibility_audit/venv/bin/activate
python --version

# Check dependencies
pip list
```

### Email Not Sending
```bash
# Test email
python visibility_audit2.0.py --test-email

# Check SMTP settings
# For Gmail: Enable 2FA and create App Password
# https://support.google.com/accounts/answer/185833
```

### Screenshot Not Working
```bash
# Check Playwright installation
playwright install chromium

# Install missing dependencies
sudo apt install -y libnss3 libatk1.0-0 libatk-bridge2.0-0
```

### Cron Job Not Running
```bash
# Check cron logs
grep CRON /var/log/syslog

# Check crontab
crontab -l

# Test manually with same command
cd /home/visibility_audit/visibility_audit && /home/visibility_audit/visibility_audit/venv/bin/python visibility_audit2.0.py
```

### Permission Issues
```bash
# Fix ownership
sudo chown -R visibility_audit:visibility_audit ~/visibility_audit

# Fix permissions
chmod 755 ~/visibility_audit
chmod 644 ~/visibility_audit/*.py
chmod 600 ~/visibility_audit/.env
```

---

## 📊 Quick Reference

### File Locations
```
~/visibility_audit/
├── visibility_audit2.0.py     # Main script
├── requirements.txt           # Dependencies
├── .env                       # Configuration (keep secret!)
├── visibility_dashboard.html  # Latest dashboard
├── audit_results.json         # Latest results
├── visibility_audit.log       # Application log
├── cron.log                   # Cron execution log
├── venv/                      # Python virtual environment
└── archives/                  # Historical data
    ├── audit_results_YYYY-MM-DD.json
    ├── visibility_dashboard_YYYY-MM-DD.html
    └── visibility_dashboard_YYYY-MM-DD.png
```

### Useful Commands
```bash
# Activate environment
source ~/visibility_audit/venv/bin/activate

# Run audit manually
python visibility_audit2.0.py

# Run without email
python visibility_audit2.0.py --no-email

# Test email
python visibility_audit2.0.py --test-email

# View cron schedule
crontab -l

# Check timer status
sudo systemctl status visibility-audit.timer
```

---

## 🎉 You're All Set!

Your LLM Visibility Audit Tool will now run automatically every week and:
1. ✅ Query all configured LLMs
2. ✅ Generate HTML dashboard
3. ✅ Capture screenshot
4. ✅ Compare with previous week
5. ✅ Send email notification
6. ✅ Archive results
7. ✅ Clean up old archives

Questions? Check the logs in `visibility_audit.log` or `cron.log`.

  URL: http://161.118.180.179                 
  Username: uplers                                                                                                                                           
  Password: Uplers@123   