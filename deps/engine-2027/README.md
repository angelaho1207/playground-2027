# engine-2027

`engine.py` is the Homie Hold'em engine from `mitpokerbots/scrimmage`
(`game/engine.py`, commit `ef685a8`), plus the rules for Weeks 2 and 3, which
the scrimmage engine does not have yet. `WEEK` in the config picks the rules;
with `WEEK = 1` (or no `WEEK`) the engine behaves exactly like scrimmage's.

- Week 2: each team plays one combined hand at showdown. Every live player
  submits one hole card or none (`S` request; `S0`, `S1` or `S` reply), and
  everyone then sees all live hands and the submissions (`U#:card`). A hand
  ends as soon as only one team has players left.
- Week 3: Week 2, plus a new random seating and button every orbit of four
  hands. Each player is told its teammates' seats (`M#`).

The protocol for these is defined here first; scrimmage and the released
skeletons need the same changes. `deps/test_bot.zip` is scrimmage's 4-seat
python fixture bot with its skeleton updated for this protocol and
`STARTING_STACK = 200`.

The playground does not run the engine as a script. `server/tasks.py` imports
it and drives `Game.run_round` itself, so the human's two seats can be played
from the browser while the bot's two replicas run as normal engine players.
