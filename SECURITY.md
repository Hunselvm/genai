# Security Guide for VEO API App

## 🔒 Is It Safe to Run Publicly?

**Short Answer:** It depends on your use case and how you configure it.

## ✅ Current Security Features

1. **API Key Isolation**
   - Each user enters their own API key
   - Keys stored in session state only (browser memory)
   - No server-side storage
   - Each user pays for their own usage

2. **No Sensitive Data Storage**
   - No database
   - No user accounts
   - Temp files auto-deleted
   - No logs of API keys

3. **Input Validation**
   - File type validation (images only)
   - File size limits
   - Pillow validates image integrity

## ⚠️ Security Risks by Deployment Type

### Public Internet (NOT RECOMMENDED)

**Risks:**
- ❌ No authentication - anyone can access
- ❌ No rate limiting - abuse possible
- ❌ Resource consumption - could overload server
- ❌ API key leakage - if someone uses on unsecured network
- ❌ No user tracking - can't identify abusers

**Only do this if:**
- You add password protection (see below)
- You monitor usage closely
- You're prepared to shut it down if abused

### Streamlit Cloud with Password (RECOMMENDED FOR TEAMS)

**Why It's Safer:**
- ✅ Automatic HTTPS encryption
- ✅ DDoS protection included
- ✅ Isolated environments
- ✅ Auto-scaling resources
- ✅ Can add password protection

**Good For:**
- Small teams (5-50 people)
- Clients who need access
- Beta testing with known users

### Home Server (MEDIUM RISK)

**Risks:**
- ⚠️ Your IP exposed
- ⚠️ Your network targeted
- ⚠️ You manage all security
- ⚠️ No automatic HTTPS

**Safe If:**
- Behind VPN only
- Using HTTPS (nginx + Let's Encrypt)
- Firewall configured properly
- Monitoring enabled

### Local Only (SAFEST)

**Perfect For:**
- Just you
- Trusted coworkers on same network
- Development/testing

## 🛡️ Security Improvements

### Level 1: Basic Password Protection (5 minutes)

**Use the secure version:**

```bash
# Rename the secure version
mv streamlit_app.py streamlit_app_open.py
mv streamlit_app_secure.py streamlit_app.py

# Create secrets file
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Edit secrets.toml and set a strong password
nano .streamlit/secrets.toml
```

**For Streamlit Cloud:**
1. Deploy normally
2. Go to App Settings → Secrets
3. Add: `app_password = "your_strong_password"`
4. Restart app

**Security Level:** 🔒 Basic
- Stops casual access
- One shared password
- Good for small teams

### Level 2: Add Rate Limiting (15 minutes)

Add to `streamlit_app.py`:

```python
import time
from collections import defaultdict

# Rate limiting storage
if 'rate_limit' not in st.session_state:
    st.session_state.rate_limit = defaultdict(list)

def check_rate_limit(action, max_requests=10, window_seconds=60):
    """Check if user exceeded rate limit."""
    user_id = st.session_state.get('user_id', 'anonymous')
    now = time.time()

    # Clean old requests
    st.session_state.rate_limit[user_id] = [
        req_time for req_time in st.session_state.rate_limit[user_id]
        if now - req_time < window_seconds
    ]

    # Check limit
    if len(st.session_state.rate_limit[user_id]) >= max_requests:
        return False

    # Add current request
    st.session_state.rate_limit[user_id].append(now)
    return True

# Use before video generation:
if not check_rate_limit('generate_video', max_requests=5, window_seconds=300):
    st.error("⚠️ Rate limit exceeded. Please wait 5 minutes.")
    st.stop()
```

**Security Level:** 🔒🔒 Medium
- Prevents spam
- Limits abuse
- Protects resources

### Level 3: HTTPS + Domain (Home Server)

**Setup nginx with Let's Encrypt:**

```bash
# Install
sudo apt install nginx certbot python3-certbot-nginx

# Configure nginx
sudo nano /etc/nginx/sites-available/veo-app
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Enable and get SSL
sudo ln -s /etc/nginx/sites-available/veo-app /etc/nginx/sites-enabled/
sudo certbot --nginx -d your-domain.com
sudo systemctl restart nginx
```

**Security Level:** 🔒🔒🔒 High
- Encrypted traffic
- Professional setup
- Prevents MITM attacks

### Level 4: VPN Only Access (Maximum Security)

**Home Server behind VPN:**

```bash
# Install WireGuard
sudo apt install wireguard

# Generate keys and configure
# (detailed WireGuard setup guide available)

# Configure firewall to only allow VPN
sudo ufw default deny incoming
sudo ufw allow from 10.0.0.0/24 to any port 8501
sudo ufw enable
```

**Security Level:** 🔒🔒🔒🔒 Maximum
- No public access
- VPN required
- Full control
- Best for internal use

## 🎯 Recommendations by Use Case

### Personal Use (Just You)
✅ **Run locally** - No internet exposure
```bash
streamlit run streamlit_app.py
```
**Risk Level:** 🟢 None

### Small Team (2-10 people)
✅ **Streamlit Cloud + Password**
- Deploy to Streamlit Cloud
- Add password protection
- Share password with team only
- Monitor usage
**Risk Level:** 🟡 Low

### Clients/Partners (10-50 people)
✅ **Streamlit Cloud + Password + Monitoring**
- Same as above
- Give each person unique info (for tracking)
- Check Streamlit Cloud metrics regularly
- Set expectations on usage
**Risk Level:** 🟡 Low-Medium

### Public Internet (Anyone)
❌ **NOT RECOMMENDED**
**Unless:**
- You add OAuth authentication
- Rate limiting per IP
- CAPTCHA for abuse prevention
- Terms of service
- Budget for API costs if abused
**Risk Level:** 🔴 High

### Company Internal (Private Network)
✅ **Home Server behind VPN**
- Deploy to internal server
- Require VPN connection
- HTTPS with internal CA
- Monitor logs
**Risk Level:** 🟢 Very Low

## 🚨 Red Flags - Shut It Down If:

1. **Unusual Traffic**
   - Hundreds of requests from unknown sources
   - Multiple IPs generating videos constantly
   - Strange patterns in logs

2. **Performance Issues**
   - Server running out of resources
   - Slow response times
   - Memory exhaustion

3. **API Key Concerns**
   - Your key was used without permission
   - Quota exceeded unexpectedly
   - Suspicious generation history

## 📊 Monitoring Checklist

**Daily:**
- [ ] Check Streamlit Cloud metrics (if using)
- [ ] Review any error emails
- [ ] Spot-check generation history

**Weekly:**
- [ ] Review all users (if tracked)
- [ ] Check API quota usage
- [ ] Verify no suspicious activity

**Monthly:**
- [ ] Review access logs
- [ ] Update dependencies
- [ ] Review security settings

## 🔐 Best Practices

1. **Use Strong Passwords**
   ```
   ❌ Bad: password123
   ✅ Good: xK9$mP2#vL8@qR5!nF3
   ```

2. **HTTPS Always**
   - Streamlit Cloud: Automatic ✅
   - Home Server: Setup nginx + Let's Encrypt
   - Local: Not needed if only localhost

3. **Share Wisely**
   - Don't post URL publicly
   - Share via secure channels (Signal, encrypted email)
   - Don't put password in the URL

4. **Monitor Usage**
   - Check who's using it
   - Watch for unusual patterns
   - Set up alerts if possible

5. **Have an Off Switch**
   - Know how to shut it down quickly
   - Streamlit Cloud: Stop app in dashboard
   - Home Server: `docker-compose down`
   - Can always unpublish the repo

## ✅ Final Recommendation

**For your use case (non-technical users):**

**Best Option:** Streamlit Cloud + Password Protection

**Setup:**
1. Deploy to Streamlit Cloud (free)
2. Use `streamlit_app_secure.py` version
3. Set strong password in Secrets
4. Share URL + password only with intended users
5. Monitor usage weekly

**This gives you:**
- ✅ Free hosting
- ✅ HTTPS encryption
- ✅ Basic access control
- ✅ Easy to shut down if needed
- ✅ No server management
- ✅ Separate API keys per user

**Risk Level:** 🟡 Low (acceptable for most teams)

## 📞 Emergency Response

**If something goes wrong:**

1. **Streamlit Cloud:**
   - Go to https://share.streamlit.io
   - Click your app
   - Click "Stop" or "Delete"

2. **Home Server:**
   ```bash
   docker-compose down
   # or
   sudo systemctl stop docker
   ```

3. **Change Passwords:**
   - Update secrets.toml
   - Redeploy

4. **Revoke API Keys:**
   - Go to GenAIPro dashboard
   - Regenerate your API key
   - Inform users to get new keys

## 🆘 Questions?

**Still Not Sure?**
- Start with password protection
- Deploy to Streamlit Cloud (safest option)
- Share with 2-3 trusted users first
- Monitor for a week
- Expand gradually if no issues

**Need More Security?**
- Consider OAuth integration
- Add user registration system
- Implement rate limiting
- Set up proper monitoring
- Consider paid hosting with better security

---

**Remember:** The most important security feature is **monitoring and being ready to shut it down** if something goes wrong.
