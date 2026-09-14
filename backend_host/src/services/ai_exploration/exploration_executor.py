"""
AI Exploration Executor - Device-bound singleton for exploration management

Architecture pattern: Same as NavigationExecutor
- One instance per device (created during device initialization)
- Persistent state across requests (no global session dict)
- Direct access to device controllers (av, remote, verification)
"""

import time
import threading
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

from backend_host.src.services.ai_exploration.exploration_engine import ExplorationEngine
from backend_host.src.services.ai_exploration.exploration_context import ExplorationContext, create_exploration_context
from backend_host.src.services.ai_exploration.node_generator import NodeGenerator
from shared.src.lib.database.navigation_trees_db import (
    save_node,
    save_nodes_batch,
    save_edge,
    get_node_by_id,
    get_edge_by_id,
    delete_node,
    delete_edge
)

# Phases imports
from backend_host.src.services.ai_exploration.phases.structure_creator import continue_exploration as phase2_continue
from backend_host.src.services.ai_exploration.phases.validation_runner import (
    start_validation as phase2_start_validation,
    validate_next_item as phase2_validate_next,
    execute_phase2_next_item as phase2_execute_next
)
from backend_host.src.services.ai_exploration.phases.verification_manager import (
    start_node_verification as phase2_start_verification,
    approve_node_verifications as phase2_approve_verifications
)
from backend_host.src.services.ai_exploration.phases.cleanup_manager import (
    finalize_structure as phase2_finalize,
    approve_generation as phase2_approve,
    cancel_exploration as phase2_cancel
)


