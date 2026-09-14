# Navigation Architecture Guide

## Overview

The VirtualPyTest navigation system has three distinct layers designed for different use cases. Understanding when to use each layer is crucial for maintainable and reliable scripts.

## Architecture Layers

### 1. **High-Level (Recommended for Most Scripts)**

**Use Case**: Simple navigation tasks, single-node navigation  
**Helper Function**: `navigate_to(target_node)`  
**Auto-Handles**: Tree loading, context setup, step recording, error handling  

```python
from shared.src.lib.executors.script_decorators import script, navigate_to

@script("goto", "Navigate to specified node")
def main():
    # One-line navigation - everything handled automatically
    return navigate_to("home")
```

**✅ Advantages:**
- Zero boilerplate - just specify target node
- Automatic tree loading and context setup
- Built-in error handling and step recording
- Consistent behavior across all scripts

**❌ Limitations:**
- Single navigation per call
- Limited customization of navigation behavior

**Used by**: `goto.py`, `goto_live.py`, `fullzap.py` (for initial navigation)

### 2. **Mid-Level (Manual Tree Management)**

**Use Case**: Scripts that need tree access but want automatic navigation  
**Helper Function**: `ensure_navigation_tree_loaded()` + `ScriptExecutor.navigate_to()`  
**Manual**: Tree loading verification, context validation  

```python
from shared.src.lib.executors.script_decorators import script, get_context, ensure_navigation_tree_loaded

@script("my_script", "Custom navigation logic")
def main():
    context = get_context()
    
    # Ensure tree is loaded for low-level operations
    if not ensure_navigation_tree_loaded():
        return False
    
    # Now safe to use context.tree_id, context.nodes, etc.
    # Custom logic here...
    
    return True
```

**✅ Advantages:**
- Access to tree data for complex logic
- Still handles tree loading automatically
- Better error messages for setup issues

**❌ Limitations:**
- More verbose than high-level
- Need to understand context management

**Used by**: `validation.py` (after refactoring)

### 3. **Low-Level (Expert/Complex Scenarios)**

**Use Case**: Complex validation, pathfinding, custom navigation algorithms  
**Direct Access**: Navigation services, pathfinding, cache functions  
**Manual**: Everything - tree loading, context setup, error handling  

```python
from backend_host.src.services.navigation.navigation_pathfinding import find_optimal_edge_validation_sequence
from backend_host.src.lib.utils.navigation_cache import get_cached_unified_graph

def complex_validation_logic():
    # MUST ensure tree is loaded first
    if not ensure_navigation_tree_loaded():
        return False
    
    context = get_context()
    
    # Now safe to use low-level functions
    unified_graph = get_cached_unified_graph(context.tree_id, context.team_id)
    validation_sequence = find_optimal_edge_validation_sequence(context.tree_id, context.team_id)
    
    # Custom complex logic...
```

**✅ Advantages:**
- Full control over navigation behavior
- Access to advanced pathfinding algorithms
- Can implement custom validation logic

**❌ Limitations:**
- Must handle all setup and error cases
- Easy to introduce bugs if setup is missed
- More complex to maintain

**Used by**: `validation.py` (complex validation logic), AI executors

## Decision Matrix

| Scenario | Recommended Layer | Rationale |
|----------|------------------|-----------|
| Navigate to single node | **High-Level** | Simple, reliable, zero boilerplate |
| Navigate + simple actions | **High-Level** | Use `navigate_to()` then custom logic |
| Need tree data for logic | **Mid-Level** | Use `ensure_navigation_tree_loaded()` |
| Complex pathfinding | **Low-Level** | Need direct access to navigation services |
| Validation sequences | **Low-Level** | Complex algorithms require full control |
| AI-driven navigation | **Low-Level** | Dynamic decision making needs full access |

## Error Handling Improvements

### Better Error Messages

Low-level functions now provide clear guidance when setup is missing:

```
❌ [@navigation:cache:get_cached_unified_graph] ERROR: root_tree_id is None!
💡 This usually means the navigation tree was not loaded properly.
💡 SOLUTION: Use navigate_to() helper or call load_navigation_tree() first
```

### Helper Function Validation

The `ensure_navigation_tree_loaded()` helper provides a safe way to use low-level functions:

```python
# Before (error-prone)
unified_graph = get_cached_unified_graph(context.tree_id, context.team_id)  # ❌ tree_id might be None

# After (safe)
if not ensure_navigation_tree_loaded():
    return False
unified_graph = get_cached_unified_graph(context.tree_id, context.team_id)  # ✅ tree_id guaranteed
```

## Migration Guide

### From Low-Level to High-Level

**Before:**
```python
# Manual tree loading + navigation
nav_result = context.selected_device.navigation_executor.load_navigation_tree(...)
context.tree_id = nav_result['tree_id']
navigation_result = context.selected_device.navigation_executor.execute_navigation(...)
```

**After:**
```python
# One-line navigation
success = navigate_to("target_node")
```

### From Manual Setup to Helper

**Before:**
```python
# Manual tree loading for low-level operations
nav_result = context.selected_device.navigation_executor.load_navigation_tree(...)
if not nav_result['success']:
    context.error_message = f"Navigation tree loading failed: {nav_result.get('error')}"
    return False
context.tree_id = nav_result['tree_id']
# ... more setup code ...
```

**After:**
```python
# Helper function handles all setup
if not ensure_navigation_tree_loaded():
    return False
# Ready to use low-level functions safely
```

## Best Practices

### ✅ Do This

1. **Start with High-Level**: Use `navigate_to()` unless you need tree data
2. **Use Helper for Low-Level**: Call `ensure_navigation_tree_loaded()` before low-level operations
3. **Fail Fast**: Return early on setup failures rather than continuing with None values
4. **Clear Error Messages**: Let the improved error messages guide users to solutions

### ❌ Avoid This

1. **Don't Mix Layers Unnecessarily**: If `navigate_to()` works, don't use low-level functions
2. **Don't Skip Setup Validation**: Always ensure tree is loaded before low-level operations
3. **Don't Ignore Helper Functions**: Use `ensure_navigation_tree_loaded()` instead of manual setup
4. **Don't Create New Patterns**: Follow the established three-layer architecture

## Examples

### Simple Navigation Script
```python
@script("goto_settings", "Navigate to settings")
def main():
    return navigate_to("settings")  # High-level - recommended
```

### Navigation + Custom Logic
```python
@script("custom_flow", "Navigate then do custom actions")
def main():
    # High-level navigation first
    if not navigate_to("live"):
        return False
    
    # Custom logic after navigation
    context = get_context()
    # ... custom actions ...
    return True
```

### Complex Validation Script
```python
@script("validation", "Validate navigation tree")
def main():
    # Ensure tree loaded for low-level operations
    if not ensure_navigation_tree_loaded():
        return False
    
    context = get_context()
    
    # Now safe to use low-level functions
    unified_graph = get_cached_unified_graph(context.tree_id, context.team_id)
    validation_sequence = find_optimal_edge_validation_sequence(context.tree_id, context.team_id)
    
    # Complex validation logic...
    return execute_validation_sequence(validation_sequence)
```

## Summary

- **High-Level (`navigate_to()`)**: Use for 90% of navigation needs
- **Mid-Level (`ensure_navigation_tree_loaded()`)**: Use when you need tree data
- **Low-Level (direct services)**: Use only for complex algorithms

The architecture provides clear separation of concerns while maintaining flexibility for advanced use cases. Always start with the highest level that meets your needs and only drop to lower levels when necessary.
