# Requirements Setup Guide

**Set up the external services before you install VirtualPyTest.**

You need three outside services and one AI provider.

**Estimated time: 15 minutes**

---

## 1. Supabase: database and sign-in

Supabase holds the database and handles sign-in.

### Step 1: Create a Supabase project

1. **Sign up** at [supabase.com](https://supabase.com)
2. **Create a new project**. Save the database password it asks for.
3. **Wait** about 2 minutes for the project to be ready.

<div data-technical>

Project name: `virtualpytest` (or any name you like). Database password: generate a strong password and save it. Region: the one closest to you.

</div>

### Step 2: Get the Supabase keys

Go to **Settings**, then **API**. Copy the Project URL and the two keys: the anon (public) key and the service role key.

<div data-technical>

Example format:

```
Project URL: https://your-project-id.supabase.co
Anon (public) key: <your-anon-key>
Service role key: <your-service-role-key>
```

</div>

### Step 3: Set up the database

<div data-technical>

VirtualPyTest creates the tables it needs on the first run. To set them up by hand: go to **SQL Editor** in the Supabase dashboard and run the setup scripts from the `setup/db/` folder of the VirtualPyTest project.

</div>

### Supabase is ready

Keep these keys for your `.env` files later.

---

## 2. Cloudflare R2: file storage

R2 stores video recordings, screenshots and other test files.

### Step 1: Create a Cloudflare account

**Sign up** at [cloudflare.com](https://cloudflare.com) and verify your email.

### Step 2: Create a bucket

In **R2 Object Storage**, click **Create bucket** and name it `virtualpytest-storage`. The name must be unique worldwide.

### Step 3: Create an access token

In **Manage R2 API tokens**, click **Create API token**. Give it the permission `Object Read and Write` and select your bucket.

<div data-technical>

Token name: `VirtualPyTest Access`. Expiry: no expiry, or what you prefer.

</div>

### Step 4: Copy the R2 keys

Copy the Access Key ID, the Secret Access Key, the bucket name and your Account ID.

<div data-technical>

The Account ID is on the R2 dashboard. Example format:

```
Access Key ID: abc123...
Secret Access Key: xyz789...
Bucket Name: virtualpytest-storage
Account ID: your-account-id (from R2 dashboard)
```

</div>

### R2 is ready

<div data-technical>

Your bucket can now hold test files.

</div>

---

## 3. Upstash Redis: job queue (optional, legacy)

Upstash Redis is being phased out and is **not needed** for the core features. Skip this unless a feature you use needs it.

<div data-technical>

Marked `DISCARD REDIS` in the project's `.env.example`. Once set up, your Redis queue is ready for jobs.

**Create an Upstash account:** sign up at [upstash.com](https://upstash.com) and verify your email.

**Create a Redis database:** click **Create database** with these settings:
- Name: `virtualpytest-queue`
- Region: the one closest to you
- Type: Regional (recommended for speed)

**Copy the Redis keys:** from your database page, copy the endpoint, the port, the password, the REST URL and the REST token.

Example format:

```
Endpoint: redis-12345.upstash.io
Port: 12345
Password: your-redis-password
REST URL: https://redis-12345.upstash.io
REST Token: your-rest-token
```

</div>

---

## 4. AI provider: test analysis and the agent (optional)

You need at least one AI provider key. Anthropic is the recommended default. Local servers such as LM Studio or Ollama need no key.

<div data-technical>

A fresh install sends the agents to **Anthropic**, and vision and text analysis to **OpenRouter**. OpenAI, MiniMax, Google and any OpenAI-compatible server are also supported.

</div>

### Step 1: Get an API key

- **Anthropic** (recommended): sign up at [console.anthropic.com](https://console.anthropic.com) and create an API key.
- **OpenRouter**: sign up at [openrouter.ai](https://openrouter.ai), add credits (at least $5 is a good start for testing), and create a key under **Keys**.

### Step 2: Enter the key in the app

Open **Settings**, then **AI**, then **Endpoints**. Paste the key into the matching endpoint and press **Test**. Then choose which model handles each use case under **Routing**.

<div data-technical>

The key is stored on the server only, never in `.env` and never on the hosts. You can add several providers.

</div>

### AI provider is ready

<div data-technical>

Your AI analysis service is ready.

</div>

---

## 5. Set the environment files

Add the keys to your environment files.

### Main settings (`.env`)

<div data-technical>

```bash
# Supabase
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_KEY=<your-service-role-key>

# Cloudflare R2
R2_ACCESS_KEY_ID=abc123...
R2_SECRET_ACCESS_KEY=xyz789...
R2_BUCKET_NAME=virtualpytest-storage
R2_ACCOUNT_ID=your-account-id

# Redis (optional / legacy — DISCARD REDIS in .env.example, skip unless needed)
# UPSTASH_REDIS_REST_URL=https://your-db.upstash.io
# UPSTASH_REDIS_REST_TOKEN=your-rest-token

# AI: nothing here. Providers, API keys and which model serves each use case are set in
# the web app under Settings → AI (Endpoints / Profiles / Routing) and stored server-side.
# A local model server (Ollama, vLLM, llama.cpp, LM Studio, Colibri...) is an endpoint with
# the "OpenAI-compatible" preset, e.g. http://10.10.10.10:8000/v1 (Ollama: http://<host>:11434/v1).
```

</div>

The AI keys are not in this file. You set them in the web app.

### Host settings (`backend_host/src/.env`)

<div data-technical>

```bash
# Copy relevant credentials here for host services
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
R2_ACCESS_KEY_ID=abc123...
R2_SECRET_ACCESS_KEY=xyz789...
# ... other host-specific settings
```

Add the other host-specific settings here too.

</div>

Copy the credentials the hosts need into this file.

### Frontend settings (`frontend/.env`)

<div data-technical>

```bash
# Public keys only (never put secret keys in frontend)
VITE_SUPABASE_URL=https://your-project-id.supabase.co
VITE_SUPABASE_ANON_KEY=<your-anon-key>
```

</div>

Only public keys go in this file. Never put a secret key here.

---

## Cost estimate

| Service | Free tier | Typical monthly cost |
|---------|-----------|---------------------|
| **Supabase** | 500MB DB, 1GB bandwidth | $0-25 (depending on usage) |
| **Cloudflare R2** | 10GB storage, 1M requests | $0-10 (pay per use) |
| **AI provider** (Anthropic, OpenRouter, etc.) | Varies by provider | $5-50 (depending on AI usage) |
| **Upstash Redis** (optional, legacy) | 10K requests/day | $0-20 if used |

**Total: about $5-85 a month.** Most users spend $10-30 a month. Redis is optional.

---

## Security

- **Never commit** API keys or secrets to version control.
- **Keep credentials in the environment files** (`.env`).
- **Change the keys every 3 to 6 months.**
- **Give only the access you need.**
- **Set up billing alerts** to catch unexpected costs.


---

## Checklist

Before you install VirtualPyTest, check that you have:

- [ ] **Supabase project** created, with its URL and API keys
- [ ] **R2 bucket** created, with access keys
- [ ] **AI provider account** with an API key

<div data-technical>

- [ ] **All the keys saved** somewhere safe

</div>

<div data-technical>

- [ ] **Upstash Redis** database with its details (optional, legacy: skip if unused)

</div>

---

## Troubleshooting

### Common problems

**Supabase connection fails:**
- Check the project URL format: `https://your-project-id.supabase.co`

<div data-technical>

- Wait 2 to 3 minutes after you create the project, then try again.
- Check that the API keys were copied in full. They are very long.

</div>

**R2 upload errors:**
- Check that the bucket name is unique worldwide.
- Check that the token has the right permissions.

<div data-technical>

- Check that the token has the Object Read and Write permission.
- Check that the Account ID is on the R2 dashboard.

</div>

<div data-technical>

**Redis connection timeout (only if you use it):**
- Check that the endpoint matches your Upstash dashboard.
- Check that the database is in the same region as your server.
- Check that the REST token was copied in full.

</div>

**AI provider errors:**
- Under **Settings**, then **AI**, then **Routing**, press **Test** on the endpoint and profile for the failing use case.
- Check the account has enough credit and the model name matches exactly.

<div data-technical>

The endpoint test checks the key, the connection and the model list. The profile test checks the model name and whether vision or tools are supported. The model name is case-sensitive. The server log shows one line per AI call, like `[AI] usage=… profile=… endpoint=… ok=…`.

</div>

### Where to get help

- **Supabase**: [docs.supabase.com](https://docs.supabase.com)
- **Anthropic**: [docs.anthropic.com](https://docs.anthropic.com)

<div data-technical>

- **Cloudflare R2**: [developers.cloudflare.com/r2](https://developers.cloudflare.com/r2)
- **OpenRouter**: [openrouter.ai/docs](https://openrouter.ai/docs)
- **Upstash** (optional, legacy): [docs.upstash.com](https://docs.upstash.com)

</div>

---

## Next steps

Once all the services are set up:

1. **Go back to** the [Getting Started Guide](getting-started.md).
2. **Follow** the quick start installation.
3. **Add the keys you just collected** to your `.env` files.

**Ready to install VirtualPyTest.**
