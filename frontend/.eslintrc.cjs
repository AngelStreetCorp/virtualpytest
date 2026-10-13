module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    // Codebase uses `any` extensively for dynamic device/API data — enforce typing incrementally
    '@typescript-eslint/no-explicit-any': 'off',
    // Hook dependency exhaustive checks have many pre-existing violations — enforce incrementally
    'react-hooks/exhaustive-deps': 'off',
    // ON as of 2026-09-30. The 56 pre-existing violations are fixed: the early-return
    // -above-hooks components (ProtectedRoute, NodeSelectionPanel, NodeEditDialog) now
    // branch in a thin wrapper so the body's hooks are unconditional, the
    // `try { useSomeContext() } catch {}` sites use the non-throwing
    // useOptional* variants, and TestCaseBuilder no longer calls a hook from inside
    // JSX (that one changed the hook COUNT between renders — a real latent crash, not
    // a style issue). Keep this on: it is a correctness rule.
    // Fast-refresh warnings not needed in CI
    'react-refresh/only-export-components': 'off',
    // Allow _prefixed unused vars (intentional unused destructuring)
    '@typescript-eslint/no-unused-vars': [
      'error',
      { varsIgnorePattern: '^_', argsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
    ],
    // Intentional use of constant conditions (e.g. while(true) polling loops)
    'no-constant-condition': 'off',
    // Case declarations without braces — pre-existing pattern, low risk
    'no-case-declarations': 'off',
    // {} type used in some shared types — enforce incrementally
    '@typescript-eslint/ban-types': 'off',
  },
};
