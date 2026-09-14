/**
 * Campaign Graph Types
 * 
 * TypeScript interfaces for the visual campaign builder.
 * Defines the structure for campaign graphs, nodes, edges, and data linking.
 */

import { Node } from 'reactflow';

// Campaign Graph Structure
export interface CampaignGraph {
  nodes: CampaignNode[];
  edges: CampaignEdge[];
  campaignConfig?: CampaignGraphConfig;
}

export interface CampaignGraphConfig {
  inputs?: CampaignInput[];
  outputs?: CampaignOutput[];
  reports?: CampaignReports;
}

export interface CampaignInput {
  name: string;
  type?: string;
  defaultValue?: any;
}

export interface CampaignOutput {
  name: string;
  sourceBlockId?: string;
  sourceOutputName?: string;
  sourceOutputPath?: string;
}

export interface CampaignReports {
  mode: 'set' | 'aggregate';
  fields: CampaignReportField[];
}

export interface CampaignReportField {
  name: string;
  sourceBlockId?: string;
  sourceOutputName?: string;
}

// Node Types
export type CampaignNodeType = 
  | 'start' 
  | 'success' 
  | 'failure' 
  | 'testcase' 
  | 'script'
  | 'conditional'  // Future
  | 'loop';        // Future

export interface CampaignNode extends Node {
  type: CampaignNodeType;
  data: CampaignNodeData;
}

export interface CampaignNodeData {
  label: string;
  description?: string;

  // For testcase/script nodes
  executableId?: string;      // UUID for testcases, filename for scripts
  executableType?: 'testcase' | 'script';
  executableName?: string;

  // Configuration
  parameters?: Record<string, any>;

  // I/O (from testcase scriptConfig or script analysis)
  inputs?: BlockInput[];
  outputs?: BlockOutput[];
  metadata?: BlockMetadata[];

  // Execution state (during run)
  status?: 'pending' | 'running' | 'completed' | 'failed';
  executionTime?: number;
  error?: string;

  // Viewer mode properties
  readOnly?: boolean;
  selectedUserInterface?: string;
}

export interface BlockInput {
  name: string;
  type?: string;
  required?: boolean;
  /** The testcase input's default — shown as the field placeholder; used when
   *  no per-row value is set. */
  default?: any;
  value?: any;               // Static value or template string
  linkedSource?: {           // If linked to another block's output
    blockId: string;
    outputName: string;
    outputPath?: string;     // For nested access (e.g., "parsed_data.serial")
  };
}

export interface BlockOutput {
  name: string;
  type?: string;
  description?: string;
}

export interface BlockMetadata {
  name: string;
  description?: string;
}

// Edge Types
export type CampaignEdgeType = 
  | 'control'     // Sequential execution flow
  | 'pass'        // Success branch
  | 'fail';       // Failure branch

export interface CampaignEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  type: CampaignEdgeType;
  animated?: boolean;
  style?: React.CSSProperties;
  label?: string;
  data?: any;
}

// Toolbox Item (for drag-drop)
export interface CampaignToolboxItem {
  id: string;
  type: CampaignNodeType;
  label: string;
  icon: string;
  category: 'testcases' | 'scripts' | 'flow' | 'terminal';
  
  // For testcase/script items
  executableId?: string;
  executableType?: 'testcase' | 'script';
  executableName?: string;
  
  // Metadata for display
  description?: string;
  tags?: string[];
  folder?: string;
}

// Campaign Builder State
export interface CampaignBuilderState {
  campaign_id?: string;
  campaign_name?: string;
  description?: string;
  
  // Infrastructure
  userinterface_name?: string;
  host?: string;
  device?: string;
  
  // Graph
  graph: CampaignGraph;
  
  // UI State
  selectedNode?: string;
  isExecuting?: boolean;
}

// Drag-Drop Data Transfer
export interface CampaignDragData {
  type: 'toolbox-item' | 'output-badge';
  
  // For toolbox items
  toolboxItem?: CampaignToolboxItem;
  
  // For output badges (data linking)
  blockId?: string;
  outputName?: string;
  outputType?: string;
}

