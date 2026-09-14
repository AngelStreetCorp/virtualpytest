# Orchestrator Workflow Architecture

## Overview

All execution types (Navigation, Verifications, Actions, Standard Blocks, TestCases, Campaigns) follow a unified **async-first** architecture to prevent HTTP timeouts and enable long-running operations.

> Note: Frontend execution completion now primarily uses `/system` Socket.IO push events (`execution_update`).
> Legacy `/execution/{id}/status` endpoints still exist for compatibility and some server-side/MCP paths.
> Migration safety: keep legacy status endpoints as fallback until all clients are verified on push completion.

## Core Principles

1. **Async Execution**: All routes return `execution_id` immediately (<100ms)
2. **Background Processing**: Execution happens in daemon threads
3. **Push Completion**: Frontend waits for `/system` `execution_update` events by `execution_id`
4. **No Timeout Risk**: HTTP connections never wait for execution to complete

---

## Execution Flow (All Types)

```
Frontend
   ↓ POST /server/{type}/execute
Server (proxy layer)
   ↓ POST /host/{type}/execute
Host Route
   ├─ 1. Generate execution_id (UUID)
   ├─ 2. Store state in executor._executions[id]
   ├─ 3. Start background thread
   └─ 4. Return {"execution_id": "..."} immediately
   
Background Thread
   ├─ 5. Execute through ExecutionOrchestrator
   ├─ 6. Orchestrator wraps with LoggingManager (captures logs)
   ├─ 7. Domain executor performs actual work
   └─ 8. Update _executions[id] with result

Frontend Socket Wait
   ↓ subscribe /system
   ↓ receive execution_update (execution_id match)
   └─ Status: 'running' | 'completed' | 'failed' | 'error'
```

---

## 1. Navigation Execution

**Route**: `/host/navigation/execute/{tree_id}`

**Implementation**: `backend_host/src/routes/host_navigation_routes.py`

**Flow**:
```python
@host_navigation_bp.route('/execute/<tree_id>', methods=['POST'])
def navigation_execute(tree_id):
    # 1. Generate execution_id
    execution_id = str(uuid.uuid4())
    
    # 2. Store in NavigationExecutor._executions
    device.navigation_executor._executions[execution_id] = {
        'status': 'running',
        'tree_id': tree_id,
        'target_node_id': target_node_id,
        'start_time': time.time(),
        ...
    }
    
    # 3. Start background thread
    threading.Thread(
        target=_execute_navigation_thread,
        args=(device, execution_id, tree_id, ...)
    ).start()
    
    # 4. Return immediately
    return jsonify({'execution_id': execution_id})
```

**Background Thread**:
```python
def _execute_navigation_thread(device, execution_id, ...):
    # Execute through orchestrator
    result = ExecutionOrchestrator.execute_navigation(
        device=device,
        tree_id=tree_id,
        ...
    )
    
    # Update state
    device.navigation_executor._executions[execution_id] = {
        'status': 'completed',
        'result': result
    }
```

**Legacy Status Endpoint**: `/host/navigation/execution/{execution_id}/status`

---

## 2. Verification Execution

**Route**: `/host/verification/executeBatch`

**Implementation**: `backend_host/src/routes/host_verification_routes.py`

**Flow**: Same pattern as navigation

```python
@host_verification_bp.route('/executeBatch', methods=['POST'])
def verification_execute_batch():
    execution_id = str(uuid.uuid4())
    
    device.verification_executor._executions[execution_id] = {...}
    
    threading.Thread(target=_execute_verifications_thread, ...).start()
    
    return jsonify({'execution_id': execution_id})
```

**Legacy Status Endpoint**: `/host/verification/execution/{execution_id}/status`

---

## 3. Action Execution

**Route**: `/host/action/executeBatch`

**Implementation**: `backend_host/src/routes/host_actions_routes.py`

**Flow**: Same pattern as navigation

```python
@host_actions_bp.route('/executeBatch', methods=['POST'])
def action_execute_batch():
    execution_id = str(uuid.uuid4())
    
    device.action_executor._executions[execution_id] = {...}
    
    threading.Thread(target=_execute_actions_thread, ...).start()
    
    return jsonify({'execution_id': execution_id})
```

