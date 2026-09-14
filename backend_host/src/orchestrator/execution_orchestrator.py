"""
Execution Orchestrator
Unified coordinator for all execution types (navigation, actions, verifications, blocks)
Handles cross-cutting concerns: logging, screenshots, error handling
"""

from typing import Dict, Any, List, Optional
from .logging_manager import LoggingManager
from .screenshot_manager import ScreenshotManager


class ExecutionOrchestrator:
    """
    Unified orchestrator that coordinates all execution types.
    Handles cross-cutting concerns and delegates to domain executors.
    """
    
    @staticmethod
    async def execute_navigation(
        device,
        tree_id: str,
        userinterface_name: str,
        target_node_id: str = None,
        target_node_label: str = None,
        navigation_path: List[Dict] = None,
        current_node_id: Optional[str] = None,
        frontend_sent_position: bool = False,
        image_source_url: Optional[str] = None,
        team_id: str = None,
        context=None,
        verification_mode: str = 'end',
    ) -> Dict[str, Any]:
        """
        Execute navigation with logging
        
        Args:
            device: Device instance
            tree_id: Navigation tree ID
            userinterface_name: User interface name (REQUIRED)
            target_node_id: Target node ID (UUID)
            target_node_label: Target node label
            navigation_path: Optional pre-computed path
            current_node_id: Optional current position
            frontend_sent_position: Whether frontend explicitly sent position
            image_source_url: Optional image source URL
            team_id: Team ID for security
            context: Optional execution context
            
        Returns:
            Dict with success status, logs, and navigation details
        """
        print(f"[@ExecutionOrchestrator] Executing navigation to {target_node_label or target_node_id}")
        
        async def execute():
            return await device.navigation_executor.execute_navigation(
                tree_id=tree_id,
                userinterface_name=userinterface_name,
                target_node_id=target_node_id,
                target_node_label=target_node_label,
                navigation_path=navigation_path,
                current_node_id=current_node_id,
                frontend_sent_position=frontend_sent_position,
                image_source_url=image_source_url,
                team_id=team_id,
                context=context,
                verification_mode=verification_mode,
            )
        
        return await LoggingManager.execute_with_logging(execute)
    
    @staticmethod
    async def execute_actions(
        device,
        actions: List[Dict[str, Any]],
        retry_actions: Optional[List[Dict[str, Any]]] = None,
        failure_actions: Optional[List[Dict[str, Any]]] = None,
        team_id: str = None,
        context=None,
        userinterface_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a list of actions on the device (ad-hoc — no edge context).

        Used for raw remote button presses, MCP testing, etc. — anything not
        tied to a specific edge in a navigation tree. No DB row is written;
        ActionExecutor is a pure primitive.

        For edge-bound execution (Run button, goto step, validation script)
        use `execute_single_edge_step` or `execute_navigation` — both record
        per-step rows with variant + KPI.
        """
        print(f"[@ExecutionOrchestrator] Executing {len(actions)} command(s) [ad-hoc]")

        async def execute():
            return await device.action_executor.execute_actions(
                actions=actions,
                retry_actions=retry_actions,
                failure_actions=failure_actions,
                team_id=team_id,
                context=context,
                userinterface_name=userinterface_name,
            )

        return await LoggingManager.execute_with_logging(execute)

    @staticmethod
    async def execute_single_edge_step(
        device,
        *,
        tree_id: str,
        userinterface_name: str,
        edge_id: str,
        action_set_id: str,
        target_node_id: str,
        actions: List[Dict[str, Any]],
        retry_actions: Optional[List[Dict[str, Any]]] = None,
        failure_actions: Optional[List[Dict[str, Any]]] = None,
        current_node_id: Optional[str] = None,
        team_id: str = None,
        final_wait_time: int = 0,
    ) -> Dict[str, Any]:
        """Run one edge step on the device — same code path as one step of goto.

        Used by the Edge Selection panel's "Run" button. Builds a
        single-element navigation_path from the request's literal actions
        (so unsaved edits in the Edit Edge dialog still work) and delegates
        to NavigationExecutor.execute_navigation. Per-step recording, KPI
        queue, and position update are all handled by the navigation flow.
        """
        print(f"[@ExecutionOrchestrator] Single edge step: {edge_id}#{action_set_id} → {target_node_id}")

        async def execute():
            return await device.navigation_executor.execute_single_edge_step(
                tree_id=tree_id,
                userinterface_name=userinterface_name,
                edge_id=edge_id,
                action_set_id=action_set_id,
                target_node_id=target_node_id,
                actions=actions,
                retry_actions=retry_actions,
                failure_actions=failure_actions,
                current_node_id=current_node_id,
                team_id=team_id,
                final_wait_time=final_wait_time,
            )

        return await LoggingManager.execute_with_logging(execute)

    @staticmethod
    async def execute_single_node_verification(
        device,
        *,
        tree_id: str,
        node_id: str,
        verifications: List[Dict[str, Any]],
        userinterface_name: str,
        image_source_url: Optional[str] = None,
        team_id: str = None,
        generate_success_report: bool = False,
    ) -> Dict[str, Any]:
        """Run a single-node verification (Node panel "Run" button).

        Verification-only counterpart of `execute_single_edge_step`. Runs
        the primitive verifications and writes one node_metrics row through
        NavigationExecutor — same single-owner rule.
        """
        print(f"[@ExecutionOrchestrator] Single node verification: {node_id} ({len(verifications)} checks)")

        async def execute():
            return await device.navigation_executor.execute_single_node_verification(
                tree_id=tree_id,
                node_id=node_id,
                verifications=verifications,
                userinterface_name=userinterface_name,
                image_source_url=image_source_url,
                team_id=team_id,
                generate_success_report=generate_success_report,
            )

        return await LoggingManager.execute_with_logging(execute)

    @staticmethod
    async def execute_verifications(
        device,
        verifications: List[Dict[str, Any]],
        userinterface_name: str,
        image_source_url: Optional[str] = None,
        team_id: str = None,
        context=None,
        tree_id: Optional[str] = None,
        node_id: Optional[str] = None,
        generate_success_report: bool = False
    ) -> Dict[str, Any]:
        """
        Execute verifications with logging.
        Pass condition ('all' vs 'any') is auto-detected from verifications[0]['verification_pass_condition'].
        
        Args:
            device: Device instance
            verifications: List of verifications to execute
            userinterface_name: User interface name (REQUIRED)
            image_source_url: Optional image source URL
            team_id: Team ID for database recording
            context: Optional execution context
            tree_id: Optional tree ID for navigation context
            node_id: Optional node ID for navigation context
            
        Returns:
            Dict with success status, logs, and verification results
        """
        print(f"[@ExecutionOrchestrator] Executing {len(verifications)} verification(s)")
        
        async def execute():
            return await device.verification_executor.execute_verifications(
                verifications=verifications,
                userinterface_name=userinterface_name,
                image_source_url=image_source_url,
                team_id=team_id,
                context=context,
                tree_id=tree_id,
                node_id=node_id,
                generate_success_report=generate_success_report
                # verification_pass_condition auto-detected from verifications[0]
            )
        
        return await LoggingManager.execute_with_logging(execute)
    
    @staticmethod
    async def execute_blocks(
        device,
        blocks: List[Dict[str, Any]],
        context=None
    ) -> Dict[str, Any]:
        """
        Execute standard blocks with logging
        
        Args:
            device: Device instance
            blocks: List of standard blocks to execute
            context: Optional execution context
            
        Returns:
            Dict with success status, logs, and block results
        """
        print(f"[@ExecutionOrchestrator] Executing {len(blocks)} block(s)")
        
        def execute():
            return device.standard_block_executor.execute_blocks(
                blocks=blocks,
                context=context
            )
        
        return await LoggingManager.execute_with_logging(execute)

