/**
 * Variable Resolution Utilities
 *
 * Resolves {variable_name} references to actual values for PER-ITEM manual Run
 * only (UniversalBlock / inline configs), where previewing with input defaults
 * is the correct semantic. Full testcase runs are resolved SERVER-SIDE by
 * TestCaseExecutor._resolve_block_data from scriptConfig.inputs[].value/default.
 */

export interface ScriptInput {
  name: string;
  default?: any; // Optional to match TestCase_Types.ScriptInput
}

export interface ScriptVariable {
  name: string;
  value?: any; // Optional to match Variable type
}

/**
 * Resolve a single {variable_name} reference to its actual value.
 * 
 * Priority:
 * 1. scriptInputs (use .default value)
 * 2. scriptVariables (use .value)
 * 3. Return as-is if not found (with warning)
 * 
 * @param value - Value that may contain {variable_name} reference
 * @param scriptInputs - Array of script inputs with default values
 * @param scriptVariables - Array of script variables with values
 * @returns Resolved value or original if not a reference
 */
export const resolveVariableInValue = (
  value: any,
  scriptInputs?: ScriptInput[],
  scriptVariables?: ScriptVariable[]
): any => {
  if (typeof value !== 'string') return value;
  
  // Check if it's a variable reference: {variable_name}
  const varMatch = value.match(/^\{(.+?)\}$/);
  if (!varMatch) return value;
  
  const varName = varMatch[1].trim();
  
  // Try scriptInputs first (use .default value)
  const input = scriptInputs?.find((inp) => inp.name === varName);
  if (input && input.default !== undefined) {
    console.log(`[variableResolution] Resolved {${varName}} = ${JSON.stringify(input.default)} (from scriptInputs)`);
    return input.default;
  }
  
  // Try scriptVariables (use .value)
  const variable = scriptVariables?.find((v) => v.name === varName);
  if (variable && variable.value !== undefined) {
    console.log(`[variableResolution] Resolved {${varName}} = ${JSON.stringify(variable.value)} (from scriptVariables)`);
    return variable.value;
  }
  
  // Not found - warn and return as-is
  console.warn(`[variableResolution] Variable {${varName}} not found in scriptInputs or scriptVariables`);
  return value;
};

/**
 * Resolve all {variable} references in a params object.
 * Used for manual block execution in UniversalBlock.
 * 
 * ALSO cleans schema-style params (extracts .default values).
 * 
 * @param params - Object with parameter key-value pairs
 * @param scriptInputs - Array of script inputs
 * @param scriptVariables - Array of script variables
 * @returns New object with all variables resolved and schema cleaned
 */
export const resolveParamsVariables = (
  params: Record<string, any>,
  scriptInputs?: ScriptInput[],
  scriptVariables?: ScriptVariable[]
): Record<string, any> => {
  const resolvedParams: Record<string, any> = {};
  
  Object.entries(params).forEach(([key, value]) => {
    // ✅ CLEAN SCHEMA: If value is schema object {default, type, description, required}, extract .default
    // This matches VerificationsList.tsx lines 298-306
    if (value && typeof value === 'object' && 'default' in value && 'type' in value) {
      console.log(`[variableResolution] Cleaning schema param ${key}: extracting .default from schema`);
      const cleanedValue = value.default;
      resolvedParams[key] = resolveVariableInValue(cleanedValue, scriptInputs, scriptVariables);
    } else {
      // Regular value - resolve directly
      resolvedParams[key] = resolveVariableInValue(value, scriptInputs, scriptVariables);
    }
  });
  
  return resolvedParams;
};