**Background Thread**:
```python
def _execute_actions_thread(device, execution_id, actions, ...):
    result = ExecutionOrchestrator.execute_actions(
        device=device,
        actions=actions,
        retry_actions=retry_actions,
        failure_actions=failure_actions,
        ...
    )
    
    device.action_executor._executions[execution_id] = {
        'status': 'completed',
        'result': result
    }
```

**Legacy Status Endpoint**: `/host/action/execution/{execution_id}/status`

---

## 4. Standard Block Execution

**Route**: `/host/builder/execute`

**Implementation**: `backend_host/src/routes/host_builder_routes.py`

**Flow**: Same pattern as navigation

```python
@host_builder_bp.route('/execute', methods=['POST'])
def execute_standard_block():
    execution_id = str(uuid.uuid4())
    
    device.standard_block_executor._executions[execution_id] = {...}
    
    threading.Thread(target=_execute_blocks_thread, ...).start()
    
    return jsonify({'execution_id': execution_id})
```

**Background Thread**:
```python
def _execute_blocks_thread(device, execution_id, blocks):
    result = ExecutionOrchestrator.execute_blocks(
        device=device,
        blocks=blocks,
        context=None
    )
    
    device.standard_block_executor._executions[execution_id] = {
        'status': 'completed',
        'result': result
    }
```

**Legacy Status Endpoint**: `/host/builder/execution/{execution_id}/status`

---

## 5. TestCase Execution

**Route**: `/host/testcase/execute`

**Implementation**: `backend_host/src/routes/host_testcase_routes.py`

**Flow**: Uses dedicated async method in TestCaseExecutor

```python
@host_testcase_bp.route('/execute', methods=['POST'])
def testcase_execute_direct():
    if async_execution:  # Always True
        result = executor.execute_testcase_from_graph_async(...)
        return jsonify(result)  # Contains execution_id
```

**Legacy Status Endpoint**: `/host/testcase/execution/{execution_id}/status`

---

## 6. Campaign Execution

**Route**: `/host/campaign/execute`

**Implementation**: `backend_host/src/routes/host_campaign_routes.py`

**Flow**: Manual threading in route

```python
@host_campaign_bp.route('/execute', methods=['POST'])
def execute_campaign():
    execution_id = str(uuid.uuid4())
    
    running_campaigns[execution_id] = {'status': 'running', ...}
    
    threading.Thread(
        target=execute_campaign_async,
        args=(campaign_config, execution_id, ...)
    ).start()
    
    return jsonify({'execution_id': execution_id})
```

**Legacy Status Endpoint**: `/host/campaign/execution/{execution_id}/status`

---

## ExecutionOrchestrator Role

**Location**: `backend_host/src/orchestrator/execution_orchestrator.py`

**Purpose**: Provides cross-cutting concerns (NOT async management)

### What ExecutionOrchestrator Does:
- ✅ **Log Capture**: Wraps execution with `LoggingManager.execute_with_logging()`
- ✅ **Unified Interface**: Standardized `execute_*()` methods for all types
- ✅ **Delegation**: Routes to domain executors (ActionExecutor, NavigationExecutor, etc.)

### What ExecutionOrchestrator Does NOT Do:
- ❌ Async execution (handled by routes with threading)
- ❌ execution_id generation (handled by routes)
- ❌ Frontend completion waiting (handled by socket listeners / fallback status endpoints)

### Example:
```python
@staticmethod
def execute_actions(device, actions, ...) -> Dict[str, Any]:
    def execute():
        return device.action_executor.execute_actions(...)
    
    # Wraps execution with log capture
    return LoggingManager.execute_with_logging(execute)
```

---

## State Management Pattern

All executors maintain execution state in `_executions` dict:

```python
# During initialization (in route)
if not hasattr(executor, '_executions'):
    executor._executions = {}
    executor._lock = threading.Lock()

# When starting execution
with executor._lock:
    executor._executions[execution_id] = {
        'execution_id': execution_id,
        'status': 'running',  # 'running' | 'completed' | 'error'
        'result': None,
        'error': None,
        'start_time': time.time(),
        'progress': 0,
        'message': 'Starting...'
    }

# When execution completes
with executor._lock:
    executor._executions[execution_id]['status'] = 'completed'
    executor._executions[execution_id]['result'] = result
    executor._executions[execution_id]['progress'] = 100
```

