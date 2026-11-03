'''
Plays a Homie Hold'em game between a human in the browser and a bot.

The human's team is A and controls both of its seats, A1 and A2. The selected
bot plays both B seats as ordinary engine players. The worker drives the
engine's Game.run_round itself, so every query reaches us with the full
RoundState. The engine's WEEK picks the rules; see deps/engine-2027/engine.py.
'''
import json

HUMAN_TEAM = 'A'
# Seats are renumbered every round, counting from the small blind.
POSITIONS = ['SB', 'BB', 'UTG', 'BTN']
STREET_NAMES = {0: 'Preflop', 3: 'Flop', 4: 'Turn', 5: 'River'}


class HumanSeat():
    '''
    Stands in for an engine Player: the engine queries it like a bot, and it
    asks the browser instead.
    '''

    def __init__(self, table, name):
        self.table = table
        self.name = name
        self.bankroll = 0

    def query(self, round_state, player_message, game_log):
        if isinstance(round_state, self.table.engine.TerminalState):
            self.table.handle_round_over(round_state)
            return self.table.engine.CheckAction()
        return self.table.get_human_action(round_state)

    def query_submission(self, round_state, player_message, game_log):
        return self.table.get_human_submission(round_state, self.table.seats.index(self))


class BotSeat():
    '''
    Wraps an engine Player so the browser sees each of the bot's actions.
    '''

    def __init__(self, table, player):
        self.table = table
        self.player = player
        self.name = player.name
        self.bankroll = 0

    def query(self, round_state, player_message, game_log):
        action = self.player.query(round_state, player_message, game_log)
        if isinstance(round_state, self.table.engine.RoundState):
            self.table.handle_bot_action(round_state, action)
        return action

    def query_submission(self, round_state, player_message, game_log):
        return self.player.query_submission(round_state, player_message, game_log)


class Table():
    '''
    Runs one playground game and relays it to the browser.
    '''

    def __init__(self, engine, db_game, pubsub, bot_path):
        self.engine = engine
        self.db_game = db_game
        self.pubsub = pubsub
        self.game = engine.Game()
        self.bots = [engine.Player(name, bot_path) for name in ('B1', 'B2')]
        # teams alternate around the table: A1 B1 A2 B2
        self.seats = [HumanSeat(self, 'A1'), BotSeat(self, self.bots[0]),
                      HumanSeat(self, 'A2'), BotSeat(self, self.bots[1])]
        # seats in clockwise order around the table, from the orbit's first small blind
        self.table_order = list(self.seats)
        self.round_num = 0
        self.round_over_sent = False
        self.decision_id = 0
        self.done = False

    def start_bots(self):
        for bot in self.bots:
            bot.build()
        for bot in self.bots:
            bot.run()

    def stop_bots(self):
        for bot in self.bots:
            bot.stop()

    def play(self):
        for round_num in range(1, self.engine.NUM_ROUNDS + 1):
            self.round_num = round_num
            self.round_over_sent = False
            seats = self.game.seat_players(self.seats, round_num)
            if seats is not self.seats:  # a new orbit's seating
                self.seats = seats
                self.table_order = list(seats)
            self.game.run_round(self.seats)
            if self.done:
                break
            self.seats = self.seats[1:] + self.seats[:1]  # the button moves one seat to the left

    def team_bankroll(self, team):
        return sum(seat.bankroll for seat in self.seats if seat.name[:-1] == team)

    def default_action(self, round_state):
        engine = self.engine
        return engine.CheckAction() if engine.CheckAction in round_state.legal_actions() else engine.FoldAction()

    def wait_for_message(self):
        '''
        Returns the next message from the browser, skipping pings. Returns None
        if the browser quit or stopped pinging, and ends the game.
        '''
        while True:
            message = self.pubsub.get_message(timeout=30)
            if message is None:  # no pings, so the browser is gone
                self.done = True
                return None
            if message.get('type') == 'subscribe':
                continue
            data = message['data'].decode('utf-8')
            if data == 'quit_game':
                self.done = True
                return None
            if data != 'ping':
                return data

    def get_human_action(self, round_state):
        if self.done:
            return self.default_action(round_state)
        self.decision_id += 1
        self.send(round_state, 'get_action', decision_id=self.decision_id,
                  legal_moves=self.legal_moves(round_state))
        while True:
            data = self.wait_for_message()
            if data is None:
                return self.default_action(round_state)
            try:
                move = json.loads(data)
            except ValueError:
                continue  # a stray next_hand
            if move.get('decision_id') != self.decision_id:
                continue  # a late click on an earlier decision
            action = self.parse_move(round_state, move)
            if action is not None:
                return action

    def get_human_submission(self, round_state, seat):
        '''
        Asks the browser which card a human seat submits at a Week 2+ showdown.
        '''
        if self.done:
            return None
        self.decision_id += 1
        self.send(round_state, 'get_submission', decision_id=self.decision_id, active_seat=seat,
                  street_name='Showdown')
        while True:
            data = self.wait_for_message()
            if data is None:
                return None
            try:
                move = json.loads(data)
            except ValueError:
                continue  # a stray next_hand
            if move.get('decision_id') != self.decision_id or move.get('type') != 'SUBMIT':
                continue
            if move.get('card_index') in (0, 1, None):
                return move.get('card_index')

    def parse_move(self, round_state, move):
        engine = self.engine
        legal_actions = round_state.legal_actions()
        action_types = {'FOLD': engine.FoldAction, 'CHECK': engine.CheckAction,
                        'CALL': engine.CallAction, 'RAISE': engine.RaiseAction}
        action_type = action_types.get(move.get('type'))
        if action_type not in legal_actions:
            return None
        if action_type is engine.RaiseAction:
            min_raise, max_raise = round_state.raise_bounds()
            try:
                amount = int(move['amount'])
            except (KeyError, TypeError, ValueError):
                return None
            return engine.RaiseAction(amount) if min_raise <= amount <= max_raise else None
        return action_type()

    def handle_bot_action(self, round_state, action):
        if self.done:
            return
        next_state = round_state.proceed(action)
        if isinstance(next_state, self.engine.RoundState):  # otherwise the round-over message shows it
            self.send(next_state, 'bot_action')

    def handle_round_over(self, terminal_state):
        '''
        Shows the result and waits for the next hand. Both human seats are
        queried at the end of the round; only the first one does anything.
        '''
        if self.round_over_sent or self.done:
            return
        self.round_over_sent = True
        engine = self.engine
        round_state = terminal_state.previous_state
        deltas = terminal_state.deltas
        submitted = terminal_state.submitted
        live = round_state.live()
        hand_names = [None] * engine.NUM_PLAYERS
        if engine.WEEK == 1 and len(live) > 1:  # showdown
            for seat in live:
                hand_names[seat] = engine.pkrbot.handtype(engine.pkrbot.evaluate(round_state.runout + round_state.hands[seat]))
        elif submitted is not None:  # team showdown
            for seat in live:
                cards = [round_state.hands[mate][submitted[mate]] for mate in live
                         if self.seats[mate].name[:-1] == self.seats[seat].name[:-1] and submitted[mate] is not None]
                hand_names[seat] = engine.pkrbot.handtype(engine.pkrbot.evaluate(round_state.runout + cards))
        team_delta = sum(delta for seat, delta in zip(self.seats, deltas) if seat.name[:-1] == HUMAN_TEAM)
        self.send(round_state, 'round_over', deltas=deltas,
                  shown=[seat for seat in live if hand_names[seat] is not None],
                  submitted=submitted, hand_names=hand_names,
                  result='win' if team_delta > 0 else ('loss' if team_delta < 0 else 'tie'),
                  team_delta=team_delta,
                  new_team_bankrolls={team: self.team_bankroll(team) + sum(
                      delta for seat, delta in zip(self.seats, deltas) if seat.name[:-1] == team)
                      for team in ('A', 'B')})
        while True:
            data = self.wait_for_message()
            if data is None or data == 'next_hand':
                return

    def legal_moves(self, round_state):
        engine = self.engine
        legal_actions = round_state.legal_actions()
        active = round_state.active
        top = max(round_state.pips)
        moves = []
        if engine.FoldAction in legal_actions:
            moves.append({'type': 'FOLD', 'cost': 0})
        if engine.CheckAction in legal_actions:
            moves.append({'type': 'CHECK', 'cost': 0})
        if engine.CallAction in legal_actions:
            moves.append({'type': 'CALL', 'cost': min(top - round_state.pips[active], round_state.stacks[active])})
        if engine.RaiseAction in legal_actions:
            min_raise, max_raise = round_state.raise_bounds()
            moves.append({'type': 'BET' if top == 0 else 'RAISE', 'min': min_raise, 'max': max_raise,
                          'pip': round_state.pips[active]})
        return moves

    def action_history(self, round_state):
        '''
        Rebuilds the round's actions from the chain of previous states.
        '''
        chain = []
        state = round_state
        while state is not None:
            chain.append(state)
            state = state.previous_state
        chain.reverse()
        names = [seat.name for seat in self.seats]
        history = [{'type': 'POST', 'player': names[0], 'amount': self.engine.SMALL_BLIND},
                   {'type': 'POST', 'player': names[1], 'amount': self.engine.BIG_BLIND}]
        for before, after in zip(chain, chain[1:]):
            if after.street != before.street:
                history.append({'type': 'DEAL', 'street': STREET_NAMES[after.street]})
                continue
            seat = before.active
            top = max(before.pips)
            move = {'player': names[seat]}
            if after.folded[seat] and not before.folded[seat]:
                move['type'] = 'FOLD'
            elif after.pips[seat] == before.pips[seat]:
                move['type'] = 'CHECK'
            elif after.pips[seat] <= top:
                move['type'] = 'CALL'
            else:
                move['type'] = 'BET' if top == 0 else 'RAISE'
                move['amount'] = after.pips[seat]
            history.append(move)
        return history

    def send(self, round_state, status, deltas=None, shown=(), submitted=None, hand_names=None, **extra):
        '''
        Sends the browser the table as the human sees it. shown lists the
        seats whose cards were revealed at showdown.
        '''
        seats = []
        for index, seat in enumerate(self.seats):
            human = seat.name[:-1] == HUMAN_TEAM
            seats.append({
                'name': seat.name,
                'team': seat.name[:-1],
                'human': human,
                'position': POSITIONS[index],
                'table_position': self.table_order.index(seat),  # clockwise
                'stack': round_state.stacks[index],
                'pip': round_state.pips[index],
                'contribution': round_state.contributions[index],
                'folded': round_state.folded[index],
                'cards': [str(card) for card in round_state.hands[index]]
                         if human or index in shown else ['??', '??'],
                'bankroll': seat.bankroll,
                'delta': deltas[index] if deltas else None,
                'submitted': None if submitted is None or submitted[index] is None
                             else str(round_state.hands[index][submitted[index]]),
                'hand_name': hand_names[index] if hand_names else None,
            })
        message = {
            'status': status,
            'week': self.engine.WEEK,
            'round_num': self.round_num,
            # hands into the orbit, which reseats the table from Week 3
            'orbit_hand': (self.round_num - 1) % self.engine.NUM_PLAYERS + 1,
            'num_rounds': self.engine.NUM_ROUNDS,
            'street_name': STREET_NAMES[round_state.street],
            'board_cards': [str(card) for card in round_state.board],
            'pot': sum(round_state.contributions),
            'active_seat': None if status == 'round_over' else round_state.active,
            'seats': seats,
            'team_bankrolls': {team: self.team_bankroll(team) for team in ('A', 'B')},
            'move_history': self.action_history(round_state),
        }
        message.update(extra)
        self.db_game.send_message(message)
