/**
 * Parameter Type System for Dynamic Block Configuration
 * 
 * Mirrors backend param_types.py to enable dynamic form generation
 * based on parameter type metadata from backend controllers.
 */

export enum ParamType {
  STRING = 'string',
  NUMBER = 'number',
  BOOLEAN = 'boolean',
  AREA = 'area',
  SELECT = 'select',
  ARRAY = 'array',
  OBJECT = 'object',
}

export interface SelectOption {
  label: string;
  value: string | number;
}

export interface ParamDefinition {
  type: ParamType;
  required: boolean;
  default: any;
  description: string;
  placeholder?: string;
  min?: number;
  max?: number;
  options?: SelectOption[];
  sub_params?: Record<string, ParamDefinition>;
  group?: string;
}

export interface BlockParams {
  [paramName: string]: ParamDefinition;
}

export interface VerificationConfig {
  command: string;
  params: BlockParams;
  verification_type?: string;
  block_type?: string;
  description: string;
}

/**
 * Helper to extract the actual parameter value from a ParamDefinition
 * Used when converting typed params to plain values for execution
 */
export function getParamValue(param: any): any {
  if (param && typeof param === 'object' && 'default' in param) {
    return param.default;
  }
  return param;
}

/**
 * Helper to check if a parameter definition is required
 */
export function isParamRequired(param: ParamDefinition): boolean {
  return param.required === true;
}

/**
 * Helper to get the display type for UI rendering
 */
export function getParamDisplayType(param: ParamDefinition): string {
  switch (param.type) {
    case ParamType.STRING:
      return 'text';
    case ParamType.NUMBER:
      return 'number';
    case ParamType.BOOLEAN:
      return 'checkbox';
    case ParamType.AREA:
      return 'area-picker';
    case ParamType.SELECT:
      return 'select';
    case ParamType.ARRAY:
      return 'array';
    case ParamType.OBJECT:
      return 'object';
    default:
      return 'text';
  }
}

/**
 * Validate a parameter value against its definition
 */
export function validateParamValue(value: any, param: ParamDefinition): { valid: boolean; error?: string } {
  // Check required
  if (param.required && (value === null || value === undefined || value === '')) {
    return { valid: false, error: `${param.description} is required` };
  }

  // Type-specific validation
  switch (param.type) {
    case ParamType.NUMBER:
      const num = Number(value);
      if (isNaN(num)) {
        return { valid: false, error: 'Must be a valid number' };
      }
      if (param.min !== undefined && num < param.min) {
        return { valid: false, error: `Must be at least ${param.min}` };
      }
      if (param.max !== undefined && num > param.max) {
        return { valid: false, error: `Must be at most ${param.max}` };
      }
      break;

    case ParamType.STRING:
      if (value && typeof value !== 'string') {
        return { valid: false, error: 'Must be a string' };
      }
      break;

    case ParamType.BOOLEAN:
      if (value !== null && value !== undefined && typeof value !== 'boolean') {
        return { valid: false, error: 'Must be true or false' };
      }
      break;

    case ParamType.AREA:
      if (value && (!value.x || !value.y || !value.width || !value.height)) {
        return { valid: false, error: 'Must specify x, y, width, height' };
      }
      break;

    case ParamType.SELECT:
      if (value && param.options) {
        const validValues = param.options.map(opt => opt.value);
        if (!validValues.includes(value)) {
          return { valid: false, error: `Must be one of: ${validValues.join(', ')}` };
        }
      }
      break;
  }

  return { valid: true };
}