---

## Frontend Integration

**Location**: `frontend/src/hooks/actions/useAction.ts`

**Pattern** (same for all execution types):

```typescript
// 1. Start execution
const response = await fetch('/server/action/executeBatch', {
  method: 'POST',
  body: JSON.stringify({ actions, ... })
});

const { execution_id } = await response.json();

// 2. Wait for socket completion event
const event = await waitForExecutionSocketEvent(execution_id, ['action'], 180000);
if (event.status === 'completed') {
  return event.result;
}
throw new Error(event.error || 'Execution failed');
```

---

## Benefits of Async Architecture

### ✅ No HTTP Timeouts
- Routes return in <100ms
- Long operations (5-600s) run in background
- No connection blocking

### ✅ Scalability
- Multiple executions run concurrently
- Each in own daemon thread
- No connection pool exhaustion

### ✅ Monitoring
- Real-time progress updates
- Can implement cancellation
- Better error handling

### ✅ User Experience
- Immediate feedback (execution started)
- Progress indicators possible
- No frozen UI waiting for completion

---

## Execution Type Comparison

| Type | Typical Duration | Max Timeout | Route Pattern | Orchestrator Used |
|------|------------------|-------------|---------------|-------------------|
| Actions | 3-10s | 30s | Manual threading | ✅ Yes |
| Standard Blocks | 1-5s | 30s | Manual threading | ✅ Yes |
| Verifications | 1-5s | 30s | Manual threading | ✅ Yes |
| Navigation | 5-30s | 60s | Manual threading | ✅ Yes |
| TestCase | 30-300s | 600s | Executor method | ❌ No |
| Campaign | 300-3600s | 7200s | Manual threading | ❌ No |

---

## Key Takeaways

1. **All execution is async** - no synchronous blocking routes
2. **Routes handle threading** - ExecutionOrchestrator is just a logger wrapper
3. **Consistent pattern** - same flow across all execution types:
   - Generate `execution_id`
   - Start thread
   - Return immediately
   - Wait for push completion (`execution_update`)
4. **Compatibility fallback remains** - legacy status endpoints are still available during migration
5. **Frontend migration status** - major execution flows now use socket completion

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          FRONTEND                                │
│  useAction / useNavigation / useVerification hooks               │
│  - Send execution request                                        │
│  - Receive execution_id                                          │
│  - Wait for /system execution_update event                       │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP (non-blocking)
┌──────────────────────▼──────────────────────────────────────────┐
│                     SERVER (Proxy)                               │
│  /server/{type}/execute          → /host/{type}/execute         │
│  /server/{type}/execution/{id}/status → /host/{type}/...        │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTP (proxy)
┌──────────────────────▼──────────────────────────────────────────┐
│                      HOST (Async Routes)                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Route: Generate execution_id + Start Thread + Return     │  │
│  └─────────────────────┬─────────────────────────────────────┘  │
│                        │                                          │
│  ┌─────────────────────▼─────────────────────────────────────┐  │
│  │ Background Thread                                         │  │
│  │   ┌──────────────────────────────────────────────────┐   │  │
│  │   │ ExecutionOrchestrator (Log Wrapper)              │   │  │
│  │   │   ┌──────────────────────────────────────────┐   │   │  │
│  │   │   │ Domain Executor (Actual Work)            │   │   │  │
│  │   │   │  - ActionExecutor                        │   │   │  │
│  │   │   │  - NavigationExecutor                    │   │   │  │
│  │   │   │  - VerificationExecutor                  │   │   │  │
│  │   │   │  - StandardBlockExecutor                 │   │   │  │
│  │   │   └──────────────────────────────────────────┘   │   │  │
│  │   └──────────────────────────────────────────────────┘   │  │
│  │   Update executor._executions[id] with result            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Status Route: Read from executor._executions[id]               │
└──────────────────────────────────────────────────────────────────┘
```
