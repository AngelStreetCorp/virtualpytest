import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAIContext } from '../../contexts/AIContext';
import { useSocket } from '../../contexts/SocketContext';

interface UIEvent {
  type: 'ui_action';
  action: string;
  payload: any;
  agent_message?: string;
}

export const useAIOrchestrator = () => {
  const {
    setProcessing
  } = useAIContext();

  const navigate = useNavigate();

  // Use centralized socket
  const { socket, connect } = useSocket();

  useEffect(() => {
    if (!socket) return;

    // Connect the centralized socket if not already connected
    connect();

    // 2. Listen for UI Actions (Navigation, etc.)
    socket.on('ui_action', (event: UIEvent) => {
      console.log('🤖 Received UI Action:', event);

      if (event.action === 'navigate') {
        const path = event.payload.path;
        if (path) {
          console.log(`🤖 Navigating to: ${path}`);
          navigate(path);

          // Optional: Show toast or update status
        }
      }
    });

    // 3. Listen for Agent Events to update UI state
    socket.on('agent_event', (event: any) => {
      // Auto-open pilot panel if agent is thinking or acting
      if (['thinking', 'tool_call', 'agent_delegated'].includes(event.type)) {
        setProcessing(true);
      }

      if (['session_ended', 'complete', 'error'].includes(event.type)) {
        setProcessing(false);
      }
    });

    socket.on('connect', () => {
      console.log('🤖 AI Orchestrator socket connected');
    });

    // No cleanup needed - socket is managed by SocketContext
  }, [socket, connect, navigate, setProcessing]);

  return {
    socket
  };
};


