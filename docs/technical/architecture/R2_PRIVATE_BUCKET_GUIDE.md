# R2 Private Bucket with Pre-signed URLs - Implementation Guide

## 🎉 Implementation Complete!

Your codebase now supports **secure, authenticated access to private R2 buckets** using pre-signed URLs with Supabase authentication.

**Mode is AUTO-DETECTED from environment variables - zero code changes needed!**

---

## 🚀 Quick Start (TL;DR)

### Public Bucket (Current - Default)
```bash
# backend/.env
CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev

# frontend/.env
VITE_CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev
```
→ Uses direct public URLs (fast, no auth)

### Private Bucket (Secure)
```bash
# backend/.env
# Remove or comment out CLOUDFLARE_R2_PUBLIC_URL
# CLOUDFLARE_R2_PUBLIC_URL=

# frontend/.env
# Remove or comment out VITE_CLOUDFLARE_R2_PUBLIC_URL
# VITE_CLOUDFLARE_R2_PUBLIC_URL=
```
→ Uses signed URLs via backend (secure, requires Supabase login)

**That's it!** No code changes needed.

---

## 📋 What Was Implemented

### Backend (Python)

✅ **`shared/src/lib/utils/cloudflare_utils.py`**
- Added `is_public_mode()` - Check if public URL mode is enabled
- Added `get_file_url_or_path()` - Returns full URL (public) or path only (private)
- Added `generate_presigned_url()` - Generate single signed URL
- Added `generate_presigned_urls_batch()` - Generate multiple signed URLs efficiently
- Uses boto3's S3-compatible signature generation (no API calls, free operation)

✅ **`backend_server/src/routes/server_storage_routes.py`** (NEW FILE)
- `POST /server/storage/signed-url` - Single URL generation (Supabase auth required)
- `POST /server/storage/signed-urls-batch` - Batch URL generation
- `GET /server/storage/health` - Service health check
- All endpoints protected with `@require_user_auth` decorator

✅ **`backend_server/src/app.py`**
- Registered new storage routes blueprint

### Frontend (TypeScript/React)

✅ **`frontend/src/utils/infrastructure/cloudflareUtils.ts`**
- Auto-detects mode from `VITE_CLOUDFLARE_R2_PUBLIC_URL` env var
- `getR2Url()` - Get single URL (public or signed based on env)
- `getR2UrlsBatch()` - Get multiple URLs efficiently
- `extractR2Path()` - Extract path from full URL or return path as-is
- `isPublicMode()` / `isPrivateMode()` - Check current mode
- In-memory caching with auto-expiry handling

✅ **`frontend/src/hooks/storage/useR2Url.ts`** (NEW FILE)
- `useR2Url()` - React hook for single URL
- `useR2UrlsBatch()` - React hook for multiple URLs
- `useR2UrlFromExisting()` - Convert existing URL to signed
- Loading states, error handling, auto-refresh

✅ **`frontend/src/components/common/R2Image.tsx`** (NEW FILE)
- Reusable component that auto-handles R2 URLs
- Shows loading spinner, error states
- Works in both public and private mode

✅ **Updated Components**
- `Navigation_NavigationNode.tsx` - Node screenshots
- `Navigation_ActionNode.tsx` - Action node screenshots
- `NodeVerificationModal.tsx` - AI verification screenshots
- `AIGenerationModal.tsx` - AI exploration screenshots

---

## 🔄 Data Compatibility

### Existing Data Works!

**No migration needed!** The system handles both formats:

| Data in Database | Mode | What Happens |
|-----------------|------|--------------|
| `https://pub-xxx.r2.dev/captures/file.jpg` | Public | Used directly ✅ |
| `https://pub-xxx.r2.dev/captures/file.jpg` | Private | Path extracted → Signed URL generated ✅ |
| `captures/file.jpg` | Public | Public URL constructed ✅ |
| `captures/file.jpg` | Private | Signed URL generated ✅ |

### How It Works

```
DATABASE (unchanged)
┌─────────────────────────────────────────────────────┐
│ screenshot: "https://pub-xxx.r2.dev/captures/a.jpg" │  (old data)
│         OR "captures/a.jpg"                         │  (new data in private mode)
└─────────────────────────────────────────────────────┘
                         │
                         ▼
              extractR2Path()
                         │
                         ▼
              "captures/a.jpg"
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   PUBLIC MODE                       PRIVATE MODE
   (env var set)                    (env var not set)
        │                                 │
        ▼                                 ▼
Return direct URL                  Fetch signed URL
        │                                 │
        ▼                                 ▼
https://pub-xxx.r2.dev/         https://account.r2...
captures/a.jpg                  /captures/a.jpg?
                                X-Amz-Signature=...
        │                                 │
        └────────────────┬────────────────┘
                         │
                         ▼
              SAME FILE IN R2 BUCKET
```

---

## 🚀 How to Use

### Mode is Controlled by Environment Variables

**BOTH backend and frontend need matching configuration:**

| Component | Env Var | What It Controls |
|-----------|---------|------------------|
| Backend | `CLOUDFLARE_R2_PUBLIC_URL` | What gets stored in DB (URL vs path) |
| Frontend | `VITE_CLOUDFLARE_R2_PUBLIC_URL` | How URLs are generated for display |

| Env Vars | Mode | Description |
|----------|------|-------------|
| **Both Set** | PUBLIC | Direct URLs, no auth, fast |
| **Both Not Set** | PRIVATE | Signed URLs via backend, requires Supabase auth |

---

### Scenario 1: Keep Public Bucket (Default)

**No changes needed!** Just ensure your env files have:

```bash
# backend/.env
CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev

# frontend/.env
VITE_CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev
```

The console will show:
```
[@utils:cloudflareUtils] 🔓 PUBLIC mode - Using direct URLs from: https://pub-xxxxx.r2.dev
```

---

### Scenario 2: Switch to Private Bucket

**Step 1: Remove env vars from both backend and frontend**

```bash
# backend/.env
# Comment out or remove to enable private mode
# CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev

# frontend/.env  
# Comment out or remove to enable private mode
# VITE_CLOUDFLARE_R2_PUBLIC_URL=https://pub-xxxxx.r2.dev
```

**Step 2: Restart both servers**

The console will show:
```
[@utils:cloudflareUtils] 🔐 PRIVATE mode - Using signed URLs (VITE_CLOUDFLARE_R2_PUBLIC_URL not set)
```

**Step 3: Make R2 bucket private in Cloudflare Dashboard**

1. Go to Cloudflare Dashboard → R2
2. Select your `virtualpytest` bucket
3. Settings → Public Access → **Disable**
4. Save

**That's it!** ✅ All file access now requires Supabase authentication.

---

## 🖼️ Using R2Image Component

For displaying R2 images with automatic mode handling:

```typescript
import { R2Image } from '@/components/common/R2Image';

// Simple usage
<R2Image src="captures/screenshot.jpg" alt="Screenshot" />

// With existing URL from database
<R2Image src={node.data.screenshot} alt="Node screenshot" />

// With custom styling
<R2Image 
  src={data.screenshot_url}
  alt="Verification"
  sx={{ maxHeight: 400, borderRadius: 1 }}
/>

// Without loading spinner
<R2Image src={path} showLoading={false} />
```

---

## 🪝 Using Hooks Directly

For more control, use the hooks:

**Single Image:**
```typescript
import { useR2Url } from '@/hooks/storage/useR2Url';

function MyComponent({ imagePath }: { imagePath: string }) {
  const { url, loading, error } = useR2Url(imagePath);

  if (loading) return <Spinner />;
  if (error) return <div>Error: {error}</div>;
  if (!url) return null;

  return <img src={url} alt="Capture" />;
}
```

**Multiple Images (Batch - More Efficient):**
```typescript
import { useR2UrlsBatch } from '@/hooks/storage/useR2Url';

function GalleryComponent({ imagePaths }: { imagePaths: string[] }) {
  const { urls, loading, error } = useR2UrlsBatch(imagePaths);

  if (loading) return <Spinner />;

  return (
    <div className="gallery">
      {urls.map((url, index) => (
        url && <img key={index} src={url} alt={`Image ${index}`} />
      ))}
    </div>
  );
}
```

