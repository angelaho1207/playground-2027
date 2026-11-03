import React, { Component } from 'react';
import { Header, Icon, Container, Segment, Button, Form } from 'semantic-ui-react';
import { withRouter } from 'react-router-dom';

import { SocketConsumer } from './SocketContext';

const WEEK_OPTIONS = [
  { key: 1, value: 1, text: "Week 1: base game" },
  { key: 2, value: 2, text: "Week 2: one combined hand per team" },
  { key: 3, value: 3, text: "Week 3: combined hands and random seating" },
];

class Home extends Component {
  constructor(props) {
    super(props);

    this.state = {
      teams: null,
      selectedTeam: null,
      selectedBot: null,
      selectedWeek: 1,
      loadingChallenge: false,
    }
  }

  fetchBots = () => {
    this.setState({ teams: null });
    this.props.socket.emit('request_bots', (result) => {
      this.setState({ teams: result.teams });
    })
  }

  componentDidMount() {
    this.fetchBots()
  }

  componentWillUnmount() {

  }

  handleChange = (e, { name, value }) => {
    if (name === 'selectedTeam') {
      this.setState({ selectedBot: null })
    }
    this.setState({ [name]: value })
  }

  teamOptions = () => {
    return this.state.teams.map((team, i) => ({
      key: i,
      text: team.name,
      value: i,
    }))
  }

  botOptions = () => {
    if (this.state.selectedTeam == null) {
      return [];
    }
    return this.state.teams[this.state.selectedTeam].bots.map((bot, i) => ({
      key: bot.id,
      text: bot.name,
      value: bot.id,
    }))
  }

  challengeBot = () => {
    this.setState({
      loadingChallenge: true
    })
    this.props.socket.emit('create_game', this.state.selectedBot, this.state.selectedWeek, (gameUuid) => {
      this.setState({
        loadingChallenge: false
      })
      this.props.history.push('/game/' + gameUuid);
    })
  }

  render() {
    return (
      <div style={{ height: "100%" }}>
        <Container text>
          <Header as='h2' style={{ paddingTop: "2em" }}>
            Welcome to the Pokerbots Playground!
            <Header.Subheader>Here, you play Homie Hold'em against the bots on the scrimmage server.</Header.Subheader>
          </Header>
          <p>
            Your team sits at a table of four: you play both of your team's seats,
            and two copies of the bot you choose play the other two. Pick a bot and
            the week whose rules you want to play, and you'll be connected.
          </p>
          { this.state.teams == null && (
            <Segment placeholder>
              <Header icon>
                <Icon name='spinner' loading />
                Fetching available bots...
              </Header>
              <Button primary onClick={this.fetchBots}>Try again</Button>
            </Segment>
          )}
          { this.state.teams != null && (
            <Segment>
              <Header dividing>
                Select a bot
              </Header>
              <Form>
                <Form.Select
                  name='selectedTeam'
                  options={this.teamOptions()}
                  placeholder="Select a team"
                  label="Team"
                  onChange={this.handleChange}
                  value={this.state.selectedTeam} />
                <Form.Select
                  name='selectedBot'
                  options={this.botOptions()} placeholder={
                    (this.state.selectedTeam == null) ? "Select a team first" : "Select a bot"
                  }
                  label="Bot"
                  disabled={this.state.selectedTeam == null}
                  onChange={this.handleChange}
                  value={this.state.selectedBot} />
                <Form.Select
                  name='selectedWeek'
                  options={WEEK_OPTIONS}
                  label="Rules"
                  onChange={this.handleChange}
                  value={this.state.selectedWeek} />
                <div style={{ textAlign: "center" }}>
                  <Button
                    color='green'
                    onClick={this.challengeBot}
                    fluid
                    loading={this.state.loadingChallenge}
                    disabled={this.state.selectedBot == null || this.state.loadingChallenge}>Challenge!</Button>
                </div>
              </Form>
            </Segment>
          )}
        </Container>
      </div>
    );
  }
}

const HomeWithSocket = (props) => (
  <SocketConsumer>
    { (value) => <Home {...props} socket={value} /> }
  </SocketConsumer>
);

export default withRouter(HomeWithSocket);
