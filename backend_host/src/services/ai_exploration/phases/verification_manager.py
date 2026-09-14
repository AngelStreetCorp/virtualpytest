import time
from typing import Dict, Any, List
from backend_host.src.services.ai_exploration.dump_analyzer import analyze_unique_elements
from shared.src.lib.database.navigation_trees_db import get_node_by_id, save_node, save_nodes_batch
from shared.src.lib.database.verifications_references_db import save_reference, snapshot_reference_version

def start_node_verification(executor) -> Dict[str, Any]:
    """
    Phase 2c: Analyze dumps and suggest verifications
    
    Returns:
        {
            'success': True,
            'suggestions': [...],
            'total_nodes': 5
        }
    """
    with executor._lock:
        if executor.exploration_state['status'] != 'validation_complete':
            return {
                'success': False,
                'error': f"Cannot start node verification: status is {executor.exploration_state['status']}"
            }
        
        node_verification_data = executor.exploration_state.get('node_verification_data', [])
        
        if not node_verification_data:
            return {
                'success': False,
                'error': 'No node verification data available'
            }
        
        print(f"\n{'='*100}")
        print(f"🔍 [VERIFICATION MANAGER] Received {len(node_verification_data)} nodes from validation")
        print(f"{'='*100}")
        for idx, item in enumerate(node_verification_data):
            print(f"  [{idx}] {item.get('node_id'):20} -> {item.get('screenshot_url', 'NO SCREENSHOT')}")
        print(f"{'='*100}\n")
        
        # Filter out start_node if it already has verification
        if executor.exploration_state.get('start_node_has_verification', False):
            start_node_id = executor.exploration_state.get('home_id')
            node_verification_data = [n for n in node_verification_data if n.get('node_id') != start_node_id]
            start_node_label = executor.exploration_state.get('start_node', start_node_id)
            print(f"[@ExplorationExecutor:start_node_verification] Filtered out '{start_node_label}' (already has verification)")
            
            print(f"\n{'='*100}")
            print(f"🔍 [VERIFICATION MANAGER] After filtering: {len(node_verification_data)} nodes")
            print(f"{'='*100}")
            for idx, item in enumerate(node_verification_data):
                print(f"  [{idx}] {item.get('node_id'):20} -> {item.get('screenshot_url', 'NO SCREENSHOT')}")
            print(f"{'='*100}\n")
        
        print(f"[@ExplorationExecutor:start_node_verification] Analyzing {len(node_verification_data)} nodes")
        
        # Analyze dumps to find unique elements
        suggestions = analyze_unique_elements(node_verification_data, device_model=executor.device_model)
        
        # Store suggestions
        executor.exploration_state['node_verification_suggestions'] = suggestions
        executor.exploration_state['status'] = 'awaiting_node_verification'
        executor.exploration_state['current_step'] = 'Node verification suggestions ready - review and approve'
        
        print(f"[@ExplorationExecutor:start_node_verification] Generated {len(suggestions)} suggestions")
        
        print(f"\n{'='*100}")
        print(f"📨 [VERIFICATION MANAGER] Sending suggestions to frontend")
        print(f"{'='*100}")
        for idx, suggestion in enumerate(suggestions):
            node_id = suggestion.get('node_id')
            node_label = suggestion.get('node_label')
            screenshot_url = suggestion.get('screenshot_url', 'NO SCREENSHOT')
            has_verification = suggestion.get('suggested_verification', {}).get('found', False)
            print(f"  [{idx}] {node_label:20} (id: {node_id:20}) -> {screenshot_url[:80]}... | Verification: {'✅' if has_verification else '❌'}")
        print(f"{'='*100}\n")
        
        return {
            'success': True,
            'suggestions': suggestions,
            'total_nodes': len(suggestions),
            'message': 'Node verification analysis complete'
        }