---

## 🔐 Security Features

### Authentication Flow

```
User Login (Supabase)
  ↓
Get JWT Token
  ↓
Frontend: Call /server/storage/signed-url (with JWT)
  ↓
Backend: Validate JWT
  ↓
Backend: Generate signed URL (cryptographic signature)
  ↓
Frontend: Receive temporary URL (expires in 1 hour)
  ↓
Browser: Access R2 directly (R2 validates signature)
```

### What's Protected

✅ **Authentication Required**: Must have valid Supabase account
✅ **Time-Limited**: URLs expire (default: 1 hour, configurable)
✅ **Auditable**: Backend logs who requested what file
✅ **Revocable**: Disable user → no new URLs generated
✅ **Role-Based**: Can restrict by user role (admin, tester, viewer)

---

## 📊 Performance & Cost

### Performance

**Public Bucket**:
- Direct browser → R2 access
- Latency: ~50-200ms (CDN)

**Private Bucket with Signed URLs**:
- Browser → Backend API → Generate URL (local, no R2 call)
- Browser → R2 (direct access with signed URL)
- First load latency: +100-300ms (API call)
- Cached loads: Same as public (no API call)

### Cost

**Cloudflare R2 Pricing**:
- Storage: $0.015/GB/month (unchanged)
- Class B operations (GET): **FREE** ✅
- `generate_presigned_url()`: **Local operation (FREE)** ✅

**No extra cost for signed URLs!** 🎉

---

## 🔄 Migration Path

**Simple 3-step process:**

### Step 1: Test in Development

1. ✅ Comment out env vars in both `backend/.env` and `frontend/.env`
2. ✅ Restart both servers
3. ✅ Check console shows: `🔐 PRIVATE mode - Using signed URLs`
4. ✅ Test that images/files still load (via signed URLs)
5. ✅ Bucket is still public, but you're testing signed URL flow

### Step 2: Go Live

1. ✅ Update production env files - remove both `CLOUDFLARE_R2_PUBLIC_URL` vars
2. ✅ Deploy backend and frontend
3. ✅ Make bucket **private** in Cloudflare dashboard
4. 🎉 Done! All file access now requires authentication

### Step 3: Rollback (if needed)

- Add both env vars back
- Make bucket public again
- Instant rollback, no code changes

---

## 🐛 Troubleshooting

### Check Current Mode

Open browser console and look for:
```
[@utils:cloudflareUtils] 🔓 PUBLIC mode - Using direct URLs from: https://...
```
or
```
[@utils:cloudflareUtils] 🔐 PRIVATE mode - Using signed URLs (VITE_CLOUDFLARE_R2_PUBLIC_URL not set)
```

### Error: "Authentication required" (401)

**Cause**: In private mode but user not logged in

**Fix**:
- Ensure user is logged in to Supabase
- Check `supabase.auth.getSession()` returns valid session
- Private mode requires authentication for ALL file access

### Error: "Failed to generate signed URL"

**Cause**: Backend R2 credentials not configured

**Fix**:
- Check backend `.env` has:
  - `CLOUDFLARE_R2_ENDPOINT`
  - `CLOUDFLARE_R2_ACCESS_KEY_ID`
  - `CLOUDFLARE_R2_SECRET_ACCESS_KEY`
- Restart backend server

### URLs Return 403 Forbidden

**Cause**: Bucket is private but using public URLs

**Fix**:
- Check env var is NOT set in frontend
- Verify console shows `🔐 PRIVATE mode`
- If console shows `🔓 PUBLIC mode`, the env var is still set

### Images Not Loading in Private Mode

**Cause**: User not authenticated or token expired

**Fix**:
- Check user is logged in
- Check Supabase session is valid
- Try logging out and back in

---

## 📄 Test Reports & Logs

Reports and logs are also stored in R2 and automatically work with both public and private modes.

### How It Works

1. **Backend Uploads** (`report_utils.py`):
   - Uploads HTML reports to R2
   - Uploads execution logs to R2
   - Returns URL or path (depending on mode)

2. **Database Storage**:
   - Stores the URL/path in `html_report_r2_url`
   - Same field works for both modes

