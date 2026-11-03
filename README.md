# playground
Play against your pokerbot online!

The 2027 variant is Homie Hold'em: four seats, two per team. In the playground
the human plays both of team A's seats (A1 and A2) against two copies of the
chosen bot (B1 and B2), under the rules of Week 1, 2 or 3, picked on the home
page. Games are 100 hands, with 200 chips per seat each hand.

The worker imports the engine (`deps/engine-2027/engine.py`, scrimmage's
`game/engine.py` plus Weeks 2 and 3; see its README) and drives its
`Game.run_round` from `server/bot.py`, which relays the human seats' decisions
and each bot action to the browser. The `games.week` column needs the migration
in `migrations/versions/b2f7c41d9a63_.py` on an existing database.

# Instructions to run (similar to scrimmage):
To run locally (cd into directory first), do:

- `brew install rabbitmq scons boost postgres redis` (Optional)
- `initdb --username=postgres ~/pbots; pg_ctl -D ~/pbots -l logfile start; createdb -U postgres pbots`
- `pip install -r requirements.txt`
- Run `from server import db; db.create_all()` from a python3 shell

To run the server and worker, run in separate tabs:

- `sudo rabbitmq-server`
- `redis-server`
- `python manage.py runserver`
- `celery -A server.celery_app worker --loglevel=info --concurrency=1`

Then to run the frontend do:

- `cd client`
- `npm install` (the first time you use it)
- `npm start`

### To import bots into playground
When you originally spin up playground, there are no bots and we need to manually import them.
Bots can be imported by going to the /admin route (like localhost:5001/admin), providing the username and password, and then filling out the text for bots.

In dev environment (local testing), you can enter some dummy value like so: `{"teams": [{"name": "local", "bots": [{"name": "test_bot", "s3_key": "none"}]}]}`, and you can challenge the test bot in `deps/test_bot.zip`.

In prod (once deployed), you can use the "export to playground" button in scrimmage to make all the current bots visible.
