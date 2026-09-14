# Timezone Management Documentation

## Current Timezone Issues ⚠️

### **Problem Identified**
The system has inconsistent timezone handling across different components, causing:
1. **2-hour time differences** between database timestamps and file timestamps
2. **Incorrect "Stuck Events" detection** - showing events as recent when they happened hours ago
3. **Uptime calculation confusion** - 3h uptime means process has been working for 3h, not stuck 3h ago

## **Current Timezone Usage**

### **Database Storage** 📊
```python
# system_metrics_db.py (Lines 26, 63)
'timestamp': datetime.now().isoformat()  # ❌ LOCAL system time (no timezone)
```

### **Screenshot Timestamps** 📸
```python
# base_controller.py (Line 312)
zurich_tz = pytz.timezone("Europe/Zurich")
zurich_time = now.astimezone(zurich_tz)  # ✅ Zurich timezone (UTC+1/+2)
```

### **File Modification Times** 📁
```python
# system_info_utils.py (Line 111, 119)
os.path.getmtime(f)  # ❌ System local time (Unix timestamp, usually UTC)
```

### **Some Database Tables** ✅
```python
# script_results_db.py (Line 40, 56)
'started_at': datetime.now(timezone.utc).isoformat()  # ✅ Correct UTC usage

# alerts_db.py (Line 234)
'start_time': datetime.now(timezone.utc).isoformat()  # ✅ Correct UTC usage
```

## **The 2-Hour Difference Explained**

1. **Database timestamps**: Stored in local system time (likely UTC)
2. **Screenshot filenames**: Created using Zurich time (UTC+2 in summer)
3. **File modification times**: Unix timestamps in UTC
4. **Grafana queries**: Expecting consistent timezone but getting mixed data

**Result**: When Grafana shows "17:02:01" for FFmpeg/Monitor last activity, but database timestamp is "15:02:01", there's a 2-hour offset.

## **Uptime vs Stuck Time Confusion**

### **Current Logic (INCORRECT)**
```
Device Metrics showing "3h uptime" means:
- Process has been WORKING for 3 hours
- NOT that it got stuck 3 hours ago
```

### **Stuck Events Logic (NEEDS FIX)**
The "Stuck Events History" panel shows:
- **Stuck Time**: When the transition from 'active' → 'stuck' happened
- **Working Duration**: How long it worked before getting stuck

**But the confusion is**:
- If current uptime is "3h" and status is "active" → Process is currently working fine
- If current uptime is "0m" and status is "stuck" → Process just got stuck
- If stuck event shows "17:02:02" but current time is "18:14:16" → Event happened 1h12m ago

## **Required Fixes**

### **1. Standardize Database Storage to UTC**
```python
# Fix system_metrics_db.py
'timestamp': datetime.now(timezone.utc).isoformat()
```

### **2. Convert File Timestamps to UTC**
```python
# Fix system_info_utils.py
from datetime import timezone
file_mtime_utc = datetime.fromtimestamp(os.path.getmtime(f), tz=timezone.utc)
```

### **3. Keep Zurich Time Only for Display**
```python
# base_controller.py - Keep for screenshot filenames (display purposes)
# But convert to UTC for any database storage
```

### **4. Fix Grafana Time Display**
- Ensure all Grafana queries use consistent UTC timestamps
- Configure Grafana to display times in Zurich timezone for user interface

## **Files Requiring Timezone Fixes**

### **High Priority** 🔴
1. `shared/src/lib/database/system_metrics_db.py` - Database storage
2. `backend_host/src/lib/utils/system_info_utils.py` - File timestamp handling
3. `shared/src/lib/database/heatmap_db.py` - Line 88 (datetime.now())

### **Medium Priority** 🟡
4. `backend_host/src/lib/utils/host_utils.py` - Host ping timestamps
5. `backend_server/src/routes/server_system_routes.py` - Server metrics
6. All other database files using `datetime.now()` without timezone

### **Low Priority** 🟢
7. `backend_host/src/controllers/base_controller.py` - Keep Zurich for filenames
8. Frontend display formatting

## **Implementation Strategy**

### **Phase 1: Database Standardization**
- Convert all `datetime.now()` to `datetime.now(timezone.utc)`
- Test system metrics collection

### **Phase 2: File Timestamp Conversion**
- Convert `os.path.getmtime()` results to UTC datetime objects
- Update uptime calculations

### **Phase 3: Grafana Configuration**
- Verify all queries use UTC timestamps
- Configure Grafana timezone display settings

### **Phase 4: Validation**
- Compare database timestamps with file timestamps
- Verify "Stuck Events" show correct times
- Confirm uptime calculations are logical

## **Expected Results After Fix**

1. **Consistent Timestamps**: All database entries in UTC
2. **Correct Time Display**: Grafana shows Zurich time consistently
3. **Accurate Stuck Detection**: Events show when they actually happened
4. **Clear Uptime Logic**: 
   - "3h uptime" = process working for 3 hours (good)
   - "0m uptime" + "stuck" status = just got stuck (bad)
   - Stuck events show actual transition times

## **Testing Checklist**

- [ ] Database timestamps match file timestamps (accounting for timezone)
- [ ] Grafana panels show consistent times
- [ ] Stuck events correspond to actual status changes
- [ ] Uptime calculations make logical sense
- [ ] Screenshot timestamps align with database entries
