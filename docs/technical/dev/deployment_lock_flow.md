# Deployment Lock Indicator - Data Flow

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SUPABASE DATABASE                        │
├─────────────────────────────────────────────────────────────────┤
│  deployments                      deployment_executions          │
│  ├─ id                            ├─ id                         │
│  ├─ host_name                     ├─ deployment_id (FK)         │
│  ├─ device_id                     ├─ status: 'running'/'comp..  │
│  ├─ script_name                   ├─ started_at                 │
│  └─ cron_expression               └─ completed_at               │
└─────────────────────────────────────────────────────────────────┘
                           ▲                      │
                           │                      │
                    ┌──────┴──────────────────────▼──────────┐
                    │      DEPLOYMENT SCHEDULER              │
                    │   (deployment_scheduler.py)            │
                    │                                        │
                    │  • Creates 'running' execution         │
                    │  • Executes script                     │
                    │  • Updates to 'completed'/'failed'     │
                    └────────────────────────────────────────┘
                                     ▲
                                     │
                                     │
┌────────────────────────────────────┴───────────────────────────┐
│                          HOST SERVER                            │
├─────────────────────────────────────────────────────────────────┤
│  Every 10 seconds (send_ping_to_server):                        │
│                                                                  │
│  1. get_devices_with_running_deployments()                      │
│     ├─ Query deployments for this host                          │
│     ├─ Check deployment_executions.status = 'running'           │
│     └─ Return set of device_ids with active deployments         │
│                                                                  │
│  2. Build ping_data with deployment status                      │
│     devices: [                                                   │
│       {                                                          │
│         device_id: 'device1',                                    │
│         has_running_deployment: true  ← NEW FIELD               │
│       },                                                         │
│       { device_id: 'device2', has_running_deployment: false }   │
│     ]                                                            │
│                                                                  │
│  3. POST to /server/system/ping                                 │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     BACKEND SERVER                               │
├─────────────────────────────────────────────────────────────────┤
│  /server/system/ping endpoint:                                  │
│                                                                  │
│  update_host_ping(host_name, ping_data)                         │
│  └─ For each device in ping_data['devices']:                    │
│     └─ Update existing_device['has_running_deployment']         │
│                                                                  │
│  Host Registry (in-memory):                                     │
│  {                                                               │
│    'host1': {                                                    │
│      devices: [                                                  │
│        {                                                         │
│          device_id: 'device1',                                   │
│          has_running_deployment: true  ← STORED IN MEMORY       │
│        }                                                         │
│      ]                                                           │
│    }                                                             │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
├─────────────────────────────────────────────────────────────────┤
│  GET /server/system/getAllHosts                                 │
│  └─ Returns host data including has_running_deployment          │
│                                                                  │
│  HostManagerProvider updates context                            │
│  └─ All components receive updated device data                  │
│                                                                  │
│  RecHostPreview                 RecHostStreamModal              │
│  ┌─────────────────┐            ┌──────────────────┐           │
│  │ Device Name 🔒  │            │ Device - 🔒 Live │           │
│  │                 │            │                  │           │
│  │ [Video Stream]  │            │ [Full Stream]    │           │
│  └─────────────────┘            └──────────────────┘           │
│                                                                  │
│  Conditional Rendering:                                         │
│  {device?.has_running_deployment && <LockIcon />}               │
└─────────────────────────────────────────────────────────────────┘
```

## Timing Diagram

```
Time →
0s    10s   20s   30s   40s   50s   60s   70s   80s   90s
│     │     │     │     │     │     │     │     │     │
│     │     │     │     │     │     │     │     │     │
├─────┤ Deployment Starts                 ├─────┤ Ends
│     ▼                                   │     ▼
│     ┌─────────────────────────────────┐ │     
│     │  deployment_executions table:   │ │     
│     │  status = 'running'             │ │     
│     └─────────────────────────────────┘ │     
│                                         │     
├─────┬─────┬─────┬─────┬─────┬─────────┴─────┬─────┐
│Ping │Ping │Ping │Ping │Ping │Ping           │Ping │
▼     ▼     ▼     ▼     ▼     ▼               ▼     ▼
❌    🔒    🔒    🔒    🔒    🔒              ❌    ❌
No    Lock  Lock  Lock  Lock  Lock             No    No
lock  shown shown shown shown shown            lock  lock

Max 10s delay    │                             │ Max 10s delay
before shown     │                             │ before removed
                 │<──── Script Running ───────>│
```

## State Transitions

```
Device State Machine:

    ┌─────────────┐
    │   IDLE      │  has_running_deployment: false
    │  (no lock)  │
    └──────┬──────┘
           │
           │ Deployment starts
           │ (status='running' created)
           ▼
    ┌─────────────┐
    │  RUNNING    │  has_running_deployment: true
    │ (lock 🔒)   │
    └──────┬──────┘
           │
           │ Deployment completes
           │ (status='completed'/'failed')
           ▼
    ┌─────────────┐
    │   IDLE      │  has_running_deployment: false
    │  (no lock)  │
    └─────────────┘
```

## Query Performance

### Host Ping Query (every 10 seconds)
```sql
-- Step 1: Get deployments for host
SELECT id, device_id 
FROM deployments 
WHERE host_name = 'virtualhost'

-- Step 2: Check running executions
SELECT deployment_id 
FROM deployment_executions
WHERE deployment_id IN ('dep1', 'dep2', ...) 
  AND status = 'running'
```

**Performance Notes:**
- Index on `deployments.host_name` ✓
- Index on `deployment_executions.status` ✓
- Query runs once per host per 10 seconds
- Typically < 5ms execution time
- No impact on user experience

## Error Handling

```
┌────────────────────────────────────────┐
│ If Supabase query fails:               │
│ └─ Returns empty set                   │
│    └─ All devices show no lock         │
│       └─ No user-facing error          │
│          (graceful degradation)        │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│ If ping fails:                         │
│ └─ Status keeps last known state       │
│    └─ Lock persists until next success │
│       └─ Eventually marked 'offline'   │
└────────────────────────────────────────┘
```

## Key Design Decisions

1. **Pull Model**: Host actively queries for running deployments
   - ✅ Simple implementation
   - ✅ No websocket complexity
   - ✅ Works with existing ping system
   - ⚠️ 10-second max delay (acceptable)

2. **Memory Storage**: Server stores flag in-memory
   - ✅ Fast access
   - ✅ No additional DB queries from frontend
   - ⚠️ Rebuilds on server restart (acceptable - resolved in 10s)

3. **Visual Indicator**: Lock icon (not text/badge)
   - ✅ Universal symbol
   - ✅ Compact
   - ✅ Orange color (warning, not error)
   - ✅ Tooltip for clarity

4. **Update Frequency**: 10 seconds (existing ping rate)
   - ✅ No additional network overhead
   - ✅ Near real-time for human perception
   - ✅ Battery-friendly for mobile devices

