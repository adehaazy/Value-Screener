# Deployment Guide — Secure Auth System on Streamlit Cloud
### Complete beginner-friendly walkthrough

---

## What you'll need
- A computer with internet access
- About 30–45 minutes
- A free account on each service below (all free, no credit card needed for MVP)

| Service | What it's for | Sign-up link |
|---|---|---|
| GitHub | Stores your code | https://github.com |
| Streamlit Community Cloud | Hosts your app (free) | https://streamlit.io/cloud |
| Mailgun | Sends emails (100/day free) | https://mailgun.com |

---

## PHASE 1 — Set up GitHub (your code's home)

### Step 1: Create a GitHub account
1. Go to https://github.com and click **Sign up**
2. Enter your email, create a password, choose a username
3. Verify your email when prompted

### Step 2: Create a new repository
1. Once logged in, click the **+** icon (top-right) → **New repository**
2. Fill in:
   - **Repository name:** `my-secure-app` (or any name you like)
   - **Visibility:** ✅ **Private** ← important! Never make auth code public
   - Leave everything else as default
3. Click **Create repository**

### Step 3: Upload your files to GitHub
1. On your new repository page, click **uploading an existing file** (the link in the middle of the page)
2. Drag and drop ALL of these files from your folder:
   ```
   streamlit_app.py
   auth_utils.py
   security.py
   email_service.py
   audit.py
   database.py
   test_auth.py
   requirements_auth.txt
   ```
3. At the bottom, click **Commit changes**

> ⚠️ **Do NOT upload** `secrets.toml` or any file containing passwords. That file stays on your computer only.

---

## PHASE 2 — Set up Mailgun (email sending)

### Step 4: Create a Mailgun account
1. Go to https://mailgun.com → click **Start for Free**
2. Sign up with your email and verify it
3. You may need to enter a phone number for SMS verification

### Step 5: Get your sending credentials
1. After logging in, in the left sidebar click **Send** → **Domains**
2. You'll see a sandbox domain like: `sandbox abc123.mailgun.org`
   - This is your free test domain (100 emails/day)
3. Click on that sandbox domain
4. Click the **SMTP** tab
5. You'll see something like this — write these down:

   | Setting | Example value |
   |---|---|
   | SMTP Hostname | `smtp.mailgun.org` |
   | Port | `587` |
   | Username (Login) | `postmaster@sandbox-abc123.mailgun.org` |
   | Default Password | `abc123xyz...` (click the eye icon to reveal) |

6. Under **Authorized Recipients** (sandbox only): click **Add Recipient** and add any email address you want to test with. Mailgun's sandbox only sends to pre-approved addresses during testing.

> 💡 Later, if you want to send to anyone (not just test addresses), you'll need to add and verify a real domain in Mailgun. For the MVP, the sandbox is fine.

---

## PHASE 3 — Generate your secret keys

### Step 6: Generate a JWT secret key
This is a random password that signs your login tokens. You need to generate it once.

**Option A — if you have Python installed on your computer:**
1. Open Terminal (Mac/Linux) or Command Prompt (Windows)
2. Type:
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Copy the long string it prints (looks like: `a3f9bc12...`)

**Option B — use an online generator:**
1. Go to https://www.random.org/strings/
2. Set length to 64 characters, use hex characters (0-9, a-f)
3. Generate and copy the result

Save this key somewhere safe — you'll need it in the next step.

---

## PHASE 4 — Deploy on Streamlit Cloud

### Step 7: Connect Streamlit Cloud to GitHub
1. Go to https://share.streamlit.io
2. Click **Sign in with GitHub** and authorize Streamlit
3. You'll land on your Streamlit Cloud dashboard

### Step 8: Create a new app
1. Click **New app** (top-right button)
2. Fill in:
   - **Repository:** select `my-secure-app` (your GitHub repo)
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
3. **Do not click Deploy yet** — you need to add secrets first

### Step 9: Add your secrets ← critical security step
1. On the same "Deploy" page, click **Advanced settings**
2. You'll see a large text box labelled **Secrets**
3. Copy and paste this exactly, replacing the placeholder values with your real ones:

```toml
JWT_SECRET_KEY = "paste-your-64-character-key-here"

MAILGUN_SMTP_HOST = "smtp.mailgun.org"
MAILGUN_SMTP_USER = "postmaster@sandbox-abc123.mailgun.org"
MAILGUN_SMTP_PASSWORD = "your-mailgun-password-here"
MAILGUN_SENDER = "postmaster@sandbox-abc123.mailgun.org"

APP_URL = "https://your-app-name.streamlit.app"
```

> ⚠️ You don't know your APP_URL yet — that's fine. Put a placeholder for now and update it in Step 11.

4. Click **Save**

### Step 10: Add your requirements file
Streamlit Cloud needs to know which Python packages to install. By default it looks for `requirements.txt`. Since your project already has one for the Value Screener, you need to **merge** the auth dependencies into it.

In GitHub, open `requirements.txt` and click the **pencil (edit) icon**, then add these lines at the bottom:
```
argon2-cffi==23.1.0
PyJWT==2.8.0
passlib==1.7.4
python-dotenv==1.0.1
```
Click **Commit changes**.

### Step 11: Deploy!
1. Click **Deploy** — Streamlit will now build your app (takes 1–3 minutes)
2. Watch the log output — green ✅ means success
3. When it's done, you'll see a URL like: `https://my-secure-app-abc123.streamlit.app`
4. **Copy that URL** and go back to Streamlit Cloud → **App settings** → **Secrets**
5. Update `APP_URL` with your real URL, then click **Save** (the app will restart)

---

## PHASE 5 — First-time setup (create your admin account)

### Step 12: Create your first invitation (as admin)
The app is invite-only, so you need to invite yourself first.

1. Open your app URL in a browser
2. In the URL bar, add `?page=admin` at the end and press Enter:
   ```
   https://your-app.streamlit.app/?page=admin
   ```
   > Note: The admin page currently has no login guard for the very first setup. After you've logged in, revisit this and your session will be checked.
3. Enter your own email address and click **Generate Invitation**
4. You'll see a token on screen — also check your email (if Mailgun is configured)

### Step 13: Register your account
1. Go to your app URL with `?page=signup`
2. Enter your email and paste the invitation token
3. Click **Complete Registration**
4. Check your email for:
   - A **temporary password** (use this to log in)
   - A **verification link** (click it before trying to log in)

### Step 14: Verify your email
1. Click the verification link in your email
2. You should see "✅ Your email has been verified!"
3. Click **Go to Login**

### Step 15: Log in and change your password
1. Enter your email and the temporary password
2. You'll be automatically prompted to set a new password
3. Choose a strong password (the checklist will guide you)
4. Log in again with your new password — you're in! 🎉

---

## PHASE 6 — Ongoing maintenance

### Inviting new users
1. Log in to your app
2. Go to `your-app-url/?page=admin`
3. Enter the new user's email → click **Generate Invitation**
4. The invitation email is sent automatically, or share the token manually

### Monitoring
- Check your Mailgun dashboard to see sent emails and any delivery failures
- Streamlit Cloud shows app logs under **Manage app** → **Logs**

### Updating your code
Whenever you make changes to your Python files:
1. Upload the updated file(s) to GitHub (replace the old ones)
2. Streamlit Cloud automatically detects the change and redeploys within ~1 minute

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| App shows an error on startup | Missing package in requirements.txt | Add the missing package and commit |
| Emails not arriving | Mailgun credentials wrong, or recipient not in sandbox allowlist | Double-check secrets; add recipient in Mailgun dashboard |
| "Invalid or expired invitation" | Token expired (7-day limit) or mistyped | Generate a new invitation |
| Can't log in after verifying email | Email not in Mailgun authorized list | Add your email as an authorized recipient in Mailgun sandbox settings |
| App URL in emails is wrong | APP_URL secret not updated | Update APP_URL in Streamlit secrets to your real app URL |
| Forgot your password | Use the "Forgot password?" link on the login page | — |

---

## Security checklist before going live

- [ ] `secrets.toml` is NOT in GitHub (check your repo — it should not be there)
- [ ] Your GitHub repo is set to **Private**
- [ ] `JWT_SECRET_KEY` is a long random string (not the placeholder)
- [ ] Mailgun credentials are real (not the template placeholders)
- [ ] You've tested the full flow: invite → register → verify → login → reset password
- [ ] You've logged out and confirmed you can log back in

---

*You're all set! If anything goes wrong, re-read the Troubleshooting section above or check the app logs in Streamlit Cloud.*
