"""
Node Generator - Naming convention + _temp suffix
Generates node and edge structures following user's naming rules
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4
import re
import unicodedata


class NodeGenerator:
    """Generate node/edge names following naming convention + _temp suffix"""
    
    def __init__(self, tree_id: str, team_id: str):
        self.tree_id = tree_id
        self.team_id = team_id
        self.node_counter = 0
        self.edge_counter = 0
    
    def target_to_node_name(self, target_text: str) -> str:
        """
        Convert navigation target to node name (UNIVERSAL algorithm)
        
        Navigation targets are EDGES (actions), node names are DESTINATIONS
        
        Examples:
        "TV Guide Tab" → "tv_guide"
        "Replay Register" → "replay"
        "Movies &amp; Series Tab" → "movies_series"
        "Watch. Button" → "watch"
        "Home Tab currently selected" → "home" (filtered later)
        "Aktuell gewählte Registerkarte TV Guide" → "tv_guide"
        
        Args:
            target_text: Text from clickable element (button, tab, menu item)
        
        Returns:
            Clean node name (without _temp suffix)
        """
        text = target_text.lower()
        
        # Decode HTML entities
        text = text.replace('&amp;', ' ')
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&lt;', ' ')
        text = text.replace('&gt;', ' ')
        
        # Remove common suffixes/prefixes
        remove_words = [
            'tab', 'register', 'button', 'screen', 'menu', 'page',
            'aktuell gewählte registerkarte',  # German: "currently selected tab"
            'currently selected',
            'doppeltippen zum öffnen',  # German: "double tap to open"
            'doppeltippen zum',
            'double tap to',
        ]
        
        for word in remove_words:
            text = text.replace(word, ' ')
        
        # Normalize accents: è→e, é→e, à→a, ñ→n, etc.
        text = unicodedata.normalize('NFD', text)
        text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
        
        # Replace special chars and multiple spaces with single underscore
        text = re.sub(r'[^a-z0-9]+', '_', text)
        
        # Remove consecutive underscores
        text = re.sub(r'_+', '_', text)
        
        # Strip leading/trailing underscores
        text = text.strip('_')
        
        return text if text else 'unknown'
        
    def generate_node_name(
        self,
        ai_suggestion: str,
        parent_node: Optional[str],
        context_visible: bool
    ) -> str:
        """
        Generate node name following convention + _temp
        
        Rules:
        1. If context_visible (horizontal nav): keep prefix
           Example: "home" + "settings" → "home_settings_temp"
           
        2. If new screen (entered): drop prefix  
           Example: "settings" → "settings_temp"
           
        3. If in subtree: use parent prefix
           Example: parent="settings", child="audio" → "settings_audio_temp"
        
        Args:
            ai_suggestion: AI-suggested name (e.g., "settings")
            parent_node: Parent node name (e.g., "home_temp")
            context_visible: True if previous menu still visible
            
        Returns:
            Final node name with _temp suffix
        """
        # Clean AI suggestion (remove spaces, lowercase, sanitize)
        clean_name = ai_suggestion.lower().replace(' ', '_').replace('-', '_')
        
        # Normalize accents: è→e, é→e, à→a, ñ→n, etc.
        clean_name = unicodedata.normalize('NFD', clean_name)
        clean_name = ''.join(char for char in clean_name if unicodedata.category(char) != 'Mn')
        
        # Keep only ASCII alphanumeric and underscores
        clean_name = ''.join(c for c in clean_name if c.isascii() and (c.isalnum() or c == '_'))
        
        # If no parent, this is root-level node
        if not parent_node:
            return f"{clean_name}_temp"
        
        # Remove _temp from parent to get base name
        parent_base = parent_node.replace('_temp', '')
        
        # If context visible (horizontal nav), keep parent prefix
        if context_visible:
            # Check if parent has underscore (is already prefixed)
            if '_' in parent_base:
                # Parent is like "home_settings", keep same level
                return f"{parent_base}_{clean_name}_temp"
            else:
                # Parent is like "home", add as child
                return f"{parent_base}_{clean_name}_temp"
        
        # New screen (entered) - drop prefix
        return f"{clean_name}_temp"
    
    def should_create_subtree(self, node_name: str, depth: int) -> bool:
        """
        Determine if this node should have a subtree
        
        Rules:
        - Node entered via OK (new screen) → create subtree
        - Node name has no underscore prefix → likely a main screen
        - Depth 1 from root → create subtree
        
        Args:
            node_name: Node name (with _temp)
            depth: Current depth in exploration
            
        Returns:
            True if subtree should be created
        """
        # Remove _temp to analyze base name
        base_name = node_name.replace('_temp', '')
        
        # If depth 1, create subtree for organization
        if depth == 1:
            return True
        
        # If name has no underscore, it's likely a main screen
        # Example: "settings_temp" (not "home_settings_temp")
        if '_' not in base_name:
            return True
        
        return False
    
    def create_node_data(
        self,
        node_name: str,
        position: Dict[str, int],
        ai_analysis: Dict,
        node_type: str = 'screen',
        is_root: bool = False,
        label: str = None
    ) -> Dict:
        """
        Create node data structure for save_node()
        
        Args:
            node_name: Node name (clean ID, e.g., 'en', 'search')
            position: {'x': 250, 'y': 250}
            ai_analysis: AI analysis result
            node_type: 'screen', 'menu', etc.
            is_root: False
            label: Optional label (if None, uses node_name). Pass with _temp for temporary nodes.
            
        Returns:
            Node data dict ready for save_node()
        """
        return {
            'node_id': node_name,
            'label': label if label is not None else node_name,
            'node_type': node_type,  # ✅ Use node_type, not type
            'position_x': position['x'],
            'position_y': position['y'],
            'data': {
                'type': node_type,  # Keep type in data for ReactFlow compatibility
                'is_root': is_root,
                'ai_generated': True,
                'ai_suggestion': ai_analysis.get('suggested_name', ''),
                'screen_type': ai_analysis.get('screen_type', 'screen'),
                'discovered_at': datetime.now(timezone.utc).isoformat(),
                'reasoning': ai_analysis.get('reasoning', '')
            },
            'style': {}
        }
    
    def create_edge_data(
        self,
        source: str,
        target: str,
        actions: List[Dict],
        reverse_actions: List[Dict] = None,
        label: str = ''
    ) -> Dict:
        """
        Create edge data structure for save_edge() with bidirectional support
        
        Args:
            source: Source node_id (clean, e.g., 'home')
            target: Target node_id (clean, e.g., 'search')
            actions: List of forward actions (source → target)
            reverse_actions: List of reverse actions (target → source), optional
            label: Optional custom label (can include _temp for display)
            
        Returns:
            Edge data dict ready for save_edge() with 2 action sets (bidirectional)
        """
        # Edge ID is clean (no _temp)
        edge_id = f"edge_{source}_to_{target}"
        
        # Clean labels for action_set_id (follow frontend convention)
        import re
        clean_source = re.sub(r'[^a-z0-9]', '_', source.lower())
        clean_target = re.sub(r'[^a-z0-9]', '_', target.lower())
        
        # Use same naming convention as frontend: {source}_to_{target}
        forward_action_set_id = f"{clean_source}_to_{clean_target}"
        reverse_action_set_id = f"{clean_target}_to_{clean_source}"
        
        # Build bidirectional action sets
        action_sets = [
            {
                'id': forward_action_set_id,
                'label': f"{source} → {target}",
                'actions': actions,
                'retry_actions': [],
                'failure_actions': []
            },
            {
                'id': reverse_action_set_id,
                'label': f"{target} → {source}",
                'actions': reverse_actions if reverse_actions else [],
                'retry_actions': [],
                'failure_actions': []
            }
        ]
        
        return {
            'edge_id': edge_id,
            'source_node_id': source,
            'target_node_id': target,
            'action_sets': action_sets,
            'default_action_set_id': forward_action_set_id,
            'label': label,  # Can have _temp for visual distinction
            'data': {
                # final_wait_time + threshold now live per-direction inside action_sets.
                'ai_generated': True,
                'discovered_at': datetime.now(timezone.utc).isoformat(),
                'sourceHandle': 'bottom-right-menu-source',  # ✅ Vertical edges: source at bottom
                'targetHandle': 'top-right-menu-target'      # ✅ Vertical edges: target at top
            }
        }
    
    def rename_node(self, node_data: Dict) -> Dict:
        """
        Remove _temp suffix from node data (for approval)
        
        Args:
            node_data: Original node data with _temp
            
        Returns:
            Node data with _temp removed
        """
        renamed = node_data.copy()
        renamed['node_id'] = renamed['node_id'].replace('_temp', '')
        renamed['label'] = renamed['label'].replace('_temp', '')
        return renamed
    
    def rename_edge(self, edge_data: Dict) -> Dict:
        """
        Remove _temp suffix from edge data (for approval)
        
        Args:
            edge_data: Original edge data with _temp
            
        Returns:
            Edge data with _temp removed
        """
        renamed = edge_data.copy()
        renamed['edge_id'] = renamed['edge_id'].replace('_temp', '')
        renamed['source_node_id'] = renamed['source_node_id'].replace('_temp', '')
        renamed['target_node_id'] = renamed['target_node_id'].replace('_temp', '')
        return renamed

