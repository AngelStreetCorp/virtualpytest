"""
Pokémon Blue showcase library (TASK-33 phase 4): play the real Game Boy game in a browser emulator,
Jev-style. The harness reads the game's memory, lists the legal options with facts, and a chooser
(Jev, an LLM or a heuristic) picks one.

The ROM is the owner's own copy and is NEVER part of this package, the repo or any upload: the
runner reads it from a private path and hands it to the emulator page from memory. Emulator save
states contain the game too and stay private files next to the ROM. Game data (move table, type
chart) is located in the ROM at run time, not copied here.

- memory.py   French ROM memory map (US addresses +5 in the shifted area), text decoding, screen
- rom.py      locates the move table and the type chart in the ROM
- battle.py   battle state, options with facts, a heuristic chooser, menu key plans
- web/        the emulator page (GameBoy-Online, MIT, loaded from jsDelivr at a pinned commit)
"""
