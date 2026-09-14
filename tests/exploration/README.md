# Exploration Tests

Random/chaos tests to discover bugs not covered by regression tests.

## Rules

1. Each test = one markdown file: `tests/exploration/<name>.md`
2. If bug found → evaluate if worth a permanent testcase
3. Only rare/valuable edge cases become testcases

## Format

```markdown
# Test: <name>
## Description
What this test explores

## Steps
1. Navigate to X
2. Click Y
3. Observe Z

## Expected
A happens

## Actual (if bug)
B happens instead

## Worth a testcase?
Yes/No — reason
```

## Ideas for Exploration

- Rapid navigation between all pages
- Concurrent testcase executions
- Invalid credentials handling
- Large dataset UI performance
- Browser refresh during test execution
- Network timeout scenarios
- Invalid API responses
- Empty state handling
- Very long testcase names
- Special characters in inputs

## Running Exploration

```bash
# Manual exploration - pick random tests from this folder
ls tests/exploration/
```
