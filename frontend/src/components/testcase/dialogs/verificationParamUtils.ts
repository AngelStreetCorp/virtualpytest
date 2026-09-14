/**
 * Shared helpers for cleaning verification block params.
 *
 * TestCase builder blocks seed their params as PARAM SCHEMAS
 * (e.g. `text: {type:'string'}`) rather than values, so a raw render shows
 * "[object Object]". These helpers convert a schema to a usable value (its
 * default, else an empty value for its type) while leaving real value objects
 * (like an area {x,y,width,height}) untouched.
 *
 * Used by both the verification config modal (VerificationConfigDialog) and the
 * inline block editor (InlineVerificationConfig) so the cleaning logic never
 * forks.
 */

// Keys that mark an object as a PARAM SCHEMA ({type, required, default, ...})
// rather than a real value (e.g. an area {x,y,width,height} has none of these).
const SCHEMA_KEYS = new Set([
  'type', 'required', 'default', 'placeholder', 'description', 'optional',
  'hidden', 'min', 'max', 'options', 'label',
]);

// Convert a single param to a usable value. Pull the schema's default, else an
// empty value for its type. Real value objects (area, etc.) pass through.
export const cleanParamValue = (v: any): any => {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    const keys = Object.keys(v);
    const isSchema = keys.length > 0 && keys.every((k) => SCHEMA_KEYS.has(k));
    if (isSchema) {
      if ('default' in v) return v.default;
      if (v.type === 'number') return '';
      if (v.type === 'boolean') return false;
      if (v.type === 'area') return undefined;
      return '';
    }
  }
  return v;
};

// Clean every param on a verification so the editor shows real fields.
export const cleanVerification = (verification: any): any => {
  if (!verification) return verification;
  const params = verification.params || {};
  const cleaned: Record<string, any> = {};
  Object.entries(params).forEach(([k, val]) => {
    cleaned[k] = cleanParamValue(val);
  });
  return { ...verification, params: cleaned };
};
