# Navigation Metrics Architecture

## Overview

VirtualPyTest's navigation metrics system provides comprehensive performance tracking for the embedded actions and verifications architecture. Metrics are automatically aggregated and updated in real-time through PostgreSQL triggers.

## Database Schema

### Aggregated Metrics Tables

#### `node_metrics` - Node Performance
Tracks aggregated performance for nodes with embedded verifications:

```sql
CREATE TABLE node_metrics (
    id uuid PRIMARY KEY,
    node_id varchar NOT NULL,
    tree_id uuid REFERENCES navigation_trees(id),
    team_id uuid REFERENCES teams(id),
    
    -- Execution metrics
    total_executions integer DEFAULT 0,
    successful_executions integer DEFAULT 0,
    failed_executions integer DEFAULT 0,
    success_rate numeric(5,4) DEFAULT 0.0,
    avg_execution_time_ms integer DEFAULT 0,
    min_execution_time_ms integer DEFAULT 0,
    max_execution_time_ms integer DEFAULT 0,
    
    -- Embedded verification tracking
    verification_count integer DEFAULT 0,
    verification_types jsonb DEFAULT '[]',
    
    -- Context
    last_execution_at timestamp,
    device_model varchar,
    device_id varchar,
    
    UNIQUE(node_id, tree_id, team_id)
);
```

#### `edge_metrics` - Edge Performance  
Tracks aggregated performance for edges with embedded actions:

```sql
CREATE TABLE edge_metrics (
    id uuid PRIMARY KEY,
    edge_id varchar NOT NULL,
    tree_id uuid REFERENCES navigation_trees(id),
    team_id uuid REFERENCES teams(id),
    
    -- Execution metrics
    total_executions integer DEFAULT 0,
    successful_executions integer DEFAULT 0,
    failed_executions integer DEFAULT 0,
    success_rate numeric(5,4) DEFAULT 0.0,
    avg_execution_time_ms integer DEFAULT 0,
    
    -- Embedded action tracking
    action_count integer DEFAULT 0,
    retry_action_count integer DEFAULT 0,

    action_types jsonb DEFAULT '[]',
    final_wait_time integer DEFAULT 2000,
    
    -- Retry metrics
    retry_execution_count integer DEFAULT 0,
    retry_success_count integer DEFAULT 0,
    retry_success_rate numeric(5,4) DEFAULT 0.0,
    
    -- Context
    last_execution_at timestamp,
    device_model varchar,
    device_id varchar,
    
    UNIQUE(edge_id, tree_id, team_id)
);
```

### Detailed History Tables

#### `action_execution_history` - Individual Action Records
```sql
CREATE TABLE action_execution_history (
    id uuid PRIMARY KEY,
    edge_id varchar NOT NULL,
    tree_id uuid REFERENCES navigation_trees(id),
    team_id uuid REFERENCES teams(id),
    
    -- Action details
    action_command varchar NOT NULL,
    action_params jsonb DEFAULT '{}',  -- Preserves wait_time
    action_index integer NOT NULL,
    is_retry_action boolean DEFAULT false,

    
    -- Results
    success boolean NOT NULL,
    execution_time_ms integer NOT NULL,
    error_message text,
    
    -- Context
    device_model varchar,
    host_name varchar,
    execution_id varchar,
    
    executed_at timestamp DEFAULT now()
);
```

#### `verification_execution_history` - Individual Verification Records
```sql
CREATE TABLE verification_execution_history (
    id uuid PRIMARY KEY,
    node_id varchar NOT NULL,
    tree_id uuid REFERENCES navigation_trees(id),
    team_id uuid REFERENCES teams(id),
    
    -- Verification details
    verification_type varchar NOT NULL,
    verification_command varchar NOT NULL,
    verification_params jsonb DEFAULT '{}',
    verification_index integer NOT NULL,
    
    -- Results
    success boolean NOT NULL,
    execution_time_ms integer NOT NULL,
    confidence_score numeric(5,4),
    threshold_used numeric(5,4),
    
    -- Artifacts
    source_image_url text,
    reference_image_url text,
    extracted_text text,
    
    -- Context
    device_model varchar,
    host_name varchar,
    execution_id varchar,
    
    executed_at timestamp DEFAULT now()
);
```

## Auto-Update System

### PostgreSQL Triggers
Metrics automatically update when executions are recorded:

```sql
-- Node metrics update on verification execution
CREATE TRIGGER trigger_update_node_metrics
    AFTER INSERT ON verification_execution_history
    FOR EACH ROW
    EXECUTE FUNCTION update_node_metrics_on_verification_execution();

-- Edge metrics update on action execution  
CREATE TRIGGER trigger_update_edge_metrics
    AFTER INSERT ON action_execution_history
    FOR EACH ROW
    EXECUTE FUNCTION update_edge_metrics_on_action_execution();
```

**Benefits:**
- Real-time updates
- Automatic consistency
- Zero maintenance overhead

## API Functions

### Recording Executions
```python
# Record individual action with full parameters
record_action_execution(
    team_id, tree_id, edge_id, action_command, action_params,
    action_index, is_retry_action, success, execution_time_ms,
    device_model, device_id, host_name
)

# Record individual verification with results
record_verification_execution(
    team_id, tree_id, node_id, verification_type, verification_command,
    verification_params, verification_index, success, execution_time_ms,
    confidence_score, source_image_url, extracted_text
)
```

### Querying Metrics
```python
# Get aggregated metrics for trees
get_tree_metrics(team_id, node_ids, edge_ids)
# Returns: {nodes: {node_id: metrics}, edges: {edge_id: metrics}}

# Get detailed execution history
get_action_execution_history(team_id, edge_id, tree_id, limit)
get_verification_execution_history(team_id, node_id, tree_id, limit)
```

### Embedded Metrics Updates
```python
# Update metrics based on embedded data analysis
update_node_metrics_from_embedded_verifications(team_id, tree_id, node_id, verifications)
update_edge_metrics_from_embedded_actions(team_id, tree_id, edge_id, actions, retry_actions)
```

## Frontend Integration

### Metrics Display
```typescript
interface UINavigationEdgeData {
  actions: EdgeAction[];
  metrics?: {
    volume: number;              // total_executions
    success_rate: number;        // success_rate (0.0-1.0)  
    avg_execution_time: number;  // avg_execution_time_ms
  };
}

interface UINavigationNodeData {
  verifications: NodeVerification[];
  metrics?: {
    volume: number;
    success_rate: number;
    avg_execution_time: number;
  };
}
```

### Metrics Loading
```typescript
// Load metrics with tree data
const treeData = await navigationConfig.loadFullTree(treeId);
const metrics = await get_tree_metrics(teamId, nodeIds, edgeIds);

// Merge metrics into tree data for display
nodes.forEach(node => {
  node.data.metrics = metrics.nodes[node.id];
});
edges.forEach(edge => {
  edge.data.metrics = metrics.edges[edge.id];
});
```

## Key Features

### Embedded Architecture Awareness
- **Action Count Tracking**: Knows how many actions are in each edge
- **Verification Count Tracking**: Knows how many verifications are in each node
- **Type Analysis**: Records action/verification types used
- **Parameter Preservation**: Full parameters including `wait_time` preserved

### Performance Intelligence
- **Success Patterns**: Detailed success rate tracking
- **Timing Analysis**: Min/max/average execution times
- **Retry Effectiveness**: Separate metrics for retry actions
- **Device Context**: Performance varies by device model

### Historical Analysis
- **Individual Records**: Every action/verification execution preserved
- **Parameter Impact**: Analyze how `wait_time` affects success rates
- **Confidence Tracking**: Verification confidence scores over time
- **Error Patterns**: Detailed error analysis for optimization

## Performance Benefits

### Real-Time Updates
- **Instant Metrics**: Triggers update metrics immediately
- **No Batch Processing**: No delay between execution and metrics
- **Always Current**: Metrics reflect latest executions

### Efficient Queries
- **Aggregated Data**: Fast access to summary metrics
- **Bulk Operations**: Load metrics for entire trees efficiently
- **Indexed Access**: Optimized queries with proper indexing

### Scalable Design
- **Large Trees**: Handles thousands of nodes/edges efficiently
- **Historical Data**: Detailed history without affecting performance
- **Device Scaling**: Metrics per device model for accurate analysis

The navigation metrics system provides unprecedented insight into navigation performance while maintaining the clean embedded architecture. 