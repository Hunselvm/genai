# Streamlit Cloud Password Setup - URGENT

## 🔒 Your App is Now Password Protected!

Streamlit Cloud should be auto-deploying the new secure version right now.

## ⚡ STEP 1: Add Password to Streamlit Cloud (DO THIS NOW)

### Go to Your Streamlit Cloud Dashboard:

1. **Open:** https://share.streamlit.io
2. **Find your app** in the list (should be deploying/running)
3. **Click the ⋮ (three dots)** menu next to your app
4. **Click "Settings"**

### Add the Password Secret:

5. **Click "Secrets"** in the left sidebar
6. **In the text editor, add:**

```toml
app_password = "YourSecurePassword123!"
```

**⚠️ IMPORTANT:**
- Replace `YourSecurePassword123!` with a STRONG password
- Use at least 12 characters
- Include letters, numbers, and symbols
- Don't use common words

**Example of strong password:**
```toml
app_password = "xK9$mP2#vL8@qR5!nF3"
```

7. **Click "Save"**
8. **Your app will restart automatically** (takes ~30 seconds)

## ✅ STEP 2: Verify It's Working

1. **Visit your app URL:** `https://your-app-name.streamlit.app`
2. **You should see:** A login screen asking for password
3. **Test it:**
   - Try wrong password → Should show error
   - Enter correct password → Should let you in

## 🔐 What Happens Now:

**Before someone can use your app:**
1. They visit the URL
2. They see a password login screen
3. They must enter the correct password
4. Only then can they access the video generation features
5. They still need their own API key to generate videos

## 📱 How to Share with Users:

**Send them:**
1. **App URL:** `https://your-app-name.streamlit.app`
2. **App Password:** (the one you set in Secrets)
3. **Instructions:** "Enter the password, then enter your own GenAIPro API key in the sidebar"

**Example message:**
```
Hi! Here's access to the VEO video generation app:

🔗 URL: https://your-app.streamlit.app
🔑 Password: [password you set]

After logging in, you'll need to enter your own GenAIPro API key
from https://genaipro.vn/docs-api in the sidebar.

Let me know if you have any questions!
```

## ⚠️ If You Don't Add the Password:

Without the password configured in Streamlit Cloud Secrets:
- The app will use the default password: `changeme123`
- This is NOT secure for public use
- Anyone who finds your app can access it

**YOU MUST set a strong password in Streamlit Cloud Secrets!**

## 🔄 How to Change the Password Later:

1. Go to Streamlit Cloud → Your App → Settings → Secrets
2. Change the `app_password` value
3. Click Save
4. App restarts with new password
5. Inform your users of the new password

## 🚨 Emergency: If Someone Unauthorized Got Access

If you suspect someone unauthorized has the password:

**Option 1: Change Password**
1. Go to Streamlit Cloud → Settings → Secrets
2. Change `app_password` to a new value
3. Save
4. Share new password with authorized users only

**Option 2: Temporarily Shut Down**
1. Go to Streamlit Cloud
2. Click ⋮ menu → "Stop app" or "Delete app"
3. App is immediately offline
4. Redeploy when ready with new password

## ✅ Current Security Status:

After completing these steps:
- ✅ Password required to access app
- ✅ HTTPS encryption (automatic on Streamlit Cloud)
- ✅ No API keys in GitHub
- ✅ Each user uses their own API key
- ✅ You can shut it down anytime
- ✅ Safe for sharing with your team

## 📊 Monitoring Usage:

**Streamlit Cloud provides:**
- Number of viewers
- Resource usage
- Error logs

**To monitor:**
1. Go to Streamlit Cloud dashboard
2. Click your app
3. View "Analytics" tab

**Red flags:**
- Hundreds of viewers (should be just your team)
- High resource usage
- Many error logs

If you see unusual activity → Stop the app immediately

## 🆘 Need Help?

**Can't find Secrets settings?**
- Make sure you're logged into Streamlit Cloud
- Click the ⋮ menu, then "Settings"
- "Secrets" is in the left sidebar

**App not restarting?**
- Manual restart: Click "Reboot app" button
- Check logs for errors
- Verify TOML syntax is correct (no quotes around the whole line)

**Users can't login?**
- Verify you saved the password in Secrets
- Check there are no extra spaces
- Password is case-sensitive

---

## 🎯 Quick Checklist:

- [ ] Opened Streamlit Cloud dashboard
- [ ] Found my app settings
- [ ] Clicked "Secrets"
- [ ] Added `app_password = "my_strong_password"`
- [ ] Clicked "Save"
- [ ] Waited for app to restart (~30 seconds)
- [ ] Visited app URL and saw login screen
- [ ] Tested password works
- [ ] Ready to share with users!

---

**Your app is now secure and ready to share!** 🎉