class ExplorationExecutor:
    """
    Device-bound exploration executor (singleton per device).
    Manages AI exploration state and orchestrates ExplorationEngine.
    
    CRITICAL: Do not create instances directly! Use device.exploration_executor instead.
    Each device has a singleton ExplorationExecutor that preserves exploration state.
    """
    
    @classmethod
    def get_for_device(cls, device):
        """
        Factory method to get the device's existing ExplorationExecutor.
        
        RECOMMENDED: Use device.exploration_executor directly instead.
        
        Args:
            device: Device instance
            
        Returns:
            The device's existing ExplorationExecutor instance
            
        Raises:
            ValueError: If device doesn't have exploration_executor
        """
        if not hasattr(device, 'exploration_executor') or not device.exploration_executor:
            raise ValueError(f"Device {device.device_id} does not have ExplorationExecutor. "
                           "ExplorationExecutors are created during device initialization.")
        return device.exploration_executor
    
    def __init__(self, device, _from_device_init: bool = False):
        """Initialize ExplorationExecutor (should only be called during device init)"""
        # Warn if creating instance outside of device initialization
        if not _from_device_init:
            import traceback
            device_id = getattr(device, 'device_id', 'unknown')
            print(f"⚠️ [ExplorationExecutor] WARNING: Creating new ExplorationExecutor for {device_id}")
            print(f"⚠️ [ExplorationExecutor] This may cause state loss! Use device.exploration_executor instead.")
            print(f"⚠️ [ExplorationExecutor] Call stack:")
            for line in traceback.format_stack()[-3:-1]:
                print(f"⚠️ [ExplorationExecutor]   {line.strip()}")
        
        # Store device reference
        self.device = device
        self.host_name = getattr(device, 'host_name', None)
        self.device_id = getattr(device, 'device_id', None)
        self.device_model = getattr(device, 'device_model', None)
        
        # Persistent exploration state (replaces global _exploration_sessions dict)
        self.current_exploration_id: Optional[str] = None
        self.exploration_engine: Optional[ExplorationEngine] = None
        
        # ✅ NEW v2.0: Context instance
        self.context: Optional[ExplorationContext] = None
        
        self.exploration_state: Dict[str, Any] = {
            'status': 'idle',  # idle, exploring, awaiting_approval, structure_created, validating, validation_complete
            'phase': None,  # analysis, structure_creation, validation
            'tree_id': None,
            'team_id': None,
            'userinterface_name': None,
            'current_step': '',
            'progress': {
                'total_screens_found': 0,
                'screens_analyzed': 0,
                'nodes_proposed': 0,
                'edges_proposed': 0
            },
            'current_analysis': {
                'screen_name': '',
                'elements_found': [],
                'reasoning': '',
                'screenshot': None
            },
            'exploration_plan': None,
            'items_to_validate': [],
            'current_validation_index': 0,
            'target_to_node_map': {},
            'home_id': None,
            'nodes_created': [],
            'edges_created': [],
            'node_verification_data': [],
            'node_verification_suggestions': [],
            'started_at': None,
            'completed_at': None,
            'error': None
        }
        
        # Thread lock for concurrent access
        self._lock = threading.Lock()
        
        print(f"[@ExplorationExecutor] Initialized for device {device.device_id}")
    
    def start_exploration(self, tree_id: str, root_tree_id: str, userinterface_name: str, team_id: str, original_prompt: str = "", start_node: str = 'home') -> Dict[str, Any]:
        """
        Start AI exploration (Phase 0+1: Strategy Detection + Analysis)
        
        v2.0: Now accepts original_prompt for context-aware execution
        v2.1: Now accepts start_node for recursive exploration (depth 0, 1, 2...)
        v2.2: Now accepts root_tree_id for subtree pathfinding
        
        Args:
            tree_id: Navigation tree ID (may be a subtree)
            root_tree_id: Root tree ID for pathfinding (NEW in v2.2)
            userinterface_name: User interface name
            team_id: Team ID
            original_prompt: User's goal (NEW in v2.0)
            start_node: Node to start exploration from (NEW in v2.1, defaults to 'home')
            
        Returns:
            {
                'success': True,
                'exploration_id': 'uuid',
                'message': 'Exploration started'
            }
        """
        with self._lock:
            # Reset state for new exploration
            exploration_id = str(uuid4())
            self.current_exploration_id = exploration_id
            
            # ✅ NEW v2.0: Create context
            self.context = create_exploration_context(
                original_prompt=original_prompt or f"Explore {userinterface_name}",
                tree_id=tree_id,
                userinterface_name=userinterface_name,
                device_model=self.device_model,
                device_id=self.device_id,
                host_name=self.host_name,
                team_id=team_id
            )
            
            # Reset exploration state (keep for compatibility)
            self.exploration_state = {
                'status': 'starting',
                'phase': 'analysis',
                'tree_id': tree_id,
                'root_tree_id': root_tree_id,  # ✅ Store for validation pathfinding
                'team_id': team_id,
                'userinterface_name': userinterface_name,
                'current_step': 'Initializing exploration...',
                'progress': {
                    'total_screens_found': 0,
                    'screens_analyzed': 0,
                    'nodes_proposed': 0,
                    'edges_proposed': 0
                },
                'current_analysis': {
                    'screen_name': '',
                    'elements_found': [],
                    'reasoning': '',
                    'screenshot': None
                },
                'exploration_plan': None,
                'items_to_validate': [],
                'current_validation_index': 0,
                'target_to_node_map': {},
                'home_id': None,
                'start_node': start_node,
                'nodes_created': [],
                'edges_created': [],
                'started_at': datetime.now(timezone.utc).isoformat(),
                'completed_at': None,
                'error': None
            }
            
            print(f"[@ExplorationExecutor:start_exploration] Starting exploration {exploration_id}")
            print(f"  Tree: {tree_id}")
            print(f"  Device: {self.device_model} ({self.device_id})")
            print(f"  UI: {userinterface_name}")
            print(f"  Start node: {start_node}")
        
        # ✅ PRE-FLIGHT CHECK: Test navigation to start_node BEFORE starting exploration        
        # ✅ Pre-flight check: Verify start node exists (don't navigate - graph not loaded yet)
        print(f"\n[@ExplorationExecutor:start_exploration] 🔍 Pre-flight check: Verifying '{start_node}' node exists...")
        from shared.src.lib.database.navigation_trees_db import get_tree_nodes
        
        nodes_result = get_tree_nodes(tree_id, team_id)
        if not nodes_result.get('success'):
            error_msg = f"Failed to load tree nodes: {nodes_result.get('error')}"
            print(f"[@ExplorationExecutor:start_exploration] ❌ Pre-flight check FAILED: {error_msg}")
            
            with self._lock:
                self.exploration_state['status'] = 'failed'
                self.exploration_state['error'] = error_msg
            
            return {
                'success': False,
                'error': f"Cannot start AI exploration: {error_msg}",
                'exploration_id': exploration_id
            }
            
        nodes = nodes_result.get('nodes', [])
        start_node_exists = any(n.get('label') == start_node for n in nodes)
        
        if not start_node_exists:
            error_msg = f"Start node '{start_node}' not found in tree"
            print(f"[@ExplorationExecutor:start_exploration] ❌ Pre-flight check FAILED: {error_msg}")
            
            with self._lock:
                self.exploration_state['status'] = 'failed'
                self.exploration_state['error'] = error_msg
            
            return {
                'success': False,
                'error': f"Cannot start AI exploration: {error_msg}.\n\n"
                        f"Action required: Ensure '{start_node}' node exists in the navigation tree.",
                'exploration_id': exploration_id
            }
        
        print(f"[@ExplorationExecutor:start_exploration] ✅ Pre-flight check PASSED: '{start_node}' node exists")
        
        # ✅ PHASE 0b: Load navigation tree
        print(f"\n[@ExplorationExecutor:start_exploration] 📥 PHASE 0b: Loading navigation tree...")
        try:
            result = self.device.navigation_executor.load_navigation_tree(
                userinterface_name=userinterface_name,
                team_id=team_id
            )
            if not result.get('success'):
                raise Exception(result.get('error', 'Unknown error'))
            print(f"[@ExplorationExecutor:start_exploration] ✅ Navigation tree loaded (with clean '{start_node}' node)")
        except Exception as e:
            error_msg = f"Failed to load navigation tree: {e}"
            print(f"[@ExplorationExecutor:start_exploration] ❌ {error_msg}")
            
            with self._lock:
                self.exploration_state['status'] = 'failed'
                self.exploration_state['error'] = error_msg
            
            return {
                'success': False,
                'error': f"Cannot start AI exploration: {error_msg}",
                'exploration_id': exploration_id
            }
        
        # ✅ PHASE 0c: Navigate to start_node BEFORE taking screenshot
        print(f"\n[@ExplorationExecutor:start_exploration] 📍 PHASE 0c: Navigating to start node '{start_node}'...")
        print(f"[@ExplorationExecutor:start_exploration] Using root_tree_id for pathfinding: {root_tree_id}")
        
        try:
            import asyncio
            nav_result = asyncio.run(self.device.navigation_executor.execute_navigation(
                tree_id=root_tree_id,  # ✅ FIX: Use root tree for pathfinding (not subtree!)
                userinterface_name=userinterface_name,
                target_node_label=start_node,
                team_id=team_id
            ))
            
            if not nav_result.get('success'):
                error_msg = nav_result.get('error', 'Unknown error')
                print(f"[@ExplorationExecutor:start_exploration] ❌ PHASE 0 FAILED: Cannot navigate to '{start_node}': {error_msg}")
                
                with self._lock:
                    self.exploration_state['status'] = 'failed'
                    self.exploration_state['error'] = f"Cannot navigate to start node '{start_node}': {error_msg}"
                
                return {
                    'success': False,
                    'error': f"Cannot start exploration: Failed to navigate to '{start_node}'.\n\n{error_msg}",
                    'exploration_id': exploration_id
                }
            
            print(f"[@ExplorationExecutor:start_exploration] ✅ PHASE 0 COMPLETE: At '{start_node}' - ready for screenshot")
            
        except Exception as e:
            error_msg = f"Navigation to '{start_node}' exception: {e}"
            print(f"[@ExplorationExecutor:start_exploration] ❌ {error_msg}")
            
            with self._lock:
                self.exploration_state['status'] = 'failed'
                self.exploration_state['error'] = error_msg
            
            return {
                'success': False,
                'error': f"Cannot start exploration: {error_msg}",
                'exploration_id': exploration_id
            }
        
        # Start exploration in background thread
        def run_exploration():
            try:
                # Check for immediate cancellation
                with self._lock:
                    if self.exploration_state.get('status') in ['idle', 'cancelled']:
                        print(f"[@ExplorationExecutor:run_exploration] ⚠️ Exploration cancelled at start")
                        return

                # Update state (acquire lock briefly)
                with self._lock:
                    self.exploration_state['status'] = 'exploring'
                    self.exploration_state['current_step'] = 'Capturing initial screenshot...'
                
                # Create exploration engine with callbacks
                def update_screenshot(screenshot_path: str):
                    """Upload screenshot to R2 (same as validation screenshots)"""
                    try:
                        from shared.src.lib.utils.cloudflare_utils import upload_navigation_screenshot
                        
                        # Upload to R2 (same as other navigation screenshots)
                        # ✅ FIX: Use start_node instead of hardcoded "home"
                        r2_filename = f"{start_node}_initial.jpg"
                        userinterface_name = self.exploration_state['userinterface_name']
                        upload_result = upload_navigation_screenshot(screenshot_path, userinterface_name, r2_filename)
                        
                        if upload_result.get('success'):
                            screenshot_url = upload_result.get('url')
                            print(f"[@ExplorationExecutor] Start node ({start_node}) screenshot uploaded to R2: {screenshot_url}")
                            
                            with self._lock:
                                self.exploration_state['current_analysis']['screenshot'] = screenshot_url
                        else:
                            print(f"[@ExplorationExecutor] Screenshot upload failed: {upload_result.get('error')}")
                    except Exception as e:
                        print(f"[@ExplorationExecutor] Screenshot upload failed: {e}")
                        import traceback
                        traceback.print_exc()
                
                def update_progress(step: str, screenshot: str = None, analysis: dict = None):
                    """Update progress (avoid nested lock acquisition)."""
                    screenshot_to_update = None
                    with self._lock:
                        self.exploration_state['current_step'] = step
                        
                        if analysis:
                            self.exploration_state['current_analysis'].update({
                                'screen_name': analysis.get('screen_name', ''),
                                'elements_found': analysis.get('elements_found', []),
                                'reasoning': analysis.get('reasoning', '')
                            })
                        
                        # Defer screenshot update outside the lock to avoid deadlock
                        if screenshot:
                            screenshot_to_update = screenshot
                    
                    if screenshot_to_update:
                        update_screenshot(screenshot_to_update)
                
                # Create or reuse engine
                def check_cancelled():
                    with self._lock:
                        return self.exploration_state.get('status') in ['idle', 'cancelled']

                self.exploration_engine = ExplorationEngine(
                    tree_id=tree_id,
                    device=self.device,  # Pass device directly (no Flask context needed!)
                    team_id=team_id,
                    userinterface_name=userinterface_name,
                    screenshot_callback=update_screenshot,
                    progress_callback=update_progress,
                    cancellation_check=check_cancelled
                )
                
                # Check for cancellation before starting analysis
                with self._lock:
                    if self.exploration_state.get('status') in ['idle', 'cancelled']:
                        print(f"[@ExplorationExecutor:run_exploration] ⚠️ Exploration cancelled before analysis")
                        return

                # Run Phase 1: Analysis
                result = self.exploration_engine.analyze_and_plan()
                
                with self._lock:
                    if result['success']:
                        self.exploration_state['status'] = 'awaiting_approval'
                        self.exploration_state['phase'] = 'analysis_complete'
                        self.exploration_state['current_step'] = 'Analysis complete. Review the plan below.'
                        self.exploration_state['exploration_plan'] = result['plan']
                        
                        # Preserve screenshot
                        existing_screenshot = self.exploration_state['current_analysis'].get('screenshot')
                        self.exploration_state['current_analysis'] = {
                            'screen_name': result['plan'].get('screen_name', 'Initial Screen'),
                            'elements_found': result['plan'].get('items', []),
                            'reasoning': result['plan'].get('reasoning', ''),
                            'screenshot': existing_screenshot
                        }
                    else:
                        error_msg = result.get('error', 'Failed to analyze screen')
                        print(f"[@ExplorationExecutor:run_exploration] ❌ EXPLORATION FAILED: {error_msg}")
                        self.exploration_state['status'] = 'failed'
                        self.exploration_state['error'] = error_msg
                        self.exploration_state['current_step'] = f"❌ Failed: {error_msg}"
                    
                    self.exploration_state['completed_at'] = datetime.now(timezone.utc).isoformat()
                
            except ValueError as ve:
                # Clean ValueError (no stack trace) - user-friendly message
                error_msg = str(ve)
                print(f"[@ExplorationExecutor:run_exploration] ⚠️ EXPLORATION STOPPED: {error_msg}")
                
                with self._lock:
                    self.exploration_state['status'] = 'failed'
                    self.exploration_state['error'] = error_msg
                    self.exploration_state['current_step'] = f"⚠️ {error_msg}"
                    self.exploration_state['completed_at'] = datetime.now(timezone.utc).isoformat()
                
            except Exception as e:
                print(f"[@ExplorationExecutor:run_exploration] Error: {e}")
                import traceback
                traceback.print_exc()
                
                with self._lock:
                    self.exploration_state['status'] = 'failed'
                    self.exploration_state['error'] = str(e)
                    self.exploration_state['current_step'] = f"Error: {str(e)}"
                    self.exploration_state['completed_at'] = datetime.now(timezone.utc).isoformat()
        
        # Start thread
        thread = threading.Thread(target=run_exploration, daemon=True)
        thread.start()
        
        return {
            'success': True,
            'exploration_id': exploration_id,
            'host_name': self.host_name,
            'message': 'Exploration started'
        }
    
    def get_exploration_status(self) -> Dict[str, Any]:
        """
        Get current exploration status (polling endpoint)
        
        Returns:
            {
                'success': True,
                'exploration_id': 'uuid',
                'status': 'exploring',
                'current_step': '...',
                'progress': {...},
                'exploration_plan': {...}
            }
        """
        with self._lock:
            if not self.current_exploration_id:
                return {
                    'success': False,
                    'error': 'No active exploration'
                }
            
            state = self.exploration_state.copy()
            
            return {
                'success': True,
                'exploration_id': self.current_exploration_id,
                'status': state['status'],
                'phase': state.get('phase'),
                'current_step': state['current_step'],
                'progress': state['progress'],
                'current_analysis': state['current_analysis'],
                'exploration_plan': state.get('exploration_plan'),
                'error': state.get('error')
            }
    
    def continue_exploration(self, team_id: str, selected_items: List[str] = None, selected_screen_items: List[str] = None, cleaned_lines: List[List[str]] = None, cleaned_duplicate_positions: List[str] = None) -> Dict[str, Any]:
        """
        Phase 2a: Create nodes and edges structure for selected items
        
        Args:
            team_id: Team ID
            selected_items: List of focus nodes to create
            selected_screen_items: List of screen nodes to create (TV only)
        
        Returns:
            {
                'success': True,
                'nodes_created': 11,
                'edges_created': 10
            }
        """
        # ✅ Update exploration_plan with cleaned data if provided (user edited AI response)
        if cleaned_lines is not None:
            self.exploration_state['exploration_plan']['lines'] = cleaned_lines
            self.exploration_state['exploration_plan']['items'] = [item for line in cleaned_lines for item in line]
        if cleaned_duplicate_positions is not None:
            self.exploration_state['exploration_plan']['duplicate_positions'] = cleaned_duplicate_positions
        
        return phase2_continue(self, team_id, selected_items, selected_screen_items)

    def start_validation(self) -> Dict[str, Any]:
        """
        Phase 2b: Start validation process
        
        Returns:
            {
                'success': True,
                'total_items': 10
            }
        """
        return phase2_start_validation(self)
    
    def finalize_structure(self) -> Dict[str, Any]:
        """
        Finalize structure: Rename all _temp nodes/edges to permanent
        
        Returns:
            {
                'success': True,
                'nodes_renamed': 5,
                'edges_renamed': 4
            }
        """
        return phase2_finalize(self)

    def validate_next_item(self) -> Dict[str, Any]:
        """
        Phase 2b: Validate edges sequentially (depth-first for TV dual-layer)
        
        TV Dual-Layer (depth-first):
          1. home → home_tvguide: RIGHT
          2. home_tvguide ↓ tvguide: OK (screenshot + dump)
          3. tvguide ↑ home_tvguide: BACK
          4. home_tvguide → home_apps: RIGHT
          5. home_apps ↓ apps: OK (screenshot + dump)
          6. apps ↑ home_apps: BACK
          ... (test complete cycle per item)
        
        Mobile/Web (single-layer):
          1. home → search: click (screenshot + dump)
          2. search → home: BACK
        
        Returns:
            TV: {'success': True, 'item': 'tvguide', 'edge_results': {...}, ...}
            Mobile/Web: {'success': True, 'item': 'Search', 'click_result': 'success', ...}
        """
        return phase2_validate_next(self)
    
    def approve_generation(self, tree_id: str, approved_nodes: list, approved_edges: list, team_id: str) -> Dict[str, Any]:
        """
        Approve generation - rename all _temp nodes/edges
        
        Returns:
            {
                'success': True,
                'nodes_created': 2,
                'edges_created': 1
            }
        """
        return phase2_approve(self, tree_id, approved_nodes, approved_edges, team_id)
    
    def cancel_exploration(self, tree_id: str, team_id: str) -> Dict[str, Any]:
        """
        Cancel exploration - delete all _temp nodes/edges
        
        Returns:
            {
                'success': True,
                'message': 'Exploration cancelled'
            }
        """
        return phase2_cancel(self, tree_id, team_id)
    
    def start_node_verification(self) -> Dict[str, Any]:
        """
        Phase 2c: Analyze dumps and suggest verifications
        
        Returns:
            {
                'success': True,
                'suggestions': [...],
                'total_nodes': 5
            }
        """
        return phase2_start_verification(self)
    
    def approve_node_verifications(self, approved_verifications: List[Dict], team_id: str) -> Dict[str, Any]:
        """
        Update nodes with approved verifications + screenshots
        
        Args:
            approved_verifications: [
                {
                    'node_id': 'search',
                    'verification': {
                        'text': 'TV Guide',  # For TV: text found by OCR
                        'area': {...},       # For TV: area where text was found
                        'command': 'waitForTextToAppear'  # Or from mobile/web analysis
                    },
                    'screenshot_url': '...'
                }
            ]
            
        Returns:
            {
                'success': True,
                'nodes_updated': 5,
                'references_created': 3  # TV only
            }
        """
        return phase2_approve_verifications(self, approved_verifications, team_id)
    
    # ========== NEW v2.0: MCP-FIRST INCREMENTAL METHODS ==========
    
    def execute_phase0(self) -> Dict[str, Any]:
        """
        Execute Phase 0: Strategy detection
        
        NEW in v2.0
        
        Returns:
            {
                'success': True,
                'strategy': str,
                'has_dump_ui': bool,
                'context': dict
            }
        """
        if not self.context:
            return {'success': False, 'error': 'No active exploration'}
        
        # Call engine Phase 0
        self.context = self.exploration_engine.phase0_detect_strategy(self.context)
        
        return {
            'success': True,
            'strategy': self.context.strategy,
            'has_dump_ui': self.context.has_dump_ui,
            'context': self.context.to_dict()
        }
    
    def execute_phase1(self) -> Dict[str, Any]:
        """
        Execute Phase 1: Analyze and plan (with sanitized labels)
        
        NEW in v2.0
        
        Returns:
            {
                'success': True,
                'predicted_items': List[str],  # SANITIZED labels
                'menu_type': str,
                'context': dict
            }
        """
        if not self.context:
            return {'success': False, 'error': 'No active exploration'}
        
        # Call engine Phase 1
        self.context = self.exploration_engine.phase1_analyze_and_plan(self.context)
        
        return {
            'success': True,
            'predicted_items': self.context.predicted_items,  # SANITIZED
            'menu_type': self.context.menu_type,
            'total_items': self.context.total_steps,
            'context': self.context.to_dict()
        }
    
    def execute_phase2_next_item(self) -> Dict[str, Any]:
        """
        Execute Phase 2: Create and test ONE edge incrementally
        
        NEW in v2.0: Incremental approach
        
        Returns:
            {
                'success': bool,
                'item': str,
                'has_more_items': bool,
                'progress': dict
            }
        """
        return phase2_execute_next(self)
    
    def auto_discover_screen(self, tree_id: str, team_id: str, userinterface_name: str, parent_node_id: str = 'home') -> Dict[str, Any]:
        """
        Auto-discover UI elements and create nodes/edges.
        
        SYNCHRONOUS: Waits for Phase 1 (analysis) to complete before creating nodes/edges.
        Uses SAME code as frontend: start_exploration() + continue_exploration()
        """
        import time
        
        print(f"[@ExplorationExecutor:auto_discover_screen] tree_id={tree_id}, parent={parent_node_id}")
        
        # Step 1: start_exploration() - starts background thread for Phase 1 analysis
        start_result = self.start_exploration(
            tree_id=tree_id,
            root_tree_id=tree_id,
            userinterface_name=userinterface_name,
            team_id=team_id,
            start_node=parent_node_id
        )
        
        if not start_result.get('success'):
            return {'success': False, 'error': start_result.get('error', 'start_exploration failed')}
        
        exploration_id = start_result.get('exploration_id')
        print(f"[@ExplorationExecutor:auto_discover_screen] Exploration started: {exploration_id}")
        
        # ✅ Step 2: WAIT for Phase 1 to complete (poll until 'awaiting_approval')
        print(f"[@ExplorationExecutor:auto_discover_screen] ⏳ Waiting for Phase 1 analysis to complete...")
        max_wait = 60  # 1 minutes timeout (generous for slow AI vision)
        start_time = time.time()
        poll_interval = 1  # Poll every 500ms
        
        exploration_plan = None
        while True:
            with self._lock:
                status = self.exploration_state.get('status')
                current_step = self.exploration_state.get('current_step', '')
                exploration_plan = self.exploration_state.get('exploration_plan')
                error = self.exploration_state.get('error')

                if status == 'awaiting_approval' and exploration_plan:
                    # ✅ Phase 1 complete!
                    print(f"[@ExplorationExecutor:auto_discover_screen] ✅ Phase 1 complete after {time.time() - start_time:.1f}s")
                    break
                elif status in ['idle', 'cancelled']:
                    # ❌ Exploration was cancelled
                    print(f"[@ExplorationExecutor:auto_discover_screen] ❌ Exploration cancelled (status: {status})")
                    return {'success': False, 'error': 'Exploration was cancelled by user'}
                elif status == 'failed':
                    print(f"[@ExplorationExecutor:auto_discover_screen] ❌ Phase 1 failed: {error}")
                    return {'success': False, 'error': error or 'Exploration failed during analysis'}
                elif time.time() - start_time > max_wait:
                    print(f"[@ExplorationExecutor:auto_discover_screen] ⏱️ Timeout after {max_wait}s (status: {status})")
                    return {'success': False, 'error': f'Timeout waiting for analysis (status: {status}, step: {current_step})'}
            
            # Print progress every 5 seconds
            if int(time.time() - start_time) % 5 == 0 and int(time.time() - start_time) > 0:
                elapsed = int(time.time() - start_time)
                if elapsed not in getattr(self, '_logged_intervals', set()):
                    if not hasattr(self, '_logged_intervals'):
                        self._logged_intervals = set()
                    self._logged_intervals.add(elapsed)
                    print(f"[@ExplorationExecutor:auto_discover_screen] ⏳ Still waiting... ({elapsed}s elapsed, status: {status}, step: {current_step[:50]})")
            
            time.sleep(poll_interval)
        
        # Reset logged intervals for next call
        if hasattr(self, '_logged_intervals'):
            delattr(self, '_logged_intervals')
        
        # ✅ Step 3: Extract elements from completed plan
        elements_found = exploration_plan.get('items', [])
        print(f"[@ExplorationExecutor:auto_discover_screen] Found {len(elements_found)} elements: {elements_found[:5]}{'...' if len(elements_found) > 5 else ''}")
        
        if not elements_found:
            print(f"[@ExplorationExecutor:auto_discover_screen] No elements found - returning early")
            return {'success': True, 'nodes_created': 0, 'edges_created': 0, 'elements_found': []}
        
        # ✅ Step 4: continue_exploration() - creates nodes/edges (Phase 2)
        print(f"[@ExplorationExecutor:auto_discover_screen] Starting Phase 2: Creating {len(elements_found)} nodes/edges...")
        continue_result = self.continue_exploration(
            team_id=team_id,
            selected_items=elements_found,
            selected_screen_items=elements_found
        )
        
        if not continue_result.get('success'):
            print(f"[@ExplorationExecutor:auto_discover_screen] ❌ Phase 2 failed: {continue_result.get('error')}")
            return {'success': False, 'error': continue_result.get('error', 'continue_exploration failed')}
        
        nodes_created = continue_result.get('nodes_created', 0)
        edges_created = continue_result.get('edges_created', 0)
        node_ids = continue_result.get('node_ids', [])
        edge_ids = continue_result.get('edge_ids', [])
        
        print(f"[@ExplorationExecutor:auto_discover_screen] ✅ Phase 2 complete: {nodes_created} nodes, {edges_created} edges")
        
        # ============================================================================
        # PHASE 3: Validate (same as frontend - just call existing methods, no duplication)
        # ============================================================================
        print(f"[@ExplorationExecutor:auto_discover_screen] Starting Phase 3: VALIDATION")
        
        validation_start = self.start_validation()  # Same as frontend calls
        if not validation_start.get('success'):
            return {
                'success': True,
                'nodes': node_ids,
                'edges': edge_ids,
                'validation': {'error': validation_start.get('error')}
            }
        
        # Same loop as frontend's pollValidation() - collect raw results, no processing
        validation_results = []
        while True:
            result = self.validate_next_item()  # Same as frontend calls
            if not result.get('success'):
                break
            validation_results.append(result)  # Raw result, same format frontend receives
            print(f"[@ExplorationExecutor:auto_discover_screen] Validated: {result.get('item')}")
            if not result.get('has_more_items', False):
                break
        
        print(f"[@ExplorationExecutor:auto_discover_screen] ✅ Complete: {len(validation_results)} items validated")
        
        return {
            'success': True,
            'nodes': node_ids,
            'edges': edge_ids,
            'validation_results': validation_results  # Raw results - AI reads directly
        }