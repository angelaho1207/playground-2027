import React, { Component } from "react";
import {
  Header,
  Icon,
  Container,
  Segment,
  Button,
  Grid,
  Feed,
  Divider,
  Statistic,
  Label,
  Dropdown,
} from "semantic-ui-react";
import Slider from "rc-slider";
import "rc-slider/assets/index.css";
import { withRouter } from "react-router-dom";

import { SocketConsumer } from "./SocketContext";

// Seats sit clockwise A1, B1, A2, B2, so teammates face each other.
const TABLE_LAYOUT = { top: "A2", left: "B1", right: "B2", bottom: "A1" };

const BOT_DELAY_OPTIONS = [
  { key: 0, text: "Instant", value: 0 },
  { key: 400, text: "Fast", value: 400 },
  { key: 900, text: "Normal", value: 900 },
  { key: 1600, text: "Slow", value: 1600 },
];
const DEFAULT_BOT_DELAY = 900;
const BOT_DELAY_STORAGE_KEY = "botDelay";

const readBotDelay = () => {
  try {
    const stored = window.localStorage.getItem(BOT_DELAY_STORAGE_KEY);
    return stored === null ? DEFAULT_BOT_DELAY : parseInt(stored, 10);
  } catch (e) {
    return DEFAULT_BOT_DELAY;
  }
};

// The card images are 691x1056.
const CARD_WIDTH = 56;
const cardStyle = {
  display: "inline-block",
  verticalAlign: "middle",
  width: CARD_WIDTH,
  height: Math.round((CARD_WIDTH * 1056) / 691),
  margin: "0 0.25em",
  borderRadius: "5px",
};

const PlaceholderCard = () => {
  return <div style={{ ...cardStyle, border: "1px dashed grey" }} />;
};

const Card = (props) => {
  const card = props.card;

  if (card === "??") {
    return (
      <div style={{ ...cardStyle, border: "1px solid grey", backgroundColor: "green" }} />
    );
  }
  return (
    <img
      src={`/cards/${card[0] + card[1].toLowerCase()}.jpg`}
      style={cardStyle}
      alt={card}
    />
  );
};

class Game extends Component {
  constructor(props) {
    super(props);

    this.state = {
      status: "loading",
      game: null,
      selected_amount: 0,
      min_amount: null,
      max_amount: null,
      pingInterval: null,
      botDelay: readBotDelay(),
    };
    // Updates wait here so the bots' actions play out one at a time.
    this.updateQueue = [];
    this.updateTimer = null;
    this.shownAt = 0;
  }

  componentDidMount() {
    this.props.socket.emit(
      "join_game",
      this.props.match.params.id,
      (result) => {
        this.setState({
          status: "loaded",
          pingInterval: setInterval(() => {
            this.props.socket.emit("game_ping", this.props.match.params.id);
          }, 2000),
        });
        this.showGame(result);
      }
    );

    this.props.socket.on("game_update", this.handleGameUpdate);
  }

  componentWillUnmount() {
    this.props.socket.off("game_update", this.handleGameUpdate);
    clearInterval(this.state.pingInterval);
    clearTimeout(this.updateTimer);
  }

  handleGameUpdate = (newGame) => {
    this.updateQueue.push(newGame);
    this.scheduleNextUpdate();
  };

  scheduleNextUpdate = () => {
    if (this.updateTimer !== null || this.updateQueue.length === 0) {
      return;
    }
    const shown = this.state.game && this.state.game.last_message;
    const wait =
      shown && shown.status === "bot_action"
        ? Math.max(0, this.state.botDelay - (Date.now() - this.shownAt))
        : 0;
    this.updateTimer = setTimeout(() => {
      this.updateTimer = null;
      this.showGame(this.updateQueue.shift());
      this.scheduleNextUpdate();
    }, wait);
  };

  showGame = (newGame) => {
    var min_amount = null;
    var max_amount = null;
    if (newGame && newGame.last_message && newGame.last_message.legal_moves) {
      newGame.last_message.legal_moves.forEach((move) => {
        if (move.min !== undefined) {
          min_amount = move.min;
          max_amount = move.max;
        }
      });
    }

    this.shownAt = Date.now();
    this.setState({
      game: newGame,
      selected_amount: min_amount,
      min_amount,
      max_amount,
    });
  };

  handleBotDelayChange = (e, { value }) => {
    try {
      window.localStorage.setItem(BOT_DELAY_STORAGE_KEY, String(value));
    } catch (e) {
      // the delay just isn't remembered
    }
    this.setState({ botDelay: value });
  };

  seatLabel(seatName) {
    if (seatName.startsWith("A")) {
      return `You (${seatName})`;
    }
    return `${this.state.game.bot.team} (${seatName})`;
  }

  renderGameLog() {
    var log = this.state.game.last_message.move_history.slice().reverse();

    const actionToPastTense = {
      BET: "bet",
      RAISE: "raised to",
      CALL: "called",
      FOLD: "folded",
      CHECK: "checked",
    };

    const playerColor = (player) => {
      if (player === undefined) return "grey"; // the table
      return player.startsWith("A") ? "#016699" : "black";
    };

    return (
      <Feed size="small">
        <Header as="h4">
          Hand log
          <Header.Subheader>Most recent first.</Header.Subheader>
        </Header>

        {log.map((log_item, i) => (
          <Feed.Event key={"" + i}>
            <Feed.Content>
              <Feed.Summary>
                {log_item.type === "DEAL" && (
                  <div>
                    <span style={{ color: playerColor(log_item.player) }}>
                      The {log_item.street.toLowerCase()} was dealt.
                    </span>
                    <Divider />
                  </div>
                )}
                {log_item.type === "POST" && (
                  <span style={{ color: playerColor(log_item.player) }}>
                    {this.seatLabel(log_item.player)} posted the{" "}
                    {log_item.amount === 1 ? "small" : "big"} blind of{" "}
                    {log_item.amount} {log_item.amount === 1 ? "chip" : "chips"}.
                  </span>
                )}
                {["BET", "RAISE"].includes(log_item.type) && (
                  <span style={{ color: playerColor(log_item.player) }}>
                    {this.seatLabel(log_item.player)}{" "}
                    {actionToPastTense[log_item.type]} {log_item.amount}{" "}
                    {log_item.amount === 1 ? "chip." : "chips."}
                  </span>
                )}
                {["CALL", "CHECK", "FOLD"].includes(log_item.type) && (
                  <span style={{ color: playerColor(log_item.player) }}>
                    {this.seatLabel(log_item.player)}{" "}
                    {actionToPastTense[log_item.type]}.
                  </span>
                )}
              </Feed.Summary>
            </Feed.Content>
          </Feed.Event>
        ))}
      </Feed>
    );
  }

  renderSeat(seatName) {
    const message = this.state.game.last_message;
    const seatIndex = message.seats.findIndex((seat) => seat.name === seatName);
    const seat = message.seats[seatIndex];
    const isActive = message.active_seat === seatIndex;

    return (
      <Segment
        raised={isActive}
        color={isActive ? "yellow" : seat.human ? "blue" : undefined}
        style={{ textAlign: "center", opacity: seat.folded ? 0.5 : 1 }}
      >
        <Header as="h4" style={{ marginBottom: "0.5em" }}>
          {this.seatLabel(seat.name)}{" "}
          <Label size="tiny" color={seat.position === "BTN" ? "black" : undefined}>
            {seat.position}
          </Label>
          {seat.folded && (
            <Label size="tiny" color="red">
              Folded
            </Label>
          )}
          {isActive && (
            <Label size="tiny" color="yellow">
              To act
            </Label>
          )}
        </Header>
        <div>
          {seat.cards.map((card, i) => (
            <Card card={card} key={i} />
          ))}
        </div>
        <div style={{ marginTop: "0.5em" }}>
          Stack: <b>{seat.stack}</b>
          {seat.pip > 0 && (
            <span>
              {" "}
              · Bet this street: <b>{seat.pip}</b>
            </span>
          )}
          {seat.delta !== null && (
            <span style={{ color: seat.delta > 0 ? "green" : seat.delta < 0 ? "red" : "grey" }}>
              {" "}
              · {seat.delta > 0 ? "+" : ""}
              {seat.delta}
            </span>
          )}
        </div>
      </Segment>
    );
  }

  renderBoard() {
    const message = this.state.game.last_message;
    return (
      <div style={{ textAlign: "center" }}>
        <Header as="h4">
          {message.street_name}
          <Header.Subheader>Pot: {message.pot} chips</Header.Subheader>
        </Header>
        <div>
          {message.board_cards.map((card, i) => (
            <Card card={card} key={i} />
          ))}
          {Array(5 - message.board_cards.length)
            .fill()
            .map((_, i) => (
              <PlaceholderCard key={i} />
            ))}
        </div>
      </div>
    );
  }

  renderTable() {
    return (
      <Grid verticalAlign="middle" stackable>
        <Grid.Row>
          <Grid.Column width={4} />
          <Grid.Column width={8}>{this.renderSeat(TABLE_LAYOUT.top)}</Grid.Column>
          <Grid.Column width={4} />
        </Grid.Row>
        <Grid.Row>
          <Grid.Column width={4}>{this.renderSeat(TABLE_LAYOUT.left)}</Grid.Column>
          <Grid.Column width={8}>{this.renderBoard()}</Grid.Column>
          <Grid.Column width={4}>{this.renderSeat(TABLE_LAYOUT.right)}</Grid.Column>
        </Grid.Row>
        <Grid.Row>
          <Grid.Column width={4} />
          <Grid.Column width={8}>{this.renderSeat(TABLE_LAYOUT.bottom)}</Grid.Column>
          <Grid.Column width={4} />
        </Grid.Row>
      </Grid>
    );
  }

  handleAction = (move) => {
    const message = this.state.game.last_message;
    this.props.socket.emit("game_action", this.props.match.params.id, {
      type: move.min !== undefined ? "RAISE" : move.type,
      amount: this.state.selected_amount,
      decision_id: message.decision_id,
    });
  };

  moveCost(move) {
    if (move.min !== undefined) {
      return this.state.selected_amount - move.pip;
    }
    return move.cost;
  }

  renderAction() {
    const message = this.state.game.last_message;
    const seat = message.seats[message.active_seat];
    return (
      <div>
        <Header style={{ textAlign: "center" }}>
          Your move as {seat.name} ({seat.position})
          <Header.Subheader>The cost is listed in parentheses</Header.Subheader>
        </Header>
        <div style={{ textAlign: "center" }}>
          {message.legal_moves.map((move) => (
            <Button
              key={move.type}
              size="huge"
              basic
              positive={move.type === "CHECK" || move.type === "CALL"}
              negative={move.type === "FOLD"}
              onClick={() => this.handleAction(move)}
            >
              {move.min !== undefined
                ? `${move.type} TO ${this.state.selected_amount}`
                : move.type}{" "}
              ({this.moveCost(move)})
            </Button>
          ))}
        </div>
        {this.state.min_amount !== null && this.state.max_amount !== null && (
          <div style={{ textAlign: "center", padding: "1em" }}>
            <p>(Optional) Select an amount to bet or raise to.</p>
            <Slider
              min={this.state.min_amount}
              max={this.state.max_amount}
              value={this.state.selected_amount}
              step={1}
              onChange={(value) => this.setState({ selected_amount: value })}
            />
          </div>
        )}
      </div>
    );
  }

  renderWaiting() {
    const message = this.state.game.last_message;
    const seat = message.seats[message.active_seat];
    const verbs = { BET: "bets", RAISE: "raises to", CALL: "calls", CHECK: "checks", FOLD: "folds" };
    const lastAction = message.move_history
      .filter((log_item) => verbs[log_item.type] !== undefined)
      .pop();
    return (
      <Header style={{ textAlign: "center", color: "grey" }}>
        {lastAction &&
          `${this.seatLabel(lastAction.player)} ${verbs[lastAction.type]}${
            lastAction.amount !== undefined ? " " + lastAction.amount : ""
          }.`}
        <Header.Subheader>Next to act: {this.seatLabel(seat.name)}</Header.Subheader>
      </Header>
    );
  }

  renderResult() {
    const message = this.state.game.last_message;
    return (
      <div>
        {message.result === "win" && (
          <Header style={{ color: "green", textAlign: "center" }}>
            Your team won {message.team_delta} chips!
          </Header>
        )}
        {message.result === "loss" && (
          <Header style={{ color: "red", textAlign: "center" }}>
            Your team lost {-message.team_delta} chips.
          </Header>
        )}
        {message.result === "tie" && (
          <Header style={{ color: "grey", textAlign: "center" }}>
            Your team broke even.
          </Header>
        )}
        <div style={{ textAlign: "center", marginTop: "1em" }}>
          <Button primary onClick={this.handleNextHand}>
            Next Hand
          </Button>
        </div>
      </div>
    );
  }

  handleNextHand = () => {
    this.props.socket.emit("next_hand", this.props.match.params.id);
  };

  handleQuitGame = () => {
    this.props.socket.emit("quit_game", this.props.match.params.id);
  };

  renderHand() {
    const message = this.state.game.last_message;
    const bankrolls =
      message.status === "round_over" ? message.new_team_bankrolls : message.team_bankrolls;
    const headers = {
      get_action: ["Your move!", "Select an action below"],
      bot_action: ["Bots are playing", "Their actions play out at the speed you choose"],
      round_over: [`Hand ${message.round_num} is over`, "Click next hand to continue!"],
    };
    return (
      <Segment color={message.status === "get_action" ? "yellow" : "black"}>
        <Header dividing style={{ textAlign: "center" }}>
          {headers[message.status][0]}
          <Header.Subheader>
            Hand {message.round_num} of {message.num_rounds} ·{" "}
            {headers[message.status][1]}
          </Header.Subheader>
          <Button
            color="red"
            onClick={this.handleQuitGame}
            style={{
              position: "absolute",
              top: "1.5%",
              right: "2%",
              zIndex: 1000,
            }}
          >
            Quit
          </Button>
        </Header>
        <div style={{ textAlign: "right" }}>
          Bot speed:{" "}
          <Dropdown
            inline
            options={BOT_DELAY_OPTIONS}
            value={this.state.botDelay}
            onChange={this.handleBotDelayChange}
          />
        </div>
        <Statistic.Group
          size="mini"
          style={{ textAlign: "center", display: "block", margin: "1em 0" }}
        >
          <Statistic style={{ margin: "0 10px" }}>
            <Statistic.Value>{bankrolls.A}</Statistic.Value>
            <Statistic.Label>Your team</Statistic.Label>
          </Statistic>
          <Statistic style={{ margin: "0 10px" }}>
            <Statistic.Value>{bankrolls.B}</Statistic.Value>
            <Statistic.Label>{this.state.game.bot.team}</Statistic.Label>
          </Statistic>
        </Statistic.Group>
        <Divider />
        <Grid stackable divided>
          <Grid.Row>
            <Grid.Column width="12">
              {this.renderTable()}
              <Divider />
              {message.status === "get_action" && this.renderAction()}
              {message.status === "bot_action" && this.renderWaiting()}
              {message.status === "round_over" && this.renderResult()}
            </Grid.Column>
            <Grid.Column width="4">{this.renderGameLog()}</Grid.Column>
          </Grid.Row>
        </Grid>
      </Segment>
    );
  }

  renderGame() {
    const message = this.state.game.last_message;
    if (message === null) {
      return null;
    } else if (message.status === "download_and_compile") {
      return (
        <Segment placeholder>
          <div style={{ textAlign: "center" }}>
            <Header icon>
              <Icon name="spinner" loading />
              Downloading and compiling bot...
            </Header>
          </div>
        </Segment>
      );
    } else if (message.status === "starting_game") {
      return (
        <Segment placeholder>
          <div style={{ textAlign: "center" }}>
            <Header icon>
              <Icon name="spinner" loading />
              Starting game...
            </Header>
          </div>
        </Segment>
      );
    } else if (["get_action", "bot_action", "round_over"].includes(message.status)) {
      return this.renderHand();
    }
  }

  render() {
    const { game, status } = this.state;

    return (
      <div>
        <Container>
          {status === "loading" && (
            <Header as="h2" style={{ paddingTop: "2em", textAlign: "center" }}>
              Loading game details...
            </Header>
          )}
          {status === "loaded" && game == null && (
            <div style={{ paddingTop: "2em", textAlign: "center" }}>
              <Header as="h2">
                The game you're looking for doesn't exist.
              </Header>
              <Button primary onClick={() => this.props.history.push("/")}>
                Go back
              </Button>
            </div>
          )}
          {status === "loaded" && game != null && (
            <div style={{ paddingTop: "2em" }}>
              <Header as="h3" style={{ textAlign: "center" }}>
                Your team (A1 + A2) vs. {game.bot.team} ({game.bot.name})
              </Header>
              {game.status === "created" && (
                <Segment placeholder>
                  <Header icon>
                    <Icon name="spinner" loading />
                    Waiting for game to start... If waiting for a while, please come back after 5-10 minutes!
                  </Header>
                </Segment>
              )}
              {game.status === "in_progress" && this.renderGame()}
              {game.status === "internal_error" && (
                <Segment placeholder>
                  <div style={{ textAlign: "center" }}>
                    <Header icon>
                      <Icon name="exclamation" color="red" />
                      Sorry! Something went wrong. Please create a new game.
                    </Header>
                    <Button
                      primary
                      onClick={() => this.props.history.push("/")}
                    >
                      Go back
                    </Button>
                  </div>
                </Segment>
              )}
              {game.status === "completed" && (
                <Segment placeholder>
                  <div style={{ textAlign: "center" }}>
                    <Header icon>
                      <Icon name="check" color="green" />
                      This game has completed.
                      {game.last_message && game.last_message.message && (
                        <Header.Subheader>
                          {game.last_message.message}
                        </Header.Subheader>
                      )}
                    </Header>
                    <Button
                      primary
                      onClick={() => this.props.history.push("/")}
                    >
                      New game
                    </Button>
                  </div>
                </Segment>
              )}
            </div>
          )}
        </Container>
      </div>
    );
  }
}

const GameWithSocket = (props) => (
  <SocketConsumer>
    {(value) => <Game {...props} socket={value} />}
  </SocketConsumer>
);

export default withRouter(GameWithSocket);
