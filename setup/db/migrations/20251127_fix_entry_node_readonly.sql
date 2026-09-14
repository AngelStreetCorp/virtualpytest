-- Migration: Fix entry-node to allow updates
-- Purpose: Remove read-only restriction from entry-node while keeping deletion protection
-- Date: 2025-11-27
--
-- ISSUE: entry-node was marked as read-only, blocking ALL updates including batch saves
-- FIX: Change entry-node to system-protected only (prevents deletion, allows updates)
--
-- PROTECTION RULES (CORRECTED):
-- - entry-node: SYSTEM-PROTECTED (cannot delete, CAN update)
-- - home: SYSTEM-PROTECTED (cannot delete, CAN update)
-- - edge-entry-node-to-home: SYSTEM-PROTECTED (cannot delete, CAN update)

-- ========================================
-- 1. Update entry-node protection level
-- ========================================

-- Change entry-node from READ-ONLY to SYSTEM-PROTECTED only
UPDATE navigation_nodes 
SET 
    is_system_protected = true,
    is_read_only = false  -- Allow updates, but prevent deletion
WHERE node_id = 'entry-node';

-- ========================================
-- 2. Display migration summary
-- ========================================
DO $$
DECLARE
    protected_nodes integer;
    readonly_nodes integer;
BEGIN
    SELECT COUNT(*) INTO protected_nodes FROM navigation_nodes WHERE is_system_protected = true;
    SELECT COUNT(*) INTO readonly_nodes FROM navigation_nodes WHERE is_read_only = true;
    
    RAISE NOTICE '';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Migration Complete: Fix Entry-Node Protection';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Protected nodes (cannot delete): %', protected_nodes;
    RAISE NOTICE 'Read-only nodes (cannot delete/update): %', readonly_nodes;
    RAISE NOTICE '';
    RAISE NOTICE 'Updated Protection Rules:';
    RAISE NOTICE '  • entry-node: SYSTEM-PROTECTED (cannot delete, CAN update)';
    RAISE NOTICE '  • home: SYSTEM-PROTECTED (cannot delete, CAN update)';
    RAISE NOTICE '  • edge-entry-node-to-home: PROTECTED (cannot delete, CAN update)';
    RAISE NOTICE '';
    RAISE NOTICE 'This allows batch save operations to update entry-node metadata';
    RAISE NOTICE 'while still preventing accidental deletion.';
    RAISE NOTICE '========================================';
END $$;