3. **Frontend Display** (`TestReports.tsx`, `RunTests.tsx`):
   - User clicks "View Report" or "Logs"
   - Frontend calls `handleOpenR2Url(url)`
   - Automatically generates signed URL if private mode
   - Opens in new browser tab

### Example Flow (Private Mode)

```typescript
// User clicks "View Report"
onClick={() => handleOpenR2Url(result.html_report_r2_url)}

// handleOpenR2Url implementation:
const handleOpenR2Url = async (url: string) => {
  // Extract path from full public URL stored in database
  let path = url;
  if (isCloudflareR2Url(url)) {
    const extracted = extractR2Path(url);
    if (extracted) path = extracted;
  }
  
  // getR2Url detects mode and generates signed URL if needed
  const signedUrl = await getR2Url(path);  
  window.open(signedUrl, '_blank');
};
```

**Database stores full public URLs** (backward compatible):
- Old reports: `https://pub-xxx.r2.dev/script-reports/...` ✅ Works
- New reports (private mode): `script-reports/...` ✅ Works
- Path extraction handles both formats automatically

**No data migration needed** - existing reports continue to work! 🎉

### Files Updated for Report/Log Links

All pages that display R2 report/log URLs have been updated:

**Reports & Logs:**
✅ **TestReports.tsx** - Script execution reports
✅ **RunTests.tsx** - Execution history table  
✅ **CampaignResultsList.tsx** - Campaign execution reports
✅ **HeatMapHistory.tsx** - Heatmap reports

**Screenshots & Images:**
✅ **Navigation_NavigationNode.tsx** - Node screenshots  
✅ **Navigation_ActionNode.tsx** - Action screenshots
✅ **NodeVerificationModal.tsx** - AI verification screenshots
✅ **AIGenerationModal.tsx** - AI exploration screenshots
✅ **HeatMapFreezeModal.tsx** - Freeze detection thumbnails (uses `useR2UrlsBatch`)
✅ **MosaicPlayer.tsx** - Heatmap mosaic images (uses `useR2Url`)
✅ **R2Image.tsx** - Reusable image component

All use the same pattern:
```typescript
const handleOpenR2Url = async (url: string) => {
  let path = url;
  if (isCloudflareR2Url(url)) {
    const extracted = extractR2Path(url);
    if (extracted) path = extracted;
  }
  const signedUrl = await getR2Url(path);
  window.open(signedUrl, '_blank');
};
```

---

## 📚 API Reference

### Backend API

#### POST `/server/storage/signed-url`

Generate a pre-signed URL for a single file.

**Headers**:
- `Authorization: Bearer <supabase-jwt>` (required)

**Request Body**:
```json
{
  "path": "captures/device1/capture_123.jpg",
  "expires_in": 3600
}
```

**Response**:
```json
{
  "success": true,
  "url": "https://account.r2.cloudflarestorage.com/...?X-Amz-Signature=...",
  "expires_in": 3600,
  "expires_at": "2025-12-05T15:30:00Z",
  "path": "captures/device1/capture_123.jpg"
}
```

#### POST `/server/storage/signed-urls-batch`

Generate multiple pre-signed URLs.

**Request Body**:
```json
{
  "paths": ["file1.jpg", "file2.jpg", "file3.jpg"],
  "expires_in": 3600
}
```

**Response**:
```json
{
  "success": true,
  "urls": [
    {
      "path": "file1.jpg",
      "url": "https://...",
      "expires_at": "2025-12-05T15:30:00Z",
      "expires_in": 3600
    }
  ],
  "failed": [],
  "generated_count": 3,
  "failed_count": 0
}
```

---

## 📞 Support

If you encounter issues:
1. Check browser console for errors
2. Check backend logs for authentication failures
3. Verify R2 credentials are correct
4. Test with health check endpoint first

---

**Implementation completed**: ✅ All files created, no linter errors
**Security**: ✅ Supabase JWT authentication
**Performance**: ✅ Cached signed URLs, batch generation
**Cost**: ✅ No additional R2 charges
**Data Compatibility**: ✅ Works with existing and new data

Happy secure storage! 🔐
