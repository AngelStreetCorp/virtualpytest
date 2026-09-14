# frontend tests

Component and hook tests (Vitest + React Testing Library).

## Config
- `tests/frontend/vitest.config.ts`
- `tests/frontend/setup.ts`

## Run

```bash
cd frontend
npm ci
npm install --no-save vitest@2.1.8 @testing-library/react@16.2.0 @testing-library/jest-dom@6.7.0 jsdom@25.0.1 @vitejs/plugin-react@4.7.0
npx vitest run --config ../tests/frontend/vitest.config.ts
```
