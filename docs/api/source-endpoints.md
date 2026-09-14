# Server System API - Source Endpoints

New endpoints added for source code management and deployment.

## Source Detection

### POST /server/system/source/detect

Detect source capabilities for a storage path (Git or non-Git).

**Request:**
```json
{
  "storage_path": "/mnt/shared/code/virtualpytest"
}
```

**Response:**
```json
{
  "success": true,
  "storage_path": "/mnt/shared/code/virtualpytest",
  "path_exists": true,
  "branches": ["main", "develop"],
  "is_git_repo": true,
  "branch": "main",
  "commit_hash": "abc123..."
}
```

### POST /server/system/source/git/branches

List available Git branches for the storage path.

**Request:**
```json
{
  "storage_path": "/mnt/shared/code/virtualpytest"
}
```

**Response:**
```json
{
  "success": true,
  "storage_path": "/mnt/shared/code/virtualpytest",
  "branches": ["main", "develop", "feature/xyz"],
  "current_branch": "main"
}
```

### POST /server/system/source/git/prepare

Prepare storage source from Git (checkout, pull, etc.).

**Request:**
```json
{
  "storage_path": "/mnt/shared/code/virtualpytest",
  "git_ref": "main",
  "pull_latest": true
}
```

### POST /server/system/source/zip/upload

Upload a ZIP archive for deployment.

**Request:** Multipart form data with `file` field containing the ZIP.

**Response:**
```json
{
  "success": true,
  "upload_id": "uuid...",
  "filename": "source.zip",
  "size_bytes": 12345
}
```

### POST /server/system/source/zip/validate

Validate an uploaded ZIP archive.

**Request:**
```json
{
  "upload_id": "uuid..."
}
```

### POST /server/system/source/zip/apply

Apply an uploaded ZIP to the target path.

**Request:**
```json
{
  "upload_id": "uuid...",
  "target_path": "/opt/virtualpytest"
}
```
