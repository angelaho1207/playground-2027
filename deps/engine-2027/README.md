# engine-2027

`engine.py` is the stock Homie Hold'em engine, copied unchanged from
`mitpokerbots/scrimmage` (`game/engine.py`, commit `ef685a8`). Keep it in sync
with that file; do not edit it here.

The playground does not run it as a script. `server/tasks.py` imports it and
drives `Game.run_round` itself, so the human's two seats can be played from the
browser while the bot's two replicas run as normal engine players.
