# Hermes Board

Hermes Board is a remote-first card dashboard for Hermes. The remote plugin owns card packages, data, scripts, schedules, and the REST API; the Desktop plugin renders and operates the board.

## Requirements

- Hermes Agent 0.22.2 or newer on the remote Linux host
- Hermes Desktop connected to that host
- A Git URL reachable from both the remote host and the Desktop machine

## Install

Use the same Git repository and revision for both targets.

### 1. Remote Hermes

```bash
hermes plugins install <repository-url> --enable
```

Restart the running `hermes serve` process after installation so that the dashboard API is registered. If the gateway is also long-running, restart it before asking Hermes to create or manage cards.

Confirm the backend is loaded:

```bash
hermes plugins show hermes-board
hermes plugins doctor hermes-board
```

### 2. Hermes Desktop

1. Open **Capabilities → Plugins → Install from Git**.
2. Enter the same `<repository-url>` and select the **Desktop** target.
3. Enable **Hermes Board** if it is not enabled automatically.
4. Open **Board** from the sidebar or run **Open Board** from the command palette.

The Desktop plugin calls the current remote connection. Switching the connection or profile reloads the board from that remote Hermes profile.

## Update

Update the remote and Desktop copies to the same revision, then restart `hermes serve`:

```bash
hermes plugins update hermes-board
```

The first request after an update reconciles bundled cards and Hermes cron jobs. Existing user-edited cards are not overwritten.

## Remove

Disable or remove the plugin through Hermes on each target. Removing the plugin does not automatically delete `$HERMES_HOME/plugin-data/hermes-board`; preserve that directory if the board data may be needed later.

## Acceptance checklist

After installing both targets, verify all of the following:

- The Board route, sidebar entry, command-palette actions, and header controls appear.
- Eight default cards fill the initial 24×16 layout with no gaps or overlaps.
- Light/dark theme changes propagate to every card.
- Moving and resizing cards, keyboard movement, auto-arrange, undo, add, and remove all persist after a reload.
- The weather card fetches Beijing weather, accepts a city change, and retains the last successful data on failure.
- Clock, world clock, calendar, countdown, pomodoro, note, and todo cards retain their expected state.
- The Hermes cron page shows `hermes-board:weather:fetch`; removing the weather card pauses it and adding the card resumes it.
- A card script can be run from the card and from **Recent runs**, with progress and its terminal result displayed.
- A card cannot call another card's data namespace, unknown bridge methods, external networking, browser storage, or the parent document.
- With the Desktop window hidden, remote changes arrive on the 30-second poll; when visible, they arrive on the 5-second poll.
- An expired remote login shows the authorization state, and reconnecting recovers without losing the last layout.
- A newer remote API asks for a Desktop update and performs no writes.
- In a Hermes conversation, ask for a new card with a scheduled script and a button action; it should be validated, installed, added, and usable without manually editing files.

## Development verification

```bash
pnpm install --frozen-lockfile
pnpm test:js
pnpm build
pnpm check

export HERMES_AGENT_ROOT="$HOME/.hermes/hermes-agent"
export HERMES_PY="$HERMES_AGENT_ROOT/venv/bin/python"
PYTHONDONTWRITEBYTECODE=1 "$HERMES_PY" -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 "$HERMES_PY" -m unittest discover -s tests/host -v
```

The tests create temporary `HERMES_HOME` directories and do not use the active profile.