def approve_node_verifications(executor, approved_verifications: List[Dict], team_id: str) -> Dict[str, Any]:
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
    with executor._lock:
        if executor.exploration_state['status'] != 'awaiting_node_verification':
            return {
                'success': False,
                'error': f"Cannot approve: status is {executor.exploration_state['status']}"
            }
        
        tree_id = executor.exploration_state['tree_id']
        userinterface_name = executor.exploration_state.get('userinterface_name')
        
        print(f"[@ExplorationExecutor:approve_node_verifications] Updating {len(approved_verifications)} nodes")
        
        nodes_updated = 0
        references_created = 0
        nodes_to_save = []
        
        for item in approved_verifications:
            node_id = item['node_id']
            verification = item.get('verification')
            screenshot_url = item.get('screenshot_url')
            
            # Get node
            node_result = get_node_by_id(tree_id, node_id, team_id)
            if not node_result.get('success'):
                print(f"  ❌ Node {node_id} not found")
                continue
            
            node_data = node_result['node']
            
            # ✅ Skip start_node if it already has verification
            start_node_id = executor.exploration_state.get('home_id')
            existing_verifications = node_data.get('verifications', [])
            
            if node_id == start_node_id and len(existing_verifications) > 0:
                start_node_label = executor.exploration_state.get('start_node', node_id)
                print(f"  ⏭️  Skipping '{start_node_label}': already has {len(existing_verifications)} verification(s)")
                continue
            
            # Update node with screenshot + verification
            if screenshot_url:
                # Ensure data field exists
                if 'data' not in node_data or node_data['data'] is None:
                    node_data['data'] = {}
                
                # Store screenshot in data JSONB column, not as root column
                node_data['data']['screenshot'] = screenshot_url
                node_data['data']['screenshot_timestamp'] = int(time.time() * 1000)
            
            # 🛡️ VALIDATION: Only save valid verifications (same logic as useNodeEdit.ts)
            if verification:
                # ✅ TV/TEXT: Check if this is a text verification that needs reference creation
                is_text_verification = verification.get('text') and verification.get('area')
                
                if is_text_verification:
                    # 📝 CREATE TEXT REFERENCE FIRST (TV workflow)
                    print(f"  📝 Creating text reference for node {node_id}")
                    
                    # Get node label (remove _temp suffix)
                    node_label = node_data.get('label', node_id).replace('_temp', '')
                    
                    # Create reference name with _text suffix (WITHOUT userinterface prefix)
                    # Frontend will generate internal key as: {userinterface}_{reference_name}_text
                    # So if we save "profile_text", frontend creates key "test_stb_profile_text_text"
                    reference_name = f"{node_label}_text"
                    
                    # Merge text with area data (match text_helpers.py format)
                    # Only store text + area coordinates (no confidence/font_size needed)
                    area_with_text = {
                        **(verification['area'] or {}),
                        'text': verification['text']  # ✅ Only text - confidence not needed in DB
                    }
                    
                    # Snapshot previous version before overwrite (best-effort, no-op on first capture)
                    snapshot_reference_version(reference_name, userinterface_name, 'reference_text', team_id)

                    from shared.src.lib.utils.reference_utils import reference_storage_key
                    _ui_folder = reference_storage_key(userinterface_name, team_id)
                    reference_result = save_reference(
                        name=reference_name,
                        userinterface_name=userinterface_name,
                        reference_type='reference_text',
                        team_id=team_id,
                        r2_path=f'text-references/{_ui_folder}/{reference_name}',
                        r2_url='',  # Text references don't have URLs
                        area=area_with_text
                    )
                    
                    if reference_result.get('success'):
                        references_created += 1
                        print(f"    ✅ Text reference created: {reference_name}")
                        
                        # Create verification that uses the reference
                        if 'verifications' not in node_data:
                            node_data['verifications'] = []
                        
                        # Add text verification with reference_name AND text (match manual flow)
                        node_data['verifications'].append({
                            'command': 'waitForTextToAppear',
                            'verification_type': 'text',
                            'params': {
                                'reference_name': reference_name,  # ← Points to DB entry
                                'text': verification['text'],  # ✅ Add text field like manual flow
                                'area': verification['area']  # ✅ Add area for completeness
                            },
                            'expected': True
                        })
                        
                        print(f"    ✅ Verification added with reference: {reference_name}")
                    else:
                        print(f"    ❌ Failed to create text reference: {reference_result.get('error')}")
                        continue
                
                elif verification.get('params'):
                    # 📱 MOBILE/WEB: Direct params (no reference needed)
                    # Validate: params must not be empty dict
                    params = verification['params']
                    if not params or not isinstance(params, dict):
                        print(f"  ⚠️ Skipping verification for node {node_id}: empty or invalid params")
                        continue
                    
                    # Validate: at least one param key must have a non-empty value
                    has_valid_param = any(
                        v and str(v).strip() != '' 
                        for v in params.values()
                    )
                    
                    if not has_valid_param:
                        print(f"  ⚠️ Skipping verification for node {node_id}: all param values are empty")
                        continue
                    
                    # Validate: command must exist and not be empty
                    command = verification.get('method', '')
                    if not command or command.strip() == '':
                        print(f"  ⚠️ Skipping verification for node {node_id}: missing command")
                        continue
                    
                    # Add verification to node
                    if 'verifications' not in node_data:
                        node_data['verifications'] = []
                    
                    # Check if verification already exists to avoid duplicates
                    verification_exists = False
                    new_params = verification['params']
                    
                    for v in node_data['verifications']:
                        if v.get('command') == verification.get('method') and v.get('params') == new_params:
                            verification_exists = True
                            break
                    
                    if not verification_exists:
                        # Map 'method' to 'command' for standard verification format
                        node_data['verifications'].append({
                            'command': command,  # Use validated command
                            'verification_type': verification.get('type', 'adb'),
                            'params': verification['params'],
                            'expected': True
                        })
                        print(f"    ✅ Verification added (direct params)")
            
            nodes_to_save.append(node_data)
        
        # Save all updated nodes in a SINGLE BATCH
        # This ensures the materialized view refresh trigger fires only ONCE
        if nodes_to_save:
            save_result = save_nodes_batch(tree_id, nodes_to_save, team_id)
            if save_result.get('success'):
                nodes_updated = len(nodes_to_save)
                print(f"  ✅ Successfully updated {nodes_updated} nodes (batch)")
                for n in nodes_to_save:
                    print(f"    • {n.get('node_id')}")
            else:
                print(f"  ❌ Failed to batch update nodes: {save_result.get('error')}")
        
        # Update state
        executor.exploration_state['status'] = 'node_verification_complete'
        
        if references_created > 0:
            executor.exploration_state['current_step'] = f'Updated {nodes_updated} nodes ({references_created} text references created) - ready to finalize'
        else:
            executor.exploration_state['current_step'] = f'Updated {nodes_updated} nodes - ready to finalize'
        
        return {
            'success': True,
            'nodes_updated': nodes_updated,
            'references_created': references_created,
            'message': f'Updated {nodes_updated} nodes with verifications' + (f' ({references_created} text references created)' if references_created > 0 else '')
        }

