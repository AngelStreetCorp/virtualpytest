"""League of Legends screenshot→state contracts and detector stubs (TASK-121).

The real Riot / League client is a **human-played data source only** (TASK-121
§6 FR-13). Nothing in this package launches the Riot Client, fills credentials,
clicks PLAY, picks a champion, accepts runes, buys items, or presses any key
on the real client. The detector stubs return placeholder ``unknown`` values
and are wired only against synthetic / replay / offline-simulator inputs.
"""