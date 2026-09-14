"""
Exploration Context - Thread-safe context propagation through phases

This context flows through all exploration phases (0-3) carrying:
- Original user prompt (for context-aware decisions)
- Device capabilities (strategy, available elements)
- Progress state (completed items, current step)
- History (for error recovery and suggestions)

Architecture: Mutable state container (unlike dataclass immutability in docs)
Reason: Python executor needs mutable state for async updates
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, timezone


class ExplorationContext:
    """
    Context that flows through all exploration phases
    
    Lifecycle:
    1. Created in start_exploration() with user's original prompt
    2. Updated in Phase 0 (strategy detection)
    3. Updated in Phase 1 (analysis & planning)
    4. Updated in Phase 2 (incremental creation - per item)
    5. Finalized in Phase 3
    
    Usage:
        context = ExplorationContext(
            original_prompt="Automate Sauce Demo",
            tree_id="abc123",
            ...
        )
        
        # Phase 0 updates
        context.strategy = "click_with_selectors"
        context.available_elements = [...]
        
        # Phase 2 updates
        context.completed_items.append("Signup")
        context.add_step_result("create_Signup", result)
    """
    
    def __init__(
        self,
        original_prompt: str,
        tree_id: str,
        userinterface_name: str,
        device_model: str,
        device_id: str,
        host_name: str,
        team_id: str
    ):
        """
        Initialize exploration context
        
        Args:
            original_prompt: User's goal (e.g., "Automate Sauce Demo - signup, login")
            tree_id: Navigation tree ID
            userinterface_name: UI name (e.g., "sauce-demo")
            device_model: Device model (e.g., "android_mobile", "host", "android_tv")
            device_id: Device identifier
            host_name: Host name where device is connected
            team_id: Team ID
        """
        # Original request (immutable)
        self.original_prompt = original_prompt
        self.tree_id = tree_id
        self.userinterface_name = userinterface_name
        self.device_model = device_model
        self.device_id = device_id
        self.host_name = host_name
        self.team_id = team_id
        
        # Phase 0 results (set during Phase 0)
        self.strategy: Optional[str] = None  # click_with_selectors | click_with_text | dpad_with_screenshot
        self.has_dump_ui: bool = False
        self.available_elements: List[Dict] = []
        
        # Phase 1 results (set during Phase 1)
        self.predicted_items: List[str] = []
        self.item_selectors: Dict[str, Dict] = {}  # item -> {type, value, bounds}
        self.screenshot_url: Optional[str] = None
        self.menu_type: Optional[str] = None  # horizontal, vertical, grid
        
        # Phase 2 progress (updated during Phase 2)
        self.current_step: int = 0
        self.total_steps: int = 0
        self.completed_items: List[str] = []
        self.failed_items: List[Dict] = []
        
        # History (for error recovery)
        self.step_history: List[Dict] = []
        self.last_success: Optional[Dict] = None
        self.last_failure: Optional[Dict] = None
        
        # Metadata
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize context for API responses
        
        Returns:
            Dict representation of context (safe for JSON serialization)
        """
        return {
            # Original request
            'original_prompt': self.original_prompt,
            'tree_id': self.tree_id,
            'userinterface_name': self.userinterface_name,
            'device_model': self.device_model,
            'device_id': self.device_id,
            'host_name': self.host_name,
            'team_id': self.team_id,
            
            # Phase 0 results
            'strategy': self.strategy,
            'has_dump_ui': self.has_dump_ui,
            'available_elements': self.available_elements[:10] if self.available_elements else [],  # Limit for API response
            
            # Phase 1 results
            'predicted_items': self.predicted_items,
            'item_selectors': self.item_selectors,
            'screenshot_url': self.screenshot_url,
            'menu_type': self.menu_type,
            
            # Phase 2 progress
            'current_step': self.current_step,
            'total_steps': self.total_steps,
            'completed_items': self.completed_items,
            'failed_items': self.failed_items,
            
            # Metadata
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    def add_step_result(self, step_name: str, result: Dict) -> None:
        """
        Add step result to history (mutates in place)
        
        Args:
            step_name: Name of step (e.g., "phase0_detection", "create_Signup")
            result: Result dict with at least {'success': bool}
        """
        self.step_history.append({
            'step': step_name,
            'result': result,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        if result.get('success'):
            self.last_success = {
                'step': step_name,
                'result': result,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        else:
            self.last_failure = {
                'step': step_name,
                'result': result,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
        
        self.updated_at = datetime.now(timezone.utc).isoformat()
    
    def get_progress_percentage(self) -> float:
        """
        Get progress percentage (0-100)
        
        Returns:
            Progress percentage based on current_step/total_steps
        """
        if self.total_steps == 0:
            return 0.0
        return (self.current_step / self.total_steps) * 100
    
    def get_last_n_steps(self, n: int = 3) -> List[Dict]:
        """
        Get last N steps from history
        
        Args:
            n: Number of steps to retrieve (default: 3)
            
        Returns:
            Last N steps from step_history
        """
        return self.step_history[-n:] if len(self.step_history) >= n else self.step_history
    
    def is_phase_complete(self, phase: str) -> bool:
        """
        Check if a phase is complete
        
        Args:
            phase: Phase name ('phase0', 'phase1', 'phase2', 'phase3')
            
        Returns:
            True if phase completed successfully
        """
        phase_steps = [h for h in self.step_history if h['step'].startswith(phase)]
        if not phase_steps:
            return False
        
        # Check if last step for this phase was successful
        return phase_steps[-1]['result'].get('success', False)
    
    def get_context_summary(self) -> str:
        """
        Get human-readable context summary (for debugging/logging)
        
        Returns:
            Multi-line string summary of context
        """
        summary = f"""
ExplorationContext Summary:
{'='*60}
Goal: {self.original_prompt}
Device: {self.device_model} ({self.device_id})
Strategy: {self.strategy or 'Not determined'}
Progress: {self.current_step}/{self.total_steps} ({self.get_progress_percentage():.1f}%)
Completed: {len(self.completed_items)} items
Failed: {len(self.failed_items)} items
{'='*60}
"""
        return summary
    
    def __repr__(self) -> str:
        """String representation for debugging"""
        return f"<ExplorationContext tree={self.tree_id} strategy={self.strategy} progress={self.current_step}/{self.total_steps}>"


def create_exploration_context(
    original_prompt: str,
    tree_id: str,
    userinterface_name: str,
    device_model: str,
    device_id: str,
    host_name: str,
    team_id: str
) -> ExplorationContext:
    """
    Factory function to create exploration context
    
    Args:
        original_prompt: User's goal
        tree_id: Navigation tree ID
        userinterface_name: UI name
        device_model: Device model
        device_id: Device identifier
        host_name: Host name
        team_id: Team ID
        
    Returns:
        New ExplorationContext instance
    """
    return ExplorationContext(
        original_prompt=original_prompt,
        tree_id=tree_id,
        userinterface_name=userinterface_name,
        device_model=device_model,
        device_id=device_id,
        host_name=host_name,
        team_id=team_id
    )

