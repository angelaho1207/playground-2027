'''
6.9630 MIT POKERBOTS GAME ENGINE
DO NOT REMOVE, RENAME, OR EDIT THIS FILE

Homie Hold'em: no-limit Texas hold'em at a table of four. Each team's bot plays
as two identical replicas in alternating seats (A1 B1 A2 B2), and a team's
score is the sum of its replicas' bankrolls.

WEEK in config.py picks the rules, and each week keeps the ones before it:
1. The base game above.
2. At showdown each team plays one combined hand: every live player submits
   one of its hole cards, or none, and the team's hand is the best five
   cards from the board plus those submissions. A hand also ends as soon as
   only one team has players left.
3. Seating is shuffled every orbit of NUM_PLAYERS hands, so teammates may
   sit next to each other. Each player is told its teammates' seats.
'''
from collections import namedtuple
from threading import Thread
from queue import Queue
import time
import json
import random
import subprocess
import socket
import pkrbot ###import eval7, but better
import sys
import os

sys.path.append(os.getcwd())
from config import *

try:
    WEEK
except NameError:  # config files from before Week 2 don't set it
    WEEK = 1

FoldAction = namedtuple('FoldAction', [])
CallAction = namedtuple('CallAction', [])
CheckAction = namedtuple('CheckAction', [])
# we coalesce BetAction and RaiseAction for convenience
RaiseAction = namedtuple('RaiseAction', ['amount'])

# submitted[seat] is the index of the hole card a seat submitted at a Week 2+
# showdown, or None; submitted is None for a round that had no such showdown
TerminalState = namedtuple('TerminalState', ['deltas', 'previous_state', 'submitted'], defaults=[None])
# the river's betting is over and the live players must submit cards (Week 2+)
SubmissionState = namedtuple('SubmissionState', ['previous_state'])

REPLICAS = 2  # copies of each team's bot at the table
NUM_PLAYERS = 2 * REPLICAS
STREET_NAMES = {3: 'Flop', 4: 'Turn', 5: 'River'}
DECODE = {'F': FoldAction, 'C': CallAction, 'K': CheckAction, 'R': RaiseAction}
CCARDS = lambda cards: ','.join(map(str, cards))
PCARDS = lambda cards: '[{}]'.format(' '.join(map(str, cards)))
PVALUE = lambda name, value: ', {} ({})'.format(name, value)
STATUS = lambda pairs: ''.join(PVALUE(name, value) for name, value in pairs)

# Seats are renumbered every round, counting from the small blind:
# 0 small blind, 1 big blind, 2 first to act preflop, 3 dealer.
# Until Week 3, teams alternate around the table, so teammates are always 2
# seats apart.
#
# Socket encoding scheme:
#
# T#.### the player's game clock
# P# the player's seat this round
# M#,# the player's teammates' seats this round (Week 3+)
# H**,** the player's hand in common format
# F a fold action in the round history
# C a call action in the round history
# K a check action in the round history
# R### a raise action in the round history (the raiser's new pip)
# B**,**,**,**,** the board cards in common format
# S a request to submit a hole card for the team's hand (Week 2+)
# O#:**,** the hand shown by seat # at showdown
# U#:** the card seat # submitted at showdown, or U#: for none (Week 2+)
# A#,#,#,# every seat's bankroll delta from the round, in seat order
# Q game over
#
# Clauses are separated by spaces
# Messages end with '\n'
# The engine expects a response of K at the end of the round as an ack,
# S0 or S1 (the index of the card in the player's hand) or S (no card) to a
# submission request, otherwise a response which encodes the player's action
# Action history is sent once, including the player's actions


class RoundState(namedtuple('_RoundState', ['active', 'street', 'pips', 'stacks', 'contributions', 'acted',
                                            'folded', 'min_raise', 'hands', 'runout', 'previous_state'])):
    '''
    Encodes the game tree for one round of poker.

    active is the seat to act. pips are this street's bets and contributions
    the whole round's. acted[seat] is the top bet on this street right after
    the seat last acted on it (-1 if it has not acted yet). min_raise is the
    smallest legal raise amount: the last full bet or raise on this street, at
    least the big blind. runout holds all five board cards, of which the first
    `street` are dealt.

    Betting is standard no-limit: anyone may bet or raise up to their whole
    stack, even more than anyone else can call (the part no one matched comes
    back at showdown, through the side pots). An all-in raise smaller than a
    full raise does not reopen the betting to a seat that has already acted.
    '''

    @property
    def board(self):
        '''
        The board cards dealt so far.
        '''
        return self.runout[:self.street]

    def live(self):
        '''
        The seats that have not folded.
        '''
        return [seat for seat in range(NUM_PLAYERS) if not self.folded[seat]]

    def bettors(self):
        '''
        The seats that can still bet: not folded and not all in.
        '''
        return [seat for seat in self.live() if self.stacks[seat] > 0]

    def pending(self):
        '''
        The seats that still have to act on this street: those that can bet and
        have not acted since the last bet or raise. A lone seat with chips that
        owes nothing has no one to bet against, so it does not act.
        '''
        top = max(self.pips)
        bettors = self.bettors()
        if len(bettors) == 1 and self.pips[bettors[0]] == top:
            return []
        return [seat for seat in bettors if self.acted[seat] < top]

    def settle(self, scores):
        '''
        Pays out the main pot and the side pots. scores[seat] is the strength of
        a seat's hand, or None if it folded. Each pot goes to the best hand among
        the live seats that paid into all of it; tied seats split it, and odd
        chips go to the tied seat nearest the small blind. Chips no live seat
        matched (an uncalled bet, or folded seats' money above every live seat)
        are in the top pot.
        '''
        contributions = self.contributions
        winnings = [0] * NUM_PLAYERS
        live = [seat for seat in range(NUM_PLAYERS) if scores[seat] is not None]
        levels = sorted({contributions[seat] for seat in live})
        floor = 0
        for i, level in enumerate(levels):
            cap = level if i + 1 < len(levels) else max(contributions)
            pot = sum(min(c, cap) - min(c, floor) for c in contributions)
            eligible = [seat for seat in live if contributions[seat] >= level]
            best = max(scores[seat] for seat in eligible)
            winners = [seat for seat in eligible if scores[seat] == best]
            share, odd = divmod(pot, len(winners))
            for j, seat in enumerate(winners):
                winnings[seat] += share + (j < odd)
            floor = cap
        return TerminalState([w - c for w, c in zip(winnings, contributions)], self)

    def settle_teams(self, teams, submitted):
        '''
        Pays out a Week 2+ showdown. teams[seat] names each seat's team. A
        team's hand is the board plus every card its live players submitted.
        Each pot goes to the best hand among the teams with a live seat that
        paid into all of it, and is shared among that team's seats that did;
        tied teams split it. Odd chips go to the team, then the seat, nearest
        the small blind.
        '''
        contributions = self.contributions
        live = self.live()
        team_cards = {}
        for seat in live:
            cards = team_cards.setdefault(teams[seat], [])
            if submitted[seat] is not None:
                cards.append(self.hands[seat][submitted[seat]])
        scores = {team: pkrbot.evaluate(self.runout + cards) for team, cards in team_cards.items()}
        winnings = [0] * NUM_PLAYERS
        levels = sorted({contributions[seat] for seat in live})
        floor = 0
        for i, level in enumerate(levels):
            cap = level if i + 1 < len(levels) else max(contributions)
            pot = sum(min(c, cap) - min(c, floor) for c in contributions)
            eligible = [seat for seat in live if contributions[seat] >= level]
            eligible_teams = list(dict.fromkeys(teams[seat] for seat in eligible))
            best = max(scores[team] for team in eligible_teams)
            winners = [team for team in eligible_teams if scores[team] == best]
            team_share, team_odd = divmod(pot, len(winners))
            for j, team in enumerate(winners):
                seats = [seat for seat in eligible if teams[seat] == team]
                share, odd = divmod(team_share + (j < team_odd), len(seats))
                for k, seat in enumerate(seats):
                    winnings[seat] += share + (k < odd)
            floor = cap
        return TerminalState([w - c for w, c in zip(winnings, contributions)], self, submitted)

    def showdown(self):
        '''
        Compares the live players' hands and computes the final payoffs. From
        Week 2 the players must first submit their cards.
        '''
        if WEEK >= 2:
            return SubmissionState(self)
        return self.settle([None if self.folded[seat] else pkrbot.evaluate(self.runout + self.hands[seat])
                            for seat in range(NUM_PLAYERS)])

    def raise_bounds(self):
        '''
        Returns a tuple of the minimum and maximum legal raises (the raiser's new pip).
        A raise smaller than the minimum is legal only all in.
        '''
        max_raise = self.pips[self.active] + self.stacks[self.active]
        return (min(max(self.pips) + self.min_raise, max_raise), max_raise)

    def legal_actions(self):
        '''
        Returns a set which corresponds to the active player's legal moves.
        '''
        active = self.active
        top = max(self.pips)
        continue_cost = top - self.pips[active]
        actions = {FoldAction, CheckAction} if continue_cost == 0 else {FoldAction, CallAction}
        reopened = self.acted[active] < 0 or top - self.acted[active] >= self.min_raise
        if self.stacks[active] > continue_cost and len(self.bettors()) > 1 and reopened:
            actions.add(RaiseAction)
        return actions

    def proceed_street(self):
        '''
        Resets the players' pips and advances the game tree to the next street,
        or to showdown after the river. A street on which fewer than two players
        can bet has no betting: no one is pending.
        '''
        if self.street == 5:
            return self.showdown()
        state = RoundState(0, 3 if self.street == 0 else self.street + 1, [0] * NUM_PLAYERS, self.stacks,
                           self.contributions, (-1,) * NUM_PLAYERS, self.folded, BIG_BLIND, self.hands,
                           self.runout, self)
        pending = state.pending()
        return state._replace(active=pending[0]) if pending else state

    def proceed(self, action):
        '''
        Advances the game tree by one action performed by the active player.
        '''
        active = self.active
        top = max(self.pips)
        folded = self.folded
        min_raise = self.min_raise
        amount = 0
        if isinstance(action, FoldAction):
            folded = folded[:active] + (True,) + folded[active + 1:]
        elif isinstance(action, CallAction):
            amount = min(top - self.pips[active], self.stacks[active])  # all in for less if short
        elif isinstance(action, RaiseAction):
            amount = action.amount - self.pips[active]
            min_raise = max(min_raise, action.amount - top)  # only a full raise sets a new minimum
        pips = list(self.pips)
        stacks = list(self.stacks)
        contributions = list(self.contributions)
        pips[active] += amount
        stacks[active] -= amount
        contributions[active] += amount
        acted = self.acted[:active] + (max(pips),) + self.acted[active + 1:]
        state = RoundState(active, self.street, pips, stacks, contributions, acted, folded, min_raise,
                           self.hands, self.runout, self)
        if folded.count(False) == 1:  # everyone else folded
            return state.settle([None if out else 0 for out in folded])
        pending = state.pending()
        if not pending:
            return state.proceed_street()
        return state._replace(active=min(pending, key=lambda seat: (seat - active) % NUM_PLAYERS))


class Player():
    '''
    Handles subprocess and socket interactions with one player's pokerbot.
    '''

    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.game_clock = STARTING_GAME_CLOCK
        self.bankroll = 0
        self.commands = None
        self.bot_subprocess = None
        self.socketfile = None
        self.bytes_queue = Queue()

    def build(self):
        '''
        Loads the commands file and builds the pokerbot.
        '''
        try:
            with open(self.path + '/commands.json', 'r') as json_file:
                commands = json.load(json_file)
            if ('build' in commands and 'run' in commands and
                    isinstance(commands['build'], list) and
                    isinstance(commands['run'], list)):
                self.commands = commands
            else:
                print(self.name, 'commands.json missing command')
        except FileNotFoundError:
            print(self.name, 'commands.json not found - check PLAYER_PATH')
        except json.decoder.JSONDecodeError:
            print(self.name, 'commands.json misformatted')
        if self.commands is not None and len(self.commands['build']) > 0:
            try:
                proc = subprocess.run(self.commands['build'],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      cwd=self.path, timeout=BUILD_TIMEOUT, check=False)
                self.bytes_queue.put(proc.stdout)
            except subprocess.TimeoutExpired as timeout_expired:
                error_message = 'Timed out waiting for ' + self.name + ' to build'
                print(error_message)
                self.bytes_queue.put(timeout_expired.stdout)
                self.bytes_queue.put(error_message.encode())
            except (TypeError, ValueError):
                print(self.name, 'build command misformatted')
            except OSError:
                print(self.name, 'build failed - check "build" in commands.json')

    def run(self):
        '''
        Runs the pokerbot and establishes the socket connection.
        '''
        if self.commands is not None and len(self.commands['run']) > 0:
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                with server_socket:
                    server_socket.bind(('', 0))
                    server_socket.settimeout(CONNECT_TIMEOUT)
                    server_socket.listen()
                    port = server_socket.getsockname()[1]
                    proc = subprocess.Popen(self.commands['run'] + [str(port)],
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            cwd=self.path)
                    self.bot_subprocess = proc
                    # function for bot listening
                    def enqueue_output(out, queue):
                        try:
                            for line in out:
                                if self.path == r"./player_chatbot":
                                    print(line.strip().decode("utf-8"))
                                else:
                                    queue.put(line)
                        except ValueError:
                            pass
                    # start a separate bot listening thread which dies with the program
                    Thread(target=enqueue_output, args=(proc.stdout, self.bytes_queue), daemon=True).start()
                    # block until we timeout or the player connects
                    client_socket, _ = server_socket.accept()
                    with client_socket:
                        if self.path == r"./player_chatbot":
                            client_socket.settimeout(PLAYER_TIMEOUT)
                        else:
                            client_socket.settimeout(CONNECT_TIMEOUT)
                        sock = client_socket.makefile('rw')
                        self.socketfile = sock
                        print(self.name, 'connected successfully')
            except (TypeError, ValueError):
                print(self.name, 'run command misformatted')
            except OSError:
                print(self.name, 'run failed - check "run" in commands.json')
            except socket.timeout:
                print('Timed out waiting for', self.name, 'to connect')

    def stop(self):
        '''
        Closes the socket connection and stops the pokerbot.
        '''
        if self.socketfile is not None:
            try:
                self.socketfile.write('Q\n')
                self.socketfile.close()
            except socket.timeout:
                print('Timed out waiting for', self.name, 'to disconnect')
            except OSError:
                print('Could not close socket connection with', self.name)
        if self.bot_subprocess is not None:
            try:
                if self.path == r"./player_chatbot":
                    outs, _ = self.bot_subprocess.communicate(timeout=PLAYER_TIMEOUT)
                else:
                    outs, _ = self.bot_subprocess.communicate(timeout=CONNECT_TIMEOUT)
                self.bytes_queue.put(outs)
            except subprocess.TimeoutExpired:
                print('Timed out waiting for', self.name, 'to quit')
                self.bot_subprocess.kill()
                outs, _ = self.bot_subprocess.communicate()
                self.bytes_queue.put(outs)
        with open(self.name + '.txt', 'wb') as log_file:
            bytes_written = 0
            for output in self.bytes_queue.queue:
                try:
                    bytes_written += log_file.write(output)
                    if bytes_written >= PLAYER_LOG_SIZE_LIMIT:
                        break
                except TypeError:
                    pass

    def query(self, round_state, player_message, game_log):
        '''
        Requests one action from the pokerbot over the socket connection.
        At the end of the round, we request a CheckAction from the pokerbot.

        A bot that sends an illegal or misformatted action checks if it can,
        and folds otherwise. A bot that disconnects or runs out of time has its
        game clock set to 0 and does the same for the rest of the game.
        '''
        legal_actions = round_state.legal_actions() if isinstance(round_state, RoundState) else {CheckAction}
        if self.socketfile is not None and self.game_clock > 0.:
            clause = ''
            try:
                player_message[0] = 'T{:.3f}'.format(self.game_clock)
                message = ' '.join(player_message) + '\n'
                del player_message[1:]  # do not send redundant action history
                start_time = time.perf_counter()
                self.socketfile.write(message)
                self.socketfile.flush()
                line = self.socketfile.readline()
                end_time = time.perf_counter()
                if not line:  # the bot closed the connection
                    raise ConnectionError
                clause = line.strip()
                if ENFORCE_GAME_CLOCK and self.path != r"./player_chatbot":
                    self.game_clock -= end_time - start_time
                if self.game_clock <= 0.:
                    raise socket.timeout
                action = DECODE[clause[0]]
                if action in legal_actions:
                    if clause[0] == 'R':
                        amount = int(clause[1:])
                        min_raise, max_raise = round_state.raise_bounds()
                        if min_raise <= amount <= max_raise:
                            return action(amount)
                        game_log.append(self.name + ' attempted illegal raise to ' + str(amount))
                    else:
                        return action()
                else:
                    game_log.append(self.name + ' attempted illegal ' + action.__name__)
            except socket.timeout:
                error_message = self.name + ' ran out of time'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except OSError:
                error_message = self.name + ' disconnected'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except (IndexError, KeyError, ValueError):
                game_log.append(self.name + ' response misformatted: ' + str(clause))
        return CheckAction() if CheckAction in legal_actions else FoldAction()

    def query_submission(self, round_state, player_message, game_log):
        '''
        Requests the index of the hole card to submit for the team's hand at
        a Week 2+ showdown, or None for no card.

        A bot that sends a misformatted response, disconnects or runs out of
        time submits no card.
        '''
        if self.socketfile is not None and self.game_clock > 0.:
            clause = ''
            try:
                player_message[0] = 'T{:.3f}'.format(self.game_clock)
                message = ' '.join(player_message + ['S']) + '\n'
                del player_message[1:]  # do not send redundant action history
                start_time = time.perf_counter()
                self.socketfile.write(message)
                self.socketfile.flush()
                line = self.socketfile.readline()
                end_time = time.perf_counter()
                if not line:  # the bot closed the connection
                    raise ConnectionError
                clause = line.strip()
                if ENFORCE_GAME_CLOCK and self.path != r"./player_chatbot":
                    self.game_clock -= end_time - start_time
                if self.game_clock <= 0.:
                    raise socket.timeout
                if clause[0] != 'S':
                    raise ValueError
                if clause == 'S':
                    return None
                index = int(clause[1:])
                if index in (0, 1):
                    return index
                game_log.append(self.name + ' attempted to submit card ' + str(index))
            except socket.timeout:
                error_message = self.name + ' ran out of time'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except OSError:
                error_message = self.name + ' disconnected'
                game_log.append(error_message)
                print(error_message)
                self.game_clock = 0.
            except (IndexError, ValueError):
                game_log.append(self.name + ' response misformatted: ' + str(clause))
        return None


class Game():
    '''
    Manages logging and the high-level game procedure.
    '''

    def __init__(self):
        self.teams = [(PLAYER_1_NAME, PLAYER_1_PATH), (PLAYER_2_NAME, PLAYER_2_PATH)]
        self.log = ['6.9630 MIT Pokerbots - ' + PLAYER_1_NAME + ' vs ' + PLAYER_2_NAME]
        self.player_messages = [[] for _ in range(NUM_PLAYERS)]

    def log_round_state(self, players, round_state):
        '''
        Incorporates RoundState information into the game log and player messages.
        Called once at the start of each street.
        '''
        if round_state.street == 0:
            self.log.append('{} posts the blind of {}'.format(players[0].name, SMALL_BLIND))
            self.log.append('{} posts the blind of {}'.format(players[1].name, BIG_BLIND))
            for seat, player in enumerate(players):
                self.log.append('{} dealt {}'.format(player.name, PCARDS(round_state.hands[seat])))
                self.player_messages[seat] = ['T0.', 'P' + str(seat), 'H' + CCARDS(round_state.hands[seat])]
                if WEEK >= 3:
                    teammates = [other for other, mate in enumerate(players)
                                 if other != seat and mate.name[:-1] == player.name[:-1]]
                    self.player_messages[seat].insert(2, 'M' + ','.join(map(str, teammates)))
        else:
            board = round_state.board
            self.log.append(STREET_NAMES[round_state.street] + ' ' + PCARDS(board) +
                            STATUS((player.name, contribution)
                                   for player, contribution in zip(players, round_state.contributions)))
            for message in self.player_messages:
                message.append('B' + CCARDS(board))

    def log_action(self, name, action, bet_override):
        '''
        Incorporates action information into the game log and player messages.
        '''
        if isinstance(action, FoldAction):
            phrasing = ' folds'
            code = 'F'
        elif isinstance(action, CallAction):
            phrasing = ' calls'
            code = 'C'
        elif isinstance(action, CheckAction):
            phrasing = ' checks'
            code = 'K'
        else:  # isinstance(action, RaiseAction)
            phrasing = (' bets ' if bet_override else ' raises to ') + str(action.amount)
            code = 'R' + str(action.amount)
        self.log.append(name + phrasing)
        for message in self.player_messages:
            message.append(code)

    def log_terminal_state(self, players, round_state):
        '''
        Incorporates TerminalState information into the game log and player messages.
        '''
        previous_state = round_state.previous_state
        live = previous_state.live()
        showdown = len(live) > 1 if WEEK == 1 else round_state.submitted is not None
        if showdown:
            for seat in live:
                self.log.append('{} shows {}'.format(players[seat].name, PCARDS(previous_state.hands[seat])))
                for viewer, message in enumerate(self.player_messages):
                    if viewer != seat:
                        message.append('O{}:{}'.format(seat, CCARDS(previous_state.hands[seat])))
            if round_state.submitted is not None:
                for seat in live:
                    index = round_state.submitted[seat]
                    card = '' if index is None else str(previous_state.hands[seat][index])
                    self.log.append('{} submitted {}'.format(players[seat].name, card or 'no card'))
                    for message in self.player_messages:
                        message.append('U{}:{}'.format(seat, card))
        for player, delta in zip(players, round_state.deltas):
            self.log.append('{} awarded {}'.format(player.name, delta))
        for message in self.player_messages:
            message.append('A' + ','.join(map(str, round_state.deltas)))

    def run_round(self, players):
        '''
        Runs one round of poker.
        '''
        deck = pkrbot.Deck()  # a fresh deck, and so a freshly seeded shuffle, every round
        deck.shuffle()
        cards = deck.peek(2 * NUM_PLAYERS + 5)
        hands = [cards[2 * seat:2 * seat + 2] for seat in range(NUM_PLAYERS)]
        pips = [SMALL_BLIND, BIG_BLIND] + [0] * (NUM_PLAYERS - 2)
        stacks = [STARTING_STACK - pip for pip in pips]
        round_state = RoundState(2 % NUM_PLAYERS, 0, pips, stacks, list(pips), (-1,) * NUM_PLAYERS,
                                 (False,) * NUM_PLAYERS, BIG_BLIND, hands, cards[2 * NUM_PLAYERS:], None)
        teams = [player.name[:-1] for player in players]
        street = None
        while not isinstance(round_state, TerminalState):
            if isinstance(round_state, SubmissionState):
                round_state = self.run_submissions(players, round_state.previous_state)
                continue
            if round_state.street != street:
                street = round_state.street
                self.log_round_state(players, round_state)
            if not round_state.pending():
                round_state = round_state.proceed_street()
                continue
            active = round_state.active
            player = players[active]
            action = player.query(round_state, self.player_messages[active], self.log)
            self.log_action(player.name, action, max(round_state.pips) == 0)
            round_state = round_state.proceed(action)
            if WEEK >= 2 and isinstance(round_state, (RoundState, SubmissionState)):
                state = round_state.previous_state if isinstance(round_state, SubmissionState) else round_state
                if len({teams[seat] for seat in state.live()}) == 1:  # one team left: it takes the pot
                    round_state = state.settle([None if out else 0 for out in state.folded])
        self.log_terminal_state(players, round_state)
        for player, player_message, delta in zip(players, self.player_messages, round_state.deltas):
            player.query(round_state, player_message, self.log)
            player.bankroll += delta

    def run_submissions(self, players, round_state):
        '''
        Asks each live player for its card, privately, and pays out the team showdown.
        '''
        submitted = [None] * NUM_PLAYERS
        for seat in round_state.live():
            submitted[seat] = players[seat].query_submission(round_state, self.player_messages[seat], self.log)
        return round_state.settle_teams([player.name[:-1] for player in players], submitted)

    def seat_players(self, players, round_num):
        '''
        Returns the seating for a round, given the last round's. From Week 3
        every orbit starts with a new random seating and button.
        '''
        if WEEK >= 3 and round_num % NUM_PLAYERS == 1:
            return random.sample(players, len(players))
        return players

    def run(self):
        '''
        Runs one game of poker.
        '''
        print('   __  _____________  ___       __           __        __    ')
        print('  /  |/  /  _/_  __/ / _ \\___  / /_____ ____/ /  ___  / /____')
        print(' / /|_/ // /  / /   / ___/ _ \\/  \'_/ -_) __/ _ \\/ _ \\/ __(_-<')
        print('/_/  /_/___/ /_/   /_/   \\___/_/\\_\\\\__/_/ /_.__/\\___/\\__/___/')
        print()
        print('Starting the Pokerbots engine...')
        # teams alternate around the table: A1 B1 A2 B2
        players = [Player(name + str(replica), path)
                   for replica in range(1, REPLICAS + 1) for name, path in self.teams]
        for player in players:
            player.build()
        for player in players:
            player.run()
        for round_num in range(1, NUM_ROUNDS + 1):
            players = self.seat_players(players, round_num)
            self.log.append('')
            self.log.append('Round #' + str(round_num) + STATUS((p.name, p.bankroll) for p in players))
            self.run_round(players)
            players = players[1:] + players[:1]  # the button moves one seat to the left
        self.log.append('')
        self.log.append('Final' + STATUS((name, sum(p.bankroll for p in players if p.name[:-1] == name))
                                         for name, _ in self.teams))
        for player in players:
            player.stop()
        name = GAME_LOG_FILENAME + '.txt'
        print('Writing', name)
        with open(name, 'w') as log_file:
            log_file.write('\n'.join(self.log))


if __name__ == '__main__':
    Game().run()
