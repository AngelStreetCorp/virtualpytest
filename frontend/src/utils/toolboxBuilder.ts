/**
 * Toolbox Builder - Build toolbox configuration from navigation data + controller actions
 * Reuses DeviceDataContext logic for actions/verifications
 */

import NavigationIcon from '@mui/icons-material/Navigation';
import TouchAppIcon from '@mui/icons-material/TouchApp';
import VerifiedIcon from '@mui/icons-material/Verified';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import PublicIcon from '@mui/icons-material/Public';
import type { Actions } from '../types/controller/Action_Types';
import type { Verifications } from '../types/verification/Verification_Types';

/**
 * Sort commands alphabetically, with shorter names appearing before longer ones
 * Example: "home" before "home_tvguide", "home_movies", etc.
 */
function sortCommands(commands: any[]): any[] {
  return commands.sort((a, b) => {
    const labelA = (a.label || '').toLowerCase();
    const labelB = (b.label || '').toLowerCase();
    
    // If one label starts with the other, shorter one comes first
    if (labelA.startsWith(labelB)) return 1;
    if (labelB.startsWith(labelA)) return -1;
    
    // Otherwise, alphabetical sort
    return labelA.localeCompare(labelB);
  });
}

/**
 * Build dynamic toolbox configuration
 * - Navigation blocks: from tree nodes (screen names)
 * - Actions: from DeviceDataContext availableActions
 * - Verifications: from DeviceDataContext availableVerificationTypes
 * 
 * Returns structure matching toolboxConfig.tsx format
 * 
 * @param isControlActive - Only build toolbox when control is active (not just device selected)
 */
export function buildToolboxFromNavigationData(
  nodes: any[],
  availableActions: Actions,
  availableVerifications: Verifications,
  standardBlocks: any[],
  isControlActive: boolean = false
) {
  // Only show toolbox after taking control, not just on device selection
  if (!isControlActive) {
    console.log('[@toolboxBuilder] Control not active - toolbox not available');
    return null;
  }

  // Note: userInterface is optional - only nodes and availableActions are required
  if (!nodes || nodes.length === 0) {
    console.log('[@toolboxBuilder] Cannot build toolbox - no nodes provided');
    return null;
  }

  // availableActions / availableVerifications arrive as Record<type, Def[]> from
  // DeviceDataContext — flatten to a single list so we can pick a sensible seed.
  const actionDefs: any[] = Object.values(availableActions || {}).flat();
  const verificationDefs: any[] = Object.values(availableVerifications || {}).flat();

  // Extract concrete default values from a def's params (params may be
  // SCHEMA-shaped — {type,required,default} — or already plain values).
  const seedParams = (def: any): Record<string, any> => {
    const out: Record<string, any> = {};
    Object.entries(def?.params || {}).forEach(([k, v]: [string, any]) => {
      out[k] = v && typeof v === 'object' && 'default' in v ? v.default : v;
    });
    return out;
  };

  // Action seed: prefer an "OK" press; fall back to the first available action
  // def; final fallback is one empty-command row (the inline editor refuses a
  // truly-empty list, but an empty-command row is fine).
  const okActionDef = actionDefs.find(
    (d) => (d?.command === 'press_key' && d?.params?.key === 'OK') || d?.label === 'OK',
  );
  const actionSeedDef = okActionDef || actionDefs[0];
  const actionSeed = actionSeedDef
    ? [{
        command: actionSeedDef.command,
        action_type: actionSeedDef.action_type,
        params: seedParams(actionSeedDef),
      }]
    : [{ command: '', params: {} }];

  // Verification seed: prefer "wait for image to appear"; fall back to the first
  // available verification def; final fallback is one empty-command row.
  const waitImageDef = verificationDefs.find((d) => d?.command === 'waitForImageToAppear');
  const verificationSeedDef = waitImageDef || verificationDefs[0];
  const verificationSeed = verificationSeedDef
    ? [{
        command: verificationSeedDef.command,
        verification_type: verificationSeedDef.verification_type,
        params: seedParams(verificationSeedDef),
      }]
    : [{ command: '', params: {} }];

  // Navigation seed: default the target to the "home" node when the tree has
  // one (seed the node's exact label/id so the picker shows it selected); else
  // leave empty for the user to pick.
  const homeNode = (nodes || []).find(
    (n) => (n.label || n.data?.label || '').toLowerCase() === 'home',
  );
  const navigationSeed = homeNode
    ? {
        target_node_label: homeNode.label || homeNode.data?.label,
        target_node_id: homeNode.id || homeNode.node_id,
      }
    : {};

  // Standard seed: default to the Wait (sleep) op so the block is configured on
  // drop; the user can switch the operation inside.
  const sleepDef = (standardBlocks || []).find((b) => b?.command === 'sleep');
  const standardSeed = sleepDef
    ? {
        command: 'sleep',
        action_type: 'standard_block',
        params: seedParams(sleepDef),
        paramSchema: sleepDef.params || {},
      }
    : {};

  // CONTAINER MODEL: the toolbox offers a few GENERIC blocks. You drag one
  // generic block onto the canvas, then "summon" the individual commands inside
  // it (a sequence of actions, a set of verifications, a target node). The
  // individual command lists are sourced inside each block's inline editor from
  // DeviceDataContext (availableActions / availableVerifications / nodes), so
  // the toolbox no longer enumerates 40 keys + 73 nodes + N verifications.
  return {
    standard: {
      tabName: 'Standard',
      groups: [
        {
          groupName: 'Standard',
          commands: [
            {
              type: 'standard',
              label: 'Standard',
              icon: AccessTimeIcon,
              color: '#6b7280',
              outputs: ['success', 'failure'],
              // Defaults to Wait (sleep); switch the operation inside.
              defaultData: standardSeed,
              description: 'Pick a standard operation inside the block (defaults to Wait)',
            },
          ],
        },
      ]
    },
    navigation: {
      tabName: 'Navigation',
      groups: [
        {
          groupName: 'Navigation',
          commands: [
            {
              type: 'navigation',
              label: 'Navigation',
              icon: NavigationIcon,
              color: '#8b5cf6',
              outputs: ['success', 'failure'],
              // Defaults to "home" when the tree has one; change inside the block.
              defaultData: navigationSeed,
              description: 'Go to a node (defaults to home; pick the destination inside)',
            },
          ],
        },
      ]
    },
    actions: {
      tabName: 'Actions',
      groups: [
        {
          groupName: 'Actions',
          commands: [
            {
              type: 'action',
              label: 'Action',
              icon: TouchAppIcon,
              color: '#f97316',
              outputs: ['success', 'failure'],
              // Seed one sensible action (press OK) so the block is never empty;
              // sourced from the device's available actions, with fallbacks.
              defaultData: {
                actions: actionSeed,
              },
              description: 'Run a sequence of actions (e.g. OK → wait → volume up)',
            },
          ],
        },
      ]
    },
    verifications: {
      tabName: 'Verifications',
      groups: [
        {
          groupName: 'Verifications',
          commands: [
            {
              type: 'verification',
              label: 'Verification',
              icon: VerifiedIcon,
              color: '#3b82f6',
              outputs: ['success', 'failure'],
              // Seed one sensible check (wait for image to appear) so the block is
              // never empty; sourced from the device's available verifications.
              defaultData: {
                verifications: verificationSeed,
                verification_pass_condition: 'all',
              },
              description: 'Combine one or more verifications (All / Any must pass)',
            },
          ],
        },
      ]
    },
    api: {
      tabName: 'API',
      groups: extractApiBlockGroups(standardBlocks.filter(b => b.category === 'api'))
    }
  };
}

