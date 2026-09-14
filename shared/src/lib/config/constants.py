"""
Application Constants and Configuration

Single source of truth for all hardcoded values, magic numbers, and configuration.
Shared across backend_server, backend_host, and all services.

USAGE:
    from shared.src.lib.config.constants import CACHE_CONFIG, HTTP_CONFIG, APP_CONFIG
    ttl = CACHE_CONFIG['LONG_TTL']
    timeout = HTTP_CONFIG['DEFAULT_TIMEOUT']
    team_id = APP_CONFIG['DEFAULT_TEAM_ID']
"""

import os

# =====================================================
# UTILITY FUNCTIONS
# =====================================================

def get_team_id() -> str:
    """
    Get the current team ID from environment or configuration.

    This is the single source of truth for team_id resolution.
    Used by both frontend (buildUrlUtils.ts) and backend MCP tools.

    Returns:
        str: Team ID from TEAM_ID env var or default fallback
    """
    return os.getenv('TEAM_ID', '7fdeb4bb-3639-4ec3-959f-b54769a219ce')

def get_user_id() -> str:
    """
    Get the current user ID from environment or configuration.

    Returns:
        str: User ID from USER_ID env var or default fallback
    """
    return os.getenv('USER_ID', 'eb6cfd93-44ab-4783-bd0c-129b734640f3')

# =====================================================
# APPLICATION CONFIGURATION
# =====================================================

APP_CONFIG = {
    # Default Team ID for all API requests
    # Can be overridden via TEAM_ID environment variable
    'DEFAULT_TEAM_ID': get_team_id(),

    # Default User ID for session management
    # Can be overridden via USER_ID environment variable
    'DEFAULT_USER_ID': get_user_id(),

    # Default identifiers for legacy APIs
    'DEFAULT_USER_NAME': 'default-user',
    'DEFAULT_TEAM_NAME': 'default-team-id',
}

# =====================================================
# CACHE CONFIGURATION (TTL in seconds)
# =====================================================

CACHE_CONFIG = {
    # Very short cache - for frequently changing data (30 seconds)
    # Used for: Host restart status
    'VERY_SHORT_TTL': 30,
    
    # UI cache - for user interface queries (1 minute)
    # Used for: Compatible interfaces lookup
    'UI_TTL': 60,
    
    # Short cache - for dynamic data (2 minutes)
    # Used for: Server hosts data, Script lists
    'SHORT_TTL': 2 * 60,
    
    # Medium cache - for semi-static data (5 minutes)
    # Used for: Navigation trees, heatmap analysis, Reference images (with ETag checking)
    'MEDIUM_TTL': 5 * 60,
    
    # Postman cache - for Postman collections/environments (1 hour)
    # Used for: Postman collections, requests, environments (heavy API calls, rarely change)
    'POSTMAN_TTL': 60 * 60,
    
    # Long cache - for semi-static data (1 hour)
    # Used for: Stream URLs, metadata, device models, user interfaces
    'LONG_TTL': 60 * 60,
    
    # Reference image cache TTL (5 minutes with ETag validation)
    # ETags provide instant change detection, TTL is safety fallback
    'REFERENCE_IMAGE_TTL': 5 * 60,
}

# =====================================================
# HTTP CONFIGURATION (timeouts in seconds)
# =====================================================

HTTP_CONFIG = {
    # Request timeouts
    'ULTRA_SHORT_TIMEOUT': 10,     # ADB operations (input text, click element, key events)
    'VERY_SHORT_TIMEOUT': 5,       # Quick operations
    'SHORT_TIMEOUT': 30,           # Default operations
    'DEFAULT_TIMEOUT': 60,         # Standard timeout
    'NAVIGATION_TIMEOUT': 180,     # Navigation/Action execution (3 minutes)
    'LONG_TIMEOUT': 300,           # Long operations (5 minutes)
    
    # Retry configuration
    'DEFAULT_RETRY_ATTEMPTS': 3,
    'RETRY_DELAY_BASE': 1.0,
}

# =====================================================
# HEATMAP CONFIGURATION
# =====================================================

HEATMAP_CONFIG = {
    # CPU limiting - max worker threads
    'MAX_WORKER_THREADS': 2,
    
    # Process priority setting
    'PROCESS_PRIORITY_LOW': True,
}

# =====================================================
# AI CONFIGURATION
# =====================================================

AI_CONFIG = {
    # Model configuration
    'MODEL': 'microsoft/phi-3-mini-128k-instruct',  # OpenRouter model
    'MAX_TOKENS': 2000,                              # Max completion tokens
    'TEMPERATURE': 0.0,                              # Deterministic output
    
    # Context limits (for smart preprocessing)
    'MAX_NODES_TO_AI': 15,        # Top N navigation nodes
    'MAX_ACTIONS_TO_AI': 10,      # Top N actions
    'MAX_VERIFICATIONS_TO_AI': 8, # Top N verifications
    
    # Confidence thresholds
    'CONFIDENCE_VERY_HIGH': 0.95,  # Auto-correct even with multiple matches
    'CONFIDENCE_HIGH': 0.85,       # Auto-correct single match
    'CONFIDENCE_MEDIUM': 0.60,     # Show in disambiguation
    'CONFIDENCE_LOW': 0.40,        # Minimum similarity
}

