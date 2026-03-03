# ReNoUn Deployment Guide

Two things to deploy: the **landing page** (static HTML) and the **API backend** (FastAPI + core.py).

---

## Part 1 — Landing Page (Netlify)

Netlify hosts the static landing page for free. Takes about 5 minutes.

### Steps

1. Go to [app.netlify.com](https://app.netlify.com) and sign up (use GitHub or email)
2. Once logged in, go to **Sites** → **Add new site** → **Deploy manually**
3. Drag and drop the `landing/` folder from your computer onto the upload area
4. Netlify gives you a URL like `random-name-12345.netlify.app`
5. To use a custom domain (e.g. `harrisoncollab.com`):
   - Go to **Site settings** → **Domain management** → **Add custom domain**
   - Update your DNS to point to Netlify's servers (they walk you through it)

Your landing page is now live.

---

## Part 2 — API Backend (Railway)

Railway runs the FastAPI server with your core.py. Free tier gives you $5/month of usage — enough to get started.

### Prerequisites

- A GitHub account (free at github.com)
- Your `core.py` file ready to upload privately

### Step 1: Create the GitHub Repo

```bash
# From the renoun-mcp directory on your machine
git init
git add .
git commit -m "Initial commit — ReNoUn MCP wrapper + API"

# Create the repo on GitHub (go to github.com/new)
# Name: renoun-mcp
# Visibility: PUBLIC (core.py is in .gitignore — it won't be pushed)

git remote add origin https://github.com/YOUR_USERNAME/renoun-mcp.git
git branch -M main
git push -u origin main
```

**Verify core.py was NOT pushed:** Check the repo on GitHub — you should NOT see core.py listed.

### Step 2: Deploy to Railway

1. Go to [railway.com](https://railway.com) and sign up with your GitHub account
2. Click **New Project** → **Deploy from GitHub Repo**
3. Select your `renoun-mcp` repository
4. Railway detects the Dockerfile and starts building

### Step 3: Upload core.py to Railway

Since core.py isn't in the repo, you need to add it to the running container:

**Option A — Railway Volume (recommended):**
1. In Railway dashboard, click your service
2. Go to **Settings** → **Volumes** → **Mount Volume**
3. Mount path: `/data`
4. Use the Railway CLI to upload core.py:
   ```bash
   npm install -g @railway/cli
   railway login
   railway link  # select your project
   railway run cp /path/to/your/core.py /data/core.py
   ```
5. Set environment variable: `RENOUN_CORE_PATH=/data/core.py`

**Option B — Include in Dockerfile build (simpler for now):**
1. On your local machine, temporarily copy core.py into the renoun-mcp folder
2. Build the Docker image locally and push to Railway:
   ```bash
   railway login
   railway link
   railway up
   ```
3. Remove core.py from the folder after deploy (it's in .gitignore so git never sees it)

### Step 4: Set Environment Variables

In Railway dashboard → your service → **Variables**, add:

```
STRIPE_SECRET_KEY=sk_live_...          # from Stripe dashboard
STRIPE_WEBHOOK_SECRET=whsec_...        # from Stripe webhook settings
STRIPE_PRICE_ID=price_...              # from Stripe product catalog
RENOUN_CORS_ORIGINS=https://harrisoncollab.com
```

### Step 5: Get Your Public URL

1. In Railway dashboard → your service → **Settings** → **Networking**
2. Click **Generate Domain** — you get something like `renoun-mcp-production.up.railway.app`
3. Or add a custom domain (e.g. `api.harrisoncollab.com`)

### Step 6: Verify It's Running

```bash
curl https://YOUR-DOMAIN.up.railway.app/v1/status
```

You should see:
```json
{"status": "ok", "version": "1.1.0", "engine": "ReNoUn Structural Analysis"}
```

---

## Part 3 — Connect Stripe

Now that the API is live, you can finish Stripe setup.

### Steps

1. Go to [dashboard.stripe.com](https://dashboard.stripe.com) and create an account
2. **Create the product:**
   - Go to **Product catalog** → **Add product**
   - Name: "ReNoUn Pro"
   - Price: $4.99 / month (recurring)
   - Copy the **Price ID** (starts with `price_`)
3. **Set up the webhook:**
   - Go to **Developers** → **Webhooks** → **Add endpoint**
   - URL: `https://YOUR-DOMAIN.up.railway.app/v1/billing/webhook`
   - Events to listen for:
     - `checkout.session.completed`
     - `invoice.payment_succeeded`
     - `invoice.payment_failed`
     - `customer.subscription.deleted`
     - `customer.subscription.updated`
   - Copy the **Webhook signing secret** (starts with `whsec_`)
4. **Get your API keys:**
   - Go to **Developers** → **API keys**
   - Copy the **Secret key** (starts with `sk_live_` or `sk_test_` for testing)
5. **Add all three values to Railway** as environment variables (see Step 4 above)

### Test the Full Flow

```bash
# Create a free API key
curl -X POST https://YOUR-DOMAIN.up.railway.app/v1/billing/checkout \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
```

This returns a Stripe Checkout URL. Open it, pay, and Stripe's webhook auto-provisions a pro API key.

---

## Part 4 — Update Landing Page

Once you have your API domain, update the landing page's demo section to point to the real API instead of the client-side simulation:

1. In `landing/index.html`, find the demo JavaScript section
2. Replace the simulated analysis with a real `fetch()` call to your API
3. Re-deploy to Netlify (drag and drop the folder again, or set up continuous deploy from GitHub)

---

## Quick Reference

| Service | URL | Cost |
|---------|-----|------|
| Landing page | Netlify → harrisoncollab.com | Free |
| API backend | Railway → api.harrisoncollab.com | Free tier ($5/mo credit) |
| Payments | Stripe | 2.9% + 30¢ per transaction |
| Source code | GitHub → renoun-mcp | Free (public repo) |

---

## Troubleshooting

**Railway build fails:** Make sure your Dockerfile is in the repo root and requirements-api.txt lists all dependencies.

**Stripe webhooks return 400:** Check that `STRIPE_WEBHOOK_SECRET` matches the signing secret from your webhook endpoint (not your API key).

**core.py not found:** Verify `RENOUN_CORE_PATH` env var points to where you uploaded core.py on the Railway container.

**CORS errors from landing page:** Add your landing page domain to `RENOUN_CORS_ORIGINS` in Railway variables.
