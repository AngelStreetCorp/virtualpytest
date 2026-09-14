# VirtualPyTest Database Setup

Complete database schema for VirtualPyTest Supabase database.

## 📁 Structure

```
setup/db/
├── schema/                    # SQL schema files (numbered, applied in order)
│   ├── 001_core_tables.sql           # Core tables (devices, campaigns, AI cache, zap results)
│   ├── 002_ui_navigation_tables.sql  # UI and navigation trees with nested support
│   ├── 003_test_execution_tables.sql # Test cases and results with AI features
│   ├── 004_actions_verifications.sql # Verification references
│   ├── 005_monitoring_analytics.sql  # Alerts and metrics
│   ├── 006_parent_node_sync_triggers.sql # Bidirectional parent↔subtree sync (label, screenshot, verifications)
│   ├── 007_system_monitoring_tables.sql  # System monitoring metrics
│   └── 0NN_*.sql                     # Subsequent feature migrations (AI cache, retention, RBAC, …)
└── README.md                  # This file
```

## 🚀 Quick Setup

### 1. Go to Supabase SQL Editor

1. Open your [Supabase Dashboard](https://app.supabase.com)
2. Select your project → **SQL Editor**
3. Click **New Query**

### 2. Execute Schema Files in Order

Copy and paste the contents of each SQL file **in order** and execute them:

#### Step 1: Core Tables
Copy and paste the entire contents of `001_core_tables.sql` and run it.

#### Step 2: UI & Navigation Tables  
Copy and paste the entire contents of `002_ui_navigation_tables.sql` and run it.

#### Step 3: Test Execution Tables
Copy and paste the entire contents of `003_test_execution_tables.sql` and run it.

#### Step 4: Actions & Verifications
Copy and paste the entire contents of `004_actions_verifications.sql` and run it.

#### Step 5: Monitoring & Analytics
Copy and paste the entire contents of `005_monitoring_analytics.sql` and run it.

#### Step 6: System Metrics (ALREADY CREATED)
✅ The `system_metrics` table has been automatically created via MCP Supabase server.

#### Step 7: Parent Node Sync Triggers
Copy and paste the entire contents of `007_parent_node_sync_triggers.sql` and run it.

#### Step 8: AI Plan Generation Cache
Copy and paste the entire contents of `008_ai_plan_generation.sql` and run it.

## ✅ Verification

After running all 8 schema files, verify your setup:

1. Go to **Database** → **Tables** in your Supabase dashboard
2. You should see **24+ tables** created
3. All tables should have the correct relationships and indexes

### Expected Tables:

**Core Tables:**
- `teams`, `device_models`, `device`, `environment_profiles`, `campaign_executions`, `ai_analysis_cache`, `zap_results`, `ai_plan_generation`

**UI & Navigation:**
- `userinterfaces`, `navigation_trees`, `navigation_nodes`, `navigation_edges`, `navigation_trees_history`

**Test Execution:**
- `test_cases`, `test_executions`, `test_results`, `execution_results`, `script_results`

**Verifications:**
- `verifications_references`

**Monitoring & Analytics:**
- `alerts`, `heatmaps`, `node_metrics`, `edge_metrics`, `system_metrics`

### Key Features:
- ✅ **Nested Navigation Trees**: Support for multi-level navigation with automatic parent-child sync
- ✅ **Bidirectional Edges**: Action sets for forward/reverse navigation paths
- ✅ **AI Test Generation**: AI analysis cache and test case generation support
- ✅ **AI Plan Caching**: Intelligent caching of successful AI-generated plans with performance metrics
- ✅ **Zap Results**: Detailed media analysis and monitoring data
- ✅ **System Monitoring**: Real-time host and server performance metrics
- ✅ **Automatic Triggers**: Parent node sync and edge label management

## 🛠️ Application Configuration

After database setup, update your application `.env` files with your Supabase credentials:

```bash
# Frontend: frontend/.env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key

# Backend: .env (project root), backend_host/.env  
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

## 📊 Schema Overview

The VirtualPyTest database schema supports:

- **Device Management**: Physical devices and their models
- **Test Automation**: Controllers and execution engines  
- **UI Testing**: Navigation trees and interface definitions
- **Test Execution**: Test cases, results, and campaign management
- **AI Plan Caching**: Intelligent storage and reuse of successful AI-generated plans
- **Monitoring**: Performance metrics, alerts, analytics, and system monitoring
- **Verification**: Reference data for automated testing

All tables include proper indexes, foreign key relationships, and are designed for high performance and scalability.

## 🔧 Database Functions

The schema includes several PostgreSQL functions for efficient operations:

### Alert Management Functions

#### `delete_all_alerts()`
Efficiently deletes all alerts from the database without returning data to the client.

**Usage:**
```sql
SELECT delete_all_alerts();
```

**Returns:**
```json
{
  "success": true,
  "deleted_count": 1234,
  "message": "Successfully deleted 1234 alerts"
}
```

**Why use this function?**
- Prevents timeout issues when deleting large datasets (79,000+ records)
- Executes entirely in PostgreSQL without network data transfer
- Returns only a summary instead of all deleted records
- Much faster than client-side deletion methods

**Python Usage:**
```python
from shared.src.lib.database.alerts_db import delete_all_alerts

result = delete_all_alerts()
if result['success']:
    print(f"Deleted {result['deleted_count']} alerts")
``` 