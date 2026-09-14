# Requirements Setup Guide

**External services setup for VirtualPyTest - Complete this before installation.**

VirtualPyTest requires 3 external services to function properly, plus one optional AI provider. This guide walks you through setting up each one and obtaining the necessary credentials.

**⏱️ Estimated time: 15 minutes**

---

## 🗄️ **1. Supabase - Database & Authentication**

Supabase provides the PostgreSQL database and authentication system for VirtualPyTest.

### Step 1: Create Supabase Project

1. **Sign up** at [supabase.com](https://supabase.com)
2. **Create new project**:
   - Project name: `virtualpytest` (or your preferred name)
   - Database password: Generate a strong password and **save it**
   - Region: Choose closest to your location
3. **Wait for project creation** (~2 minutes)

### Step 2: Get Supabase Credentials

Once your project is ready:

1. Go to **Settings** → **API**
2. Copy these values:
   ```
   Project URL: https://your-project-id.supabase.co
   Anon (public) key: <your-anon-key>
   Service role key: <your-service-role-key>
   ```

### Step 3: Database Setup

VirtualPyTest will automatically create the required tables on first run, but you can also run the setup manually:

1. Go to **SQL Editor** in Supabase dashboard
2. Run the initialization scripts from `setup/db/` in your VirtualPyTest project

### ✅ Supabase Complete
Save these credentials - you'll add them to your `.env` files later.

---

## ☁️ **2. Cloudflare R2 - Cloud Storage**

R2 stores video recordings, screenshots, and test artifacts with S3-compatible API.

### Step 1: Create Cloudflare Account

1. **Sign up** at [cloudflare.com](https://cloudflare.com)
2. **Verify your email** and complete account setup

### Step 2: Create R2 Bucket

1. Go to **R2 Object Storage** in Cloudflare dashboard
2. **Create bucket**:
   - Bucket name: `virtualpytest-storage` (must be globally unique)
   - Location: Choose closest region
3. **Create bucket**

### Step 3: Generate R2 API Token

1. Go to **Manage R2 API tokens**
2. **Create API token**:
   - Token name: `VirtualPyTest Access`
   - Permissions: `Object Read and Write`
   - Specify bucket: Select your bucket
   - TTL: No expiry (or set as needed)
3. **Create API token**

### Step 4: Get R2 Credentials

After creating the token, copy:
```
Access Key ID: abc123...
Secret Access Key: xyz789...
Bucket Name: virtualpytest-storage
Account ID: your-account-id (from R2 dashboard)
```

### ✅ R2 Complete
Your bucket is ready for storing test artifacts.

---

## 🚀 **3. Upstash Redis - Queue Management (Optional / Legacy)**

Upstash Redis was used for queue management. It's marked `DISCARD REDIS` in the project's `.env.example` — it is being phased out and is **not required** for core functionality. Skip this section unless a specific feature you're using still depends on it.

### Step 1: Create Upstash Account

1. **Sign up** at [upstash.com](https://upstash.com)
2. **Verify email** and complete registration

### Step 2: Create Redis Database

1. **Create database**:
   - Name: `virtualpytest-queue`
   - Region: Choose closest to your location
   - Type: Regional (recommended for better performance)
2. **Create database**

### Step 3: Get Redis Credentials

From your database dashboard, copy:
```
Endpoint: redis-12345.upstash.io
Port: 12345
Password: your-redis-password
REST URL: https://redis-12345.upstash.io
REST Token: your-rest-token
```

### ✅ Upstash Complete
Your Redis queue is ready for job management.

---

## 🤖 **4. AI Provider - Test Analysis & Agent (Optional)**

VirtualPyTest's AI agent, vision, and text analysis features need at least one AI provider API key. The default provider is **Anthropic** (used for the agent task by default); OpenRouter, OpenAI, MiniMax, and Google are supported alternates (see `shared/src/lib/ai/config.py`). Vision and text analysis default to OpenRouter unless overridden.

### Step 1: Get an API Key

Pick one provider to start:
- **Anthropic** (recommended default): sign up at [console.anthropic.com](https://console.anthropic.com), create an API key.
- **OpenRouter** (alternate, useful for a wider model catalog): sign up at [openrouter.ai](https://openrouter.ai), add credits (minimum $5 recommended for testing), and create a key under **Keys**.

You can configure multiple providers and switch per task (agent/vision/text) via environment variables — see Step 5 below.

### ✅ AI Provider Complete
Your AI analysis service is ready.

---

## 📝 **5. Configure Environment Files**

After setting up all services, you'll configure these credentials in your VirtualPyTest environment files:

### Main Configuration (`.env`)
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

# AI Provider (pick one or more)
AI_AGENT_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
# Alternates:
# OPENROUTER_API_KEY=your-openrouter-api-key
# OPENAI_API_KEY=your-openai-api-key
# MINIMAX_API_KEY=your-minimax-api-key
# GOOGLE_API_KEY=your-google-api-key
#
# Local model server (provider "local" = any OpenAI-compatible endpoint on your network:
# Ollama, vLLM, llama.cpp, LM Studio, Colibri...). Keeps AI traffic in-house.
# AI_PROVIDER=local
# LOCAL_AI_BASE_URL=http://10.10.10.10:8000/v1     # Ollama: http://<host>:11434/v1
# LOCAL_AI_MODEL=qwen3:8b                          # vLLM: the HuggingFace id, e.g. Qwen/Qwen3-8B
# LOCAL_AI_API_KEY=                                # only if the server enforces one
# LOCAL_AI_TIMEOUT=300                             # seconds per request; local models are slow
```

### Host Configuration (`backend_host/src/.env`)
```bash
# Copy relevant credentials here for host services
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=<your-anon-key>
R2_ACCESS_KEY_ID=abc123...
R2_SECRET_ACCESS_KEY=xyz789...
# ... other host-specific settings
```

### Frontend Configuration (`frontend/.env`)
```bash
# Public keys only (never put secret keys in frontend)
VITE_SUPABASE_URL=https://your-project-id.supabase.co
VITE_SUPABASE_ANON_KEY=<your-anon-key>
```

---

## 💰 **Cost Estimation**

Here's what you can expect to spend:

| Service | Free Tier | Typical Monthly Cost |
|---------|-----------|---------------------|
| **Supabase** | 500MB DB, 1GB bandwidth | $0-25 (depending on usage) |
| **Cloudflare R2** | 10GB storage, 1M requests | $0-10 (pay per use) |
| **AI Provider** (Anthropic/OpenRouter/etc.) | Varies by provider | $5-50 (depending on AI usage) |
| **Upstash Redis** (optional/legacy) | 10K requests/day | $0-20 if used |

**Total estimated cost: $5-85/month** (most users spend $10-30/month; Redis is optional)

---

## 🔐 **Security Best Practices**

- **Never commit** API keys or secrets to version control
- **Use environment files** (`.env`) for all credentials
- **Rotate keys regularly** (every 3-6 months)
- **Use least-privilege access** - only grant necessary permissions
- **Monitor usage** - set up billing alerts for unexpected costs

---

## ✅ **Verification Checklist**

Before proceeding to VirtualPyTest installation, ensure you have:

- [ ] **Supabase project** created with URL and API keys
- [ ] **R2 bucket** created with access credentials
- [ ] **AI provider account** with API key (Anthropic recommended)
- [ ] **Upstash Redis** database with connection details (optional/legacy — skip if unused)
- [ ] **All credentials** saved securely for environment configuration

---

## 🆘 **Troubleshooting**

### Common Issues

**Supabase connection fails:**
- Verify project URL format: `https://your-project-id.supabase.co`
- Check if project is fully initialized (wait 2-3 minutes after creation)
- Ensure API keys are copied correctly (they're very long)

**R2 upload errors:**
- Verify bucket name is globally unique
- Check API token has correct permissions (Object Read and Write)
- Ensure Account ID is correct (found in R2 dashboard)

**Redis connection timeout (if you're using it):**
- Verify endpoint format matches your Upstash dashboard
- Check if database is in same region as your server
- Ensure the REST token is copied correctly

**AI provider errors:**
- Verify the API key matches the provider set in `AI_AGENT_PROVIDER` (or `AI_PROVIDER`)
- Check account has sufficient credits/quota
- Ensure model name is correct (case-sensitive) if overriding the default

### Getting Help

- **Supabase**: [docs.supabase.com](https://docs.supabase.com)
- **Cloudflare R2**: [developers.cloudflare.com/r2](https://developers.cloudflare.com/r2)
- **Anthropic**: [docs.anthropic.com](https://docs.anthropic.com)
- **OpenRouter**: [openrouter.ai/docs](https://openrouter.ai/docs)
- **Upstash** (optional/legacy): [docs.upstash.com](https://docs.upstash.com)

---

## 🎯 **Next Steps**

Once you've completed all requirements setup:

1. **Return to** [Getting Started Guide](getting-started.md)
2. **Continue with** the Quick Start installation
3. **Configure** your `.env` files with the credentials you just obtained

**🎉 Ready to install VirtualPyTest!**