/**
 * Extract standard block groups from BuilderContext
 * Converts standard blocks from backend into toolbox format
 * 
 * EXPORTED for use in Campaign builder (which doesn't have navigation nodes)
 */
export function extractStandardBlockGroups(standardBlocks: any[]) {
  const groups: any[] = [];

  if (!standardBlocks || standardBlocks.length === 0) {
    console.log(`[@toolboxBuilder] No standard blocks provided`);
    return groups;
  }

  // Map each standard block to toolbox format
  const commands = standardBlocks.map((blockDef: any) => {
    // Extract default values from param schemas
    const defaultParams: Record<string, any> = {};
    if (blockDef.params && typeof blockDef.params === 'object') {
      for (const [key, paramSchema] of Object.entries(blockDef.params)) {
        const schema = paramSchema as any;
        // Get default value from schema
        if (schema && typeof schema === 'object' && 'default' in schema) {
          defaultParams[key] = schema.default;
        }
      }
    }

    return {
      type: blockDef.command,
      label: blockDef.label || blockDef.description || blockDef.command,  // Use short label
      icon: AccessTimeIcon, // Default icon (could be customized per block type)
      color: '#6b7280', // grey - standard operations
      outputs: ['success', 'failure'], // Standard blocks can succeed or fail
      defaultData: {
        command: blockDef.command,
        action_type: 'standard_block',
        params: defaultParams, // ← EXTRACTED DEFAULT VALUES
        paramSchema: blockDef.params || {}, // ← ADD FULL PARAM SCHEMA FOR CONFIG DIALOG
      },
      description: blockDef.description || `Execute ${blockDef.command}`  // Long description
    };
  });

  groups.push({
    groupName: 'Standard',
    commands: sortCommands(commands)
  });

  const totalBlocks = commands.length;
  console.log(`[@toolboxBuilder] Extracted ${totalBlocks} standard blocks`);
  
  return groups;
}

/**
 * Extract API block groups from standard blocks with category='api'
 * API blocks (like api_call) for Postman integration
 */
function extractApiBlockGroups(apiBlocks: any[]) {
  const groups: any[] = [];

  if (!apiBlocks || apiBlocks.length === 0) {
    console.log(`[@toolboxBuilder] No API blocks provided`);
    return groups;
  }

  // Map each API block to toolbox format
  const commands = apiBlocks.map((blockDef: any) => {
    // Extract default values from param schemas
    const defaultParams: Record<string, any> = {};
    if (blockDef.params && typeof blockDef.params === 'object') {
      for (const [key, paramSchema] of Object.entries(blockDef.params)) {
        const schema = paramSchema as any;
        if (schema && typeof schema === 'object' && 'default' in schema) {
          defaultParams[key] = schema.default;
        }
      }
    }

    return {
      type: blockDef.command,
      label: blockDef.name || blockDef.label || blockDef.command,
      icon: blockDef.icon === '🌐' ? PublicIcon : PublicIcon, // Use globe icon
      color: '#06b6d4', // cyan - API blocks
      outputs: ['success', 'failure'],
      defaultData: {
        command: blockDef.command,
        action_type: 'api',
        params: defaultParams,
        paramSchema: blockDef.params || {},
        blockOutputs: blockDef.outputs || [
          { name: 'response', type: 'object' },
          { name: 'status_code', type: 'number' },
          { name: 'headers', type: 'object' },
        ],
      },
      description: blockDef.description || `Execute API call`
    };
  });

  groups.push({
    groupName: 'API',
    commands: sortCommands(commands)
  });

  const totalBlocks = commands.length;
  console.log(`[@toolboxBuilder] Extracted ${totalBlocks} API blocks`);
  
  return groups;
}
