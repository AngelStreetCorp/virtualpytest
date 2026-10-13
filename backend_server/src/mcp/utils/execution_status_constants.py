"""
Constants for the MCP execution status tools (get_testcase_execution_status,
get_script_execution_status).

execute_testcase / execute_script return an id at once; callers read the run's
state with the status tools. A status call may wait a little for the run to end,
but always answers well under a proxy's idle limit (Cloudflare answers 524 after
100 s), so no MCP request holds open for the length of a run.
"""

STATUS_WAIT_DEFAULT_S = 20
STATUS_WAIT_MAX_S = 50
STATUS_READ_INTERVAL_S = 2

# Normalised run states every status tool reports.
STATE_RUNNING = 'running'
STATE_COMPLETED = 'completed'
STATE_FAILED = 'failed'
STATE_ABORTED = 'aborted'
STATE_UNKNOWN = 'unknown'  # the status read itself failed transiently; read again

DONE_STATES = {STATE_COMPLETED, STATE_FAILED, STATE_ABORTED}
