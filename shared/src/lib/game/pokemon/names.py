"""
English names of the Gen 1 moves, by move id (game knowledge, not ROM data). The French ROM names its
moves in French (22 = FOUET LIANES); an LLM thinks of them in English ("Vine Whip"), so the strategist
gets both, or it plans to learn a move the party already knows.
"""

MOVES_EN = (
    "Pound, Karate Chop, Double Slap, Comet Punch, Mega Punch, Pay Day, Fire Punch, Ice Punch, Thunder Punch, "
    "Scratch, Vice Grip, Guillotine, Razor Wind, Swords Dance, Cut, Gust, Wing Attack, Whirlwind, Fly, Bind, Slam, "
    "Vine Whip, Stomp, Double Kick, Mega Kick, Jump Kick, Rolling Kick, Sand Attack, Headbutt, Horn Attack, "
    "Fury Attack, Horn Drill, Tackle, Body Slam, Wrap, Take Down, Thrash, Double-Edge, Tail Whip, Poison Sting, "
    "Twineedle, Pin Missile, Leer, Bite, Growl, Roar, Sing, Supersonic, Sonic Boom, Disable, Acid, Ember, "
    "Flamethrower, Mist, Water Gun, Hydro Pump, Surf, Ice Beam, Blizzard, Psybeam, Bubble Beam, Aurora Beam, "
    "Hyper Beam, Peck, Drill Peck, Submission, Low Kick, Counter, Seismic Toss, Strength, Absorb, Mega Drain, "
    "Leech Seed, Growth, Razor Leaf, Solar Beam, Poison Powder, Stun Spore, Sleep Powder, Petal Dance, "
    "String Shot, Dragon Rage, Fire Spin, Thunder Shock, Thunderbolt, Thunder Wave, Thunder, Rock Throw, "
    "Earthquake, Fissure, Dig, Toxic, Confusion, Psychic, Hypnosis, Meditate, Agility, Quick Attack, Rage, "
    "Teleport, Night Shade, Mimic, Screech, Double Team, Recover, Harden, Minimize, Smokescreen, Confuse Ray, "
    "Withdraw, Defense Curl, Barrier, Light Screen, Haze, Reflect, Focus Energy, Bide, Metronome, Mirror Move, "
    "Self-Destruct, Egg Bomb, Lick, Smog, Sludge, Bone Club, Fire Blast, Waterfall, Clamp, Swift, Skull Bash, "
    "Spike Cannon, Constrict, Amnesia, Kinesis, Soft-Boiled, High Jump Kick, Glare, Dream Eater, Poison Gas, "
    "Barrage, Leech Life, Lovely Kiss, Sky Attack, Transform, Bubble, Dizzy Punch, Spore, Flash, Psywave, Splash, "
    "Acid Armor, Crabhammer, Explosion, Fury Swipes, Bonemerang, Rest, Rock Slide, Hyper Fang, Sharpen, "
    "Conversion, Tri Attack, Super Fang, Slash, Substitute, Struggle"
).split(", ")


def move_en(move_id: int) -> str:
    return MOVES_EN[move_id - 1] if 1 <= move_id <= len(MOVES_EN) else ""
