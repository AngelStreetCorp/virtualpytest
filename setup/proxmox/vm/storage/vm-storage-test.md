# VM Storage Test Results

## Proxmox Storage Test Results

**Script**: `setup/proxmox/vm/storage/test_storage.sh`

**Purpose**: Tests basic Storage VM setup - disk partitions, NFS services, exports configuration, and repository presence.

**Test Results**:

```
🧪 VirtualPyTest - Storage VM Verification Test
==============================================

💽 Testing Disk Partitions & Mounts...
✅ /data is mounted
   Mount: /dev/sdc1       2.0T   40G  2.0T   2% /data
✅ /shared is mounted
   Mount: /dev/sdb1       200G  4.0G  196G   2% /shared

🔗 Testing NFS Services...
✅ NFS server is running
✅ RPC bind is running

📋 NFS Exports Configuration per VM...
✅ /etc/exports exists
   Expected 3 exports, found 2
✅ Backend Server: /data IP/24 rw - OK
❌ Backend Host range: /data range/24 rw - KO
✅ All VMs: /shared network/24 ro - OK

Full exports configuration:
  - /data 10.10.x.31/24(rw,sync,no_subtree_check,no_root_squash)
  - /shared 10.10.x.0/24(ro,sync,no_subtree_check,no_root_squash)

📁 Testing Repository...
✅ Repository directory exists: /shared/code/virtualpytest
✅ Repository directory is not empty
✅ Repository has .git directory (confirmed git repo)

🌐 Network Configuration...
   Current IP addresses:
         inet 10.10.x.149/24 brd 10.10.x.255 scope global dynamic noprefixroute ens19
         inet 10.68.x.165/24 brd 10.68.x.255 scope global ens20

🔍 NFS Export Status...
   Local exports:
     Export list for 127.0.0.1:
     /shared 10.10.x.0/24
     /data   10.10.x.31/24

==============================================
❌ Storage VM verification FAILED
   1 critical issues found

📋 Summary:
   • Repository: OK
   • NFS Server: OK
   • Exports: WARNING
   • Data Mount: OK
   • Shared Mount: OK
```

## VirtualPyTest Storage Test Results

**Script**: `setup/local/linux/storage/test_storage.sh`

**Purpose**: Tests MinIO S3-compatible storage and Redis caching functionality.

**Test Results**:

```
🧪 VirtualPyTest - Testing Storage VM Components
   • MinIO (S3-compatible object storage)
   • Redis (caching and sessions)



🔍 Testing Redis...
✅ Redis service is UP
   Testing Redis list operations...
✅ Redis LPUSH successful
✅ Redis RPOP successful: item1
✅ Redis cleanup completed



🔍 Testing MinIO...
✅ MinIO bucket 'virtualpytest' is accessible
   Uploading test file...
✅ MinIO file upload successful
   Downloading and verifying test file...
✅ MinIO file download and verification successful
   Listing files in bucket...
✅ MinIO file listing successful
   Deleting test file...
✅ MinIO file deletion successful



✅ 🎉 All storage tests PASSED!
   • MinIO (S3-compatible storage) - UP and WORKING
   • Redis (caching) - UP and WORKING



💾 VirtualPyTest Storage VM is fully operational!
```