# herdr-ghostty-tab-title

A [herdr](https://herdr.dev) plugin that puts your agent status counts in the Ghostty tab title.

```
web-01  🔴 2  🟢 1  🟡 5  ⚪ 12
```

Two agents want your input, one finished, five are working, twelve idle — readable from the tab bar without switching to the tab.

## Why

If you run one herdr per remote host, each host lives in its own Ghostty tab. Finding out whether anything needs you means visiting every tab. This plugin pushes a rollup of each host's agent statuses into that host's tab title, so a single Ghostty window is enough to watch the whole fleet.

## Status glyphs

Ghostty tab titles are plain text — no ANSI colors — so color coding is done with colored glyphs. The default order is herdr's attention order: whatever needs you comes first.

| Glyph | Status | Meaning |
|---|---|---|
| 🔴 | `blocked` | waiting on your input or approval |
| 🟢 | `done` | finished, needs review |
| 🟡 | `working` | busy |
| ⚪ | `idle` | nothing happening |
| ⚫ | `unknown` | herdr cannot tell (hidden by default) |

Glyphs, order, and spacing are all configurable — see [config.example.toml](config.example.toml). herdr does not publish its own status palette, so these are chosen to match the semantics, not sampled from its theme.

## Install

Needs herdr ≥ 0.7.4 and Python 3 (3.11+ for TOML config; 3.8+ works with JSON config). No other dependencies.

From GitHub, on the host whose herdr server you want to watch:

```sh
herdr plugin install wjarka/herdr-ghostty-tab-title --yes
```

Or from a local checkout:

```sh
git clone https://github.com/wjarka/herdr-ghostty-tab-title
herdr plugin link "$PWD/herdr-ghostty-tab-title"
```

Either way, start the watcher without waiting for a restart:

```sh
herdr plugin action invoke ghostty-tab-title.start
```

It starts by itself from then on, via the plugin's `[[startup]]` hook.

### Remote hosts

Install it on the remote host, not locally — the plugin has to run next to the herdr server that owns the agents:

```sh
scripts/install-remote.sh agent@host-a agent@host-b
```

The title travels back over herdr's remote-client bridge to the local `herdr --remote` client, which emits it to the Ghostty tab it lives in. The default label is the remote host's short hostname, so each tab identifies itself with no configuration.

## Configuration

Optional. Drop a `config.toml` (or `config.json`) in the plugin config dir:

```sh
cp config.example.toml "$(herdr plugin config-dir ghostty-tab-title)/config.toml"
herdr plugin action invoke ghostty-tab-title.restart
```

Two env vars are handy for one-off runs: `HERDR_GHOSTTY_TITLE_LABEL` overrides the label, `HERDR_GHOSTTY_TITLE_DEBUG=1` logs every title push.

## Commands

Through herdr:

```sh
herdr plugin action invoke ghostty-tab-title.start     # start the watcher
herdr plugin action invoke ghostty-tab-title.stop      # stop it, restore herdr's title
herdr plugin action invoke ghostty-tab-title.restart   # pick up config changes
herdr plugin action invoke ghostty-tab-title.status    # watcher state + current counts
herdr plugin action invoke ghostty-tab-title.refresh   # one-shot title update
herdr plugin log list --plugin ghostty-tab-title       # stdout/stderr of the above
```

Or directly, which is easier to read while debugging:

```sh
bin/herdr-ghostty-title status
bin/herdr-ghostty-title render 2 1 5 12   # preview a title, touches nothing
bin/herdr-ghostty-title clear             # restore herdr's own title
```

Bind the ones you use to a key in `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+t"
type = "plugin_action"
command = "ghostty-tab-title.refresh"
```

## How it works

1. Subscribes to unfiltered `pane.*`, `tab.*` and `workspace.*` events on the herdr socket as a change signal. (`pane.agent_status_changed` requires a `pane_id`, so it cannot be used as a global feed.)
2. Debounces the burst, then re-reads `agent.list` — authoritative, so counts never drift from a missed event.
3. Renders the title and pushes it with `client.window_title.set`.
4. herdr's client emits `OSC 0;<title>` to its terminal, and Ghostty makes that the tab title.
5. Re-pushes unconditionally every 10s, so a client that detaches and re-attaches gets its title back.

One watcher per herdr server, guarded by a `flock` in the plugin state dir. It reconnects with backoff when the server restarts, and two cheap `[[events]]` hooks restart it if it ever dies.

## Troubleshooting

**Title never changes.** Check `herdr plugin action invoke ghostty-tab-title.status`, then the watcher log (its path is in that output). A `no_foreground_client` reason at debug level means herdr has no client attached to push to.

**Title changes, Ghostty ignores it.** A `title = ...` line in `~/.config/ghostty/config` pins the tab title and discards OSC titles. Remove it.

**`config.toml ignored: python 3.x has no tomllib`.** Python is older than 3.11. Use `config.json` with the same keys.

**Two herdr clients on one server.** Only the foreground one gets the title; herdr picks it, not this plugin.

## Tests

```sh
python3 tests/test_render.py         # unit: counting, rendering, config merge
python3 tests/integration_test.py    # end-to-end, needs herdr on PATH
```

The integration test boots a throwaway herdr session inside a pty, synthesises agent states with `pane.report_agent`, and asserts on the OSC title bytes herdr writes to that pty — the same bytes Ghostty would receive.

## Notes

- Works with any terminal that honours OSC 0/2 titles. Ghostty is what it was built and tested against.
- Tested against herdr 0.7.4 on macOS and Linux.
- herdr holds an attention state (`blocked`, `done`) on an unfocused pane until you look at it. That is herdr's behaviour, and the counts follow it.

## License

MIT
