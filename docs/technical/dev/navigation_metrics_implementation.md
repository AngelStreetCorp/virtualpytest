# Navigation Metrics Implementation

## Overview

This document describes the implementation of the navigation metrics system in VirtualPyTest. The metrics system provides performance tracking for navigation nodes and edges, including execution statistics, success rates, and timing information. **The system supports hierarchical metrics** across nested trees (up to 5 levels deep) for comprehensive confidence tracking.

## Architecture

### Database Schema

The metrics system uses the following database tables:

- `node_metrics`: Aggregated metrics for nodes with embedded verifications
- `edge_metrics`: Aggregated metrics for edges with embedded actions
- `action_execution_history`: Detailed history of individual action executions
- `verification_execution_history`: Detailed history of individual verification executions

These tables are automatically updated through PostgreSQL triggers when new executions are recorded.

### API Endpoints

The metrics system exposes the following clean, architecture-compliant API endpoints:

- `GET /server/metrics/tree/<tree_id>`: Get metrics for all nodes and edges in a tree
- `GET /server/metrics/node/<node_id>/<tree_id>`: Get metrics for a specific node
- `GET /server/metrics/edge/<edge_id>/<tree_id>`: Get metrics for a specific edge
- `GET /server/metrics/history/actions/<edge_id>/<tree_id>`: Get execution history for actions in an edge
- `GET /server/metrics/history/verifications/<node_id>/<tree_id>`: Get execution history for verifications in a node

### Frontend Integration

The frontend uses these metrics in the following components:

- `Navigation_EdgeSelectionPanel`: Displays metrics for selected edges
- `Navigation_NodeSelectionPanel`: Displays metrics for selected nodes

## Implementation Details

### Backend Implementation

The metrics system is implemented in the following files:

- `shared/src/lib/database/navigation_metrics_db.py`: Clean database functions following the embedded architecture
- `backend_server/src/routes/server_metrics_routes.py`: Clean API endpoints with no legacy code

### Frontend Integration

The frontend integrates with the metrics system through the following hooks:

- `useMetrics`: Custom hook for fetching and managing metrics data
- `useNavigationEditor`: Integrates metrics into the navigation editor

## Usage

### Fetching Metrics

To fetch metrics for a tree (including all nested subtrees), use the following endpoint:

```
GET /server/metrics/tree/<tree_id>
```

**Hierarchical Behavior**: When `tree_id` is a root tree with nested subtrees, the API automatically:
1. Fetches the complete tree hierarchy using `get_complete_tree_hierarchy()`
2. Aggregates metrics from all trees in the hierarchy (root + all nested subtrees)
3. Returns unified metrics covering the entire navigation structure
4. Includes hierarchy information in the response

The response will include metrics for all nodes and edges in the tree:

```json
{
  "success": true,
  "nodes": {
    "node_id_1": {
      "volume": 10,
      "success_rate": 0.9,
      "avg_execution_time": 1500
    },
    "node_id_2": {
      "volume": 5,
      "success_rate": 0.8,
      "avg_execution_time": 2000
    }
  },
  "edges": {
    "edge_id_1": {
      "volume": 15,
      "success_rate": 0.85,
      "avg_execution_time": 1200,
      "retry_count": 3,
      "retry_success_rate": 0.67
    },
    "edge_id_2": {
      "volume": 8,
      "success_rate": 0.75,
      "avg_execution_time": 1800,
      "retry_count": 2,
      "retry_success_rate": 0.5
    }
  }
}
```

### Displaying Metrics

Metrics are displayed in the Navigation Editor when selecting nodes or edges. The metrics include:

- **Volume**: Total number of executions
- **Success Rate**: Percentage of successful executions
- **Average Execution Time**: Average time taken for execution

## Troubleshooting

### Common Issues

1. **Missing Metrics**: If metrics are not appearing in the UI, check the following:
   - Ensure the metrics API endpoints are properly registered in `app.py`
   - Verify that the database tables exist and contain data
   - Check the browser console for API errors

2. **Database Errors**: If you encounter database errors, check:
   - Database connection settings
   - Table schemas match the expected format
   - PostgreSQL triggers are properly configured

## Future Enhancements

1. **Real-time Metrics**: Implement WebSocket-based real-time metrics updates
2. **Metrics Dashboard**: Create a dedicated dashboard for navigation metrics
3. **Performance Optimization**: Optimize metrics queries for large navigation trees
4. **Metrics Export**: Add functionality to export metrics data for external analysis
