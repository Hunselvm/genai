# Troubleshooting Guide

## Common Errors and Solutions

### ❌ TCPTransport Closed Error

**Error Message:**
```
Error: unable to perform operation on <TCPTransport closed=True reading=False>; the handler is closed
```

**What It Means:**
The connection to the VEO API server was closed unexpectedly during video generation.

**Solutions:**

1. **Just Try Again** (Most Common Fix)
   - This is usually a temporary network issue
   - Click the generate button again
   - It should work on the second try

2. **Check Your Internet Connection**
   ```bash
   # Test if you can reach the API
   curl -I https://genaipro.vn
   ```
   - Make sure you have stable internet
   - Try on a different network if possible

3. **Verify API Key is Valid**
   - Go to https://genaipro.vn/docs-api
   - Check if your API key is still active
   - Regenerate if needed and update in the app

4. **Wait a Few Minutes**
   - The VEO API servers might be experiencing issues
   - Try again in 5-10 minutes

5. **Restart the App**
   - If running locally: `Ctrl+C` then restart
   - If on Streamlit Cloud: Reboot app from dashboard

**Technical Details:**
This error happens when:
- Network connection drops mid-request
- Server closes connection due to timeout
- Too many concurrent connections
- VEO API server is temporarily unavailable

**Fixed in Latest Version:**
We've improved error handling to:
- Properly configure connection timeouts
- Use connection pooling
- Catch and recover from connection errors
- Provide clearer error messages

---

### ❌ Connection Failed Error

**Error Message:**
```
Connection failed: [various messages]
```

**Solutions:**

1. **Check Internet Connection**
   - Verify you're online
   - Try loading https://genaipro.vn in your browser

2. **Firewall/VPN Issues**
   - Disable VPN temporarily
   - Check if firewall is blocking the connection
   - Try on a different network

3. **API Server Status**
   - Visit https://genaipro.vn to see if it's accessible
   - Check GenAIPro social media for status updates

---

### ❌ Authentication Error

**Error Message:**
```
Invalid API key
```

**Solutions:**

1. **Verify API Key**
   - Go to https://genaipro.vn/docs-api
   - Copy your API key again (don't copy extra spaces!)
   - Paste it in the sidebar

2. **Check API Key Format**
   - Should be a JWT token (long string with dots)
   - Example format: `eyJhbGc...` (starts with eyJ)

3. **Regenerate API Key**
   - In GenAIPro dashboard
   - Click "Regenerate API Key"
   - Copy the new key
   - Update in app sidebar

---

### ❌ Quota Exceeded Error

**Error Message:**
```
API quota exceeded
```

**Solutions:**

1. **Check Your Quota**
   - Click "Check Quota" button in sidebar
   - See how much you have remaining

2. **Purchase More Quota**
   - Go to https://genaipro.vn
   - Add credits to your account

3. **Wait for Quota Reset**
   - Some plans reset monthly
   - Check your plan details

---

### ❌ Video Generation Failed

**Error Message:**
```
Video generation failed: [various reasons]
```

**Solutions:**

1. **Check Your Prompt**
   - Make sure prompt is not empty
   - Avoid very long prompts (>500 characters)
   - Remove special characters if present

2. **Verify Image Files**
   - For frames/ingredients: check images are valid
   - Supported formats: JPG, JPEG, PNG, WebP
   - File size should be reasonable (<10MB per image)

3. **Try Simpler Settings**
   - Generate 1 video instead of multiple
   - Use shorter prompt
   - Try different aspect ratio

---

### ❌ File Upload Issues

**Error Message:**
```
Failed to upload image / Invalid image format
```

**Solutions:**

1. **Check Image Format**
   - Supported: JPG, JPEG, PNG, WebP
   - Not supported: GIF, BMP, TIFF
   - Convert to JPG/PNG if needed

2. **Check File Size**
   - Keep images under 10MB
   - Resize if too large

3. **Verify Image Integrity**
   - Open image in another app to verify it's not corrupted
   - Try a different image

---

### ❌ App Won't Load / White Screen

**Solutions:**

1. **Clear Browser Cache**
   ```
   Chrome: Ctrl+Shift+Delete (or Cmd+Shift+Delete on Mac)
   Clear "Cached images and files"
   ```

2. **Try Different Browser**
   - Chrome, Firefox, Safari, Edge
   - Make sure browser is updated

3. **Check Streamlit Cloud Status**
   - If using Streamlit Cloud deployment
   - Check if app is running in dashboard

4. **Restart the App**
   - Local: `Ctrl+C` and restart
   - Streamlit Cloud: Reboot from dashboard

---

### ❌ Password Not Working

**Error Message:**
```
Password incorrect
```

**Solutions:**

1. **Check Password Carefully**
   - Password is case-sensitive
   - Make sure no extra spaces
   - Copy-paste if typing manually

2. **Verify Streamlit Cloud Secrets**
   - Go to App Settings → Secrets
   - Check `app_password` is set correctly
   - No quotes needed around the password value

3. **Contact Administrator**
   - If you're a user, ask who deployed the app
   - They can reset the password

---

### ❌ Slow Performance / Timeouts

**Solutions:**

1. **Be Patient**
   - Video generation takes 1-5 minutes
   - Don't refresh the page
   - Wait for progress bar to complete

2. **Try During Off-Peak Hours**
   - Early morning or late night
   - Weekdays vs weekends

3. **Generate Fewer Videos**
   - Try 1 video instead of 4
   - Multiple videos take longer

4. **Check Internet Speed**
   ```bash
   # Run speed test
   speedtest-cli
   ```
   - Need stable connection, not just fast

---

### ❌ History Won't Load

**Solutions:**

1. **Click "Load History" Button**
   - History doesn't auto-load
   - Click the button to fetch

2. **Check API Key**
   - History is tied to your API key
   - Make sure key is entered

3. **Try Different Page Size**
   - Change from 20 to 10 items
   - Might load faster

4. **Check If You Have History**
   - If you haven't generated videos yet
   - History will be empty

---

## 🔧 Debug Mode

### Enable Detailed Error Messages

If running locally, you can see detailed errors:

1. **Look at Terminal Output**
   - Where you ran `streamlit run`
   - Full error traces appear there

2. **Check Browser Console**
   - F12 → Console tab
   - See JavaScript errors

3. **Streamlit Cloud Logs**
   - App dashboard → "Manage app" → "Logs"
   - See server-side errors

---

## 🆘 Still Having Issues?

### Get Help:

1. **Check SECURITY.md**
   - Comprehensive security guide
   - Common deployment issues

2. **Check README_STREAMLIT.md**
   - Full documentation
   - Setup instructions

3. **Contact GenAIPro Support**
   - Telegram: https://t.me/genaipro_vn
   - Facebook: https://www.facebook.com/genaipro.vn

4. **Check GitHub Issues**
   - https://github.com/Hunselvm/genai/issues
   - See if others had same problem

---

## 📊 System Requirements

### Minimum Requirements:
- Modern browser (Chrome, Firefox, Safari, Edge)
- Stable internet connection (2+ Mbps)
- JavaScript enabled

### Recommended:
- Latest browser version
- 10+ Mbps internet
- Desktop/laptop (mobile works but harder to use)

---

## ✅ Quick Fixes Checklist

Before asking for help, try these:

- [ ] Refresh the page (F5)
- [ ] Try again (many errors are temporary)
- [ ] Clear browser cache
- [ ] Try different browser
- [ ] Check internet connection
- [ ] Verify API key is correct
- [ ] Check quota is not exceeded
- [ ] Wait 5 minutes and try again
- [ ] Restart the app (if local)
- [ ] Reboot app (if Streamlit Cloud)

**Most issues resolve with a simple retry!**

---

## 🐛 Report a Bug

If you found a real bug:

1. **Gather Information:**
   - What you were trying to do
   - Exact error message
   - Screenshots if possible
   - Browser and OS version

2. **Check if Already Reported:**
   - GitHub Issues: https://github.com/Hunselvm/genai/issues

3. **Create Issue:**
   - Include all information above
   - Steps to reproduce
   - Expected vs actual behavior

---

**Remember:** Most errors are temporary network issues. Just try again! 🔄
