"""
TestCase Graph Validator

Validates test case graph structure before execution.
"""

from typing import Dict, List, Any, Tuple


class TestCaseValidator:
    """Validates test case graph structure"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_graph(self, graph: Dict[str, Any], userinterface_name: str = None, team_id: str = None) -> Tuple[bool, List[str], List[str]]:
        """
        Validate complete graph structure.
        
        Args:
            graph: {nodes: [...], edges: [...]}
            userinterface_name: Optional userinterface name for validation context
            team_id: Optional team ID for validation context
        
        Returns:
            (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []
        
        # Extract nodes and edges
        nodes = graph.get('nodes', [])
        edges = graph.get('edges', [])
        
        if not nodes:
            self.errors.append("Graph must contain at least one node")
            return False, self.errors, self.warnings
        
        # Validate basic structure
        self._validate_required_blocks(nodes)
        self._validate_node_structure(nodes)
        self._validate_edge_structure(edges, nodes)
        self._validate_connectivity(nodes, edges)
        self._validate_loop_blocks(nodes)
        self._validate_required_inputs(graph)
        
        is_valid = len(self.errors) == 0
        
        return is_valid, self.errors, self.warnings
    
    def _validate_required_blocks(self, nodes: List[Dict]):
        """Ensure required blocks exist"""
        block_types = {node.get('type') for node in nodes}
        
        # Must have exactly one START block
        start_count = sum(1 for node in nodes if node.get('type') == 'start')
        if start_count == 0:
            self.errors.append("Graph must contain exactly one START block")
        elif start_count > 1:
            self.errors.append(f"Graph must contain exactly one START block (found {start_count})")
        
        # Must have at least one terminal block (SUCCESS or FAILURE)
        has_terminal = 'success' in block_types or 'failure' in block_types
        if not has_terminal:
            self.errors.append("Graph must contain at least one SUCCESS or FAILURE block")
    
    def _validate_node_structure(self, nodes: List[Dict]):
        """Validate individual node structure"""
        node_ids = set()
        
        for i, node in enumerate(nodes):
            node_id = node.get('id')
            
            # Check for unique IDs
            if not node_id:
                self.errors.append(f"Node {i} missing 'id' field")
                continue
            
            if node_id in node_ids:
                self.errors.append(f"Duplicate node ID: {node_id}")
            node_ids.add(node_id)
            
            # Check for required fields
            if 'type' not in node:
                self.errors.append(f"Node {node_id} missing 'type' field")
            
            node_type = node.get('type')
            
            # Validate block-specific requirements
            if node_type == 'action':
                self._validate_action_block(node)
            elif node_type == 'verification':
                self._validate_verification_block(node)
            elif node_type == 'navigation':
                self._validate_navigation_block(node)
            elif node_type == 'loop':
                self._validate_loop_block_structure(node)
    
    def _validate_action_block(self, node: Dict):
        """Validate action block has required data.

        Accepts both the CONTAINER shape (data.actions = [{command, ...}, ...],
        what the visual TestCaseBuilder + QuickTest now write) and the legacy flat
        shape (data.command) — mirroring how the executor reads it.
        """
        data = node.get('data', {})

        actions = data.get('actions')
        if isinstance(actions, list):
            if not actions:
                self.errors.append(f"Action block {node['id']} has an empty 'actions' list")
            elif not all(a.get('command') for a in actions):
                self.errors.append(f"Action block {node['id']} has an action missing 'command'")
            return

        if not data.get('command'):
            self.errors.append(f"Action block {node['id']} missing 'command'")

    def _validate_verification_block(self, node: Dict):
        """Validate verification block has required data.

        Accepts the CONTAINER shape (data.verifications = [...]) as well as the
        legacy flat shape (data.verification_type) — mirroring the executor.
        """
        data = node.get('data', {})

        verifications = data.get('verifications')
        if isinstance(verifications, list):
            if not verifications:
                self.errors.append(f"Verification block {node['id']} has an empty 'verifications' list")
            return

        if not data.get('verification_type'):
            self.errors.append(f"Verification block {node['id']} missing 'verification_type'")

    def _validate_navigation_block(self, node: Dict):
        """Validate navigation block has a target.

        The executor resolves the target from target_node_label, target_node, or
        target_node_id (in that order), so any one of them is sufficient here.
        """
        data = node.get('data', {})

        if (
            not data.get('target_node')
            and not data.get('target_node_id')
            and not data.get('target_node_label')
        ):
            self.errors.append(
                f"Navigation block {node['id']} missing 'target_node_label', 'target_node', or 'target_node_id'"
            )
    
    def _validate_loop_block_structure(self, node: Dict):
        """Validate loop block has required data"""
        data = node.get('data', {})

        iterations = data.get('iterations')
        # iterations may be a {variable} placeholder (resolved at run time) — only
        # range-check concrete numbers; a non-empty string is accepted as a var.
        if isinstance(iterations, str):
            if not iterations.strip():
                self.errors.append(f"Loop block {node['id']} must have 'iterations' >= 1")
        elif iterations is None or iterations < 1:
            self.errors.append(f"Loop block {node['id']} must have 'iterations' >= 1")
        
        # Check for nested graph
        nested_blocks = data.get('nested_blocks')
        if not nested_blocks:
            self.warnings.append(f"Loop block {node['id']} has no nested blocks")
    
    def _validate_edge_structure(self, edges: List[Dict], nodes: List[Dict]):
        """Validate edge structure and references"""
        node_ids = {node['id'] for node in nodes}
        
        for i, edge in enumerate(edges):
            # Check for required fields
            if 'source' not in edge:
                self.errors.append(f"Edge {i} missing 'source' field")
                continue
            if 'target' not in edge:
                self.errors.append(f"Edge {i} missing 'target' field")
                continue
            
            # Check that source and target nodes exist
            if edge['source'] not in node_ids:
                self.errors.append(f"Edge {i} references non-existent source node: {edge['source']}")
            if edge['target'] not in node_ids:
                self.errors.append(f"Edge {i} references non-existent target node: {edge['target']}")
            
            # Validate edge type
            edge_type = edge.get('type') or edge.get('sourceHandle')
            if edge_type not in ['success', 'failure']:
                self.errors.append(f"Edge {i} has invalid type: {edge_type} (must be 'success' or 'failure')")
    
    def _validate_connectivity(self, nodes: List[Dict], edges: List[Dict]):
        """Validate graph connectivity"""
        node_ids = {node['id'] for node in nodes}

        # Build adjacency map by edge type
        outgoing = {node_id: {'success': [], 'failure': []} for node_id in node_ids}
        incoming = {node_id: [] for node_id in node_ids}

        for i, edge in enumerate(edges):
            source = edge.get('source')
            target = edge.get('target')
            edge_type = edge.get('type') or edge.get('sourceHandle', 'success')

            # Validate edge references exist before using them
            if not source:
                self.errors.append(f"Edge {i} missing source field")
                continue
            if not target:
                self.errors.append(f"Edge {i} missing target field")
                continue
            if source not in node_ids:
                self.errors.append(f"Edge {i} (type: {edge_type}) references non-existent source node '{source}' -> '{target}'")
                continue
            if target not in node_ids:
                self.errors.append(f"Edge {i} (type: {edge_type}) references non-existent target node '{source}' -> '{target}'")
                continue
            if edge_type not in ['success', 'failure']:
                self.errors.append(f"Edge {i} has invalid type '{edge_type}' (source: '{source}' -> target: '{target}')")
                continue

            # Only build connectivity if edge is valid
            if edge_type in ['success', 'failure']:
                outgoing[source][edge_type].append(target)
                incoming[target].append(source)
        
        # Check for orphaned nodes (except terminal blocks)
        for node in nodes:
            node_id = node['id']
            node_type = node.get('type')
             
            # START doesn't require outgoing connection - it's valid on its own
            # (allows for minimal test cases that just check if system can start)
            # if node_type == 'start' and not outgoing[node_id]:
            #     self.errors.append(f"START block has no outgoing connections")
            
            # Terminal blocks should have incoming but no outgoing
            if node_type in ['success', 'failure', 'break_success']:
                if not incoming[node_id] and node_type == 'failure':
                    # FAILURE blocks without incoming edges are OK - they serve as implicit failure handlers
                    pass
                elif not incoming[node_id]:
                    self.warnings.append(f"{node_type.upper()} block has no incoming connections")
                if outgoing[node_id]['success'] or outgoing[node_id]['failure']:
                    self.warnings.append(f"{node_type.upper()} block should not have outgoing connections")

            # Non-terminal blocks should have both incoming and outgoing
            if node_type not in ['start', 'success', 'failure', 'break_success']:
                if not incoming[node_id]:
                    self.warnings.append(f"Block {node_id} ({node_type}) has no incoming connections")
                # Check success edge (required)
                if not outgoing[node_id]['success']:
                    self.warnings.append(f"Block {node_id} ({node_type}) has no success edge (graph may end prematurely)")
                # Check failure edge (optional - will implicitly route to FAILURE terminal if missing)
                if not outgoing[node_id]['failure']:
                    # This is informational only - failure edges are optional
                    pass
    
    def _validate_required_inputs(self, graph: Dict[str, Any]):
        """A required scriptConfig input must arrive with a runtime value or a default.

        Fails the run up-front instead of letting a {placeholder} block fail mid-test.
        """
        script_config = graph.get('scriptConfig') or {}
        for input_config in script_config.get('inputs', []) or []:
            # Protected inputs (host_name, device_name, …) describe the execution
            # environment and are filled from the request, not by the user.
            if not input_config.get('required') or input_config.get('protected'):
                continue
            value = input_config.get('value')
            if value is None or value == '':
                value = input_config.get('default')
            if value is None or value == '':
                self.errors.append(
                    f"Required input '{input_config.get('name')}' has no value or default"
                )

    def _validate_loop_blocks(self, nodes: List[Dict]):
        """Validate nested graphs in loop blocks"""
        for node in nodes:
            if node.get('type') == 'loop':
                nested_blocks = node.get('data', {}).get('nested_blocks')
                
                if nested_blocks:
                    # Recursively validate nested graph
                    is_valid, nested_errors, nested_warnings = self.validate_graph(nested_blocks)
                    
                    # Prefix errors with loop block ID
                    for error in nested_errors:
                        self.errors.append(f"Loop {node['id']}: {error}")
                    for warning in nested_warnings:
                        self.warnings.append(f"Loop {node['id']}: {warning}")

