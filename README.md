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

## herdr compatibility

| herdr | Status |
|---|---|
| < 0.7.0 | Will not work. `client.window_title.set/clear` and the plugin system (manifest actions + event hooks, config/state dirs) all landed in 0.7.0. |
| 0.7.0 – 0.7.2 | Every API used exists, but untested. The `done` count can go stale: 0.7.3 fixed re-focusing a done agent leaving stale `done` status in API responses. |
| 0.7.3 | Lowest version with accurate `done` counts. Untested. |
| **0.7.4** | **Verified** — full suite, macOS and Linux. Declared `min_herdr_version`. Autostart comes from the event hooks; `[[startup]]` is parsed but ignored. |
| 0.7.5 – 0.7.x | `[[startup]]` hooks added in 0.7.5, so autostart uses those. Note 0.7.5's breaking change: plugins became global to the user rather than per-session, so a plugin installed only inside a named session on 0.7.3 must be installed again. |
| **0.8.0** | **Verified** — full suite, no changes needed. No breaking changes in that release, and *"relative plugin commands now resolve from the plugin root"* matches how this manifest invokes `python3`. |

`min_herdr_version` is set to 0.7.4 because that is the oldest release this was
actually run against, not because 0.7.0–0.7.3 are known bad. Lowering it is safe
if you need it, with the `done` caveat above.

To check a new herdr release before upgrading, point the suite at its binary:

```sh
HERDR_BIN=/path/to/herdr-0.9.0 python3 tests/integration_test.py
```

## Install

Needs herdr ≥ 0.7.4 (see above) and Python 3 — 3.11+ for TOML config, 3.8+ with
JSON config (verified on 3.8, 3.9 and 3.11). No other dependencies.

From GitHub, on the host whose herdr server you want to watch:

```sh
herdr plugin install wjarka/herdr-ghostty-tab-title --yes
```

Or from a local checkout:

```sh
git clone https://github.com/wjarka/herdr-ghostty-tab-title
herdr plugin link "$PWD/herdr-ghostty-tab-title"
```

Either way, start the watcher for the current session:

```sh
herdr plugin action invoke ghostty-tab-title.start
```

After that it starts by itself. On herdr 0.7.5+ that is the plugin's
`[[startup]]` hook; on 0.7.0–0.7.4, which parse `[[startup]]` but ignore it, the
`pane.created` / `tab.created` / `workspace.created` event hooks do it —
including during session restore, so it comes back with the server. Verified on
0.7.4: watcher up and title pushed within a second of the server restarting.

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

### Labels

`label` takes two tokens:

| Token | Expands to |
|---|---|
| `{host}` | short hostname of the machine running the herdr server |
| `{session}` | herdr session name — `default`, or the `--session` name |

The default is `{host}`, so a `herdr --remote` tab names itself after the remote
box with no configuration. Set `label = "{host}/{session}"` if you run several
named sessions on one host, or hard-code a human name (`label = "Management
Dashboard"`) — that is the better place for it than a Ghostty tab title, since
you keep the counts.

The session name is not in herdr's socket API at all (`session.snapshot` carries
only version, protocol, focused ids and the object lists), so it is derived from
the socket path: `<config>/sessions/<name>/herdr.sock` for a named session,
`<config>/herdr.sock` for `default`.

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

Or directly, which is easier to read while debugging. These find herdr's managed
config and state directories on their own, so they report the same thing the
watcher herdr started is using:

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

One watcher per herdr server. The `flock` guarding it is keyed on the socket
path, not just the state dir, because herdr hands every session on a host the
same plugin state dir — without that, a second session would never get a title.
The watcher reconnects with backoff when the server restarts, gives up after 10
minutes with no server (the event hooks bring it back), and the `ensure` hooks
restart it if it ever dies.

## Troubleshooting

**Title never changes.** Check `herdr plugin action invoke ghostty-tab-title.status`, then the watcher log (its path is in that output). A `no_foreground_client` reason at debug level means herdr has no client attached to push to.

**Title changes, Ghostty ignores it — most common cause.** If you ever renamed
the tab yourself (`prompt_tab_title`, or right-click the tab and rename), Ghostty
pins that title: *"The title set via this prompt overrides any title set by the
terminal."* Every OSC title, including this plugin's, is then discarded. Clear the
override with an empty `set_tab_title`:

```
# ~/.config/ghostty/config
keybind = cmd+shift+u=set_tab_title:
```

Reload the config, press it once in each affected tab, and the tab goes back to
following the terminal. To keep a human-readable name, move it into this plugin's
`label` instead of Ghostty's tab title — you then get the name *and* the counts:

```toml
label = "Build Box"
```

A `title = ...` line in `~/.config/ghostty/config` pins titles the same way.
Remove it.

Quick check on whether a given tab is pinned: `printf '\033]0;PINNED?\007'`. If
the tab title does not change, it is pinned.

**`config.toml ignored: python 3.x has no tomllib`.** Python is older than 3.11. Use `config.json` with the same keys.

**Two herdr clients on one server.** Only the foreground one gets the title; herdr picks it, not this plugin.

**Watcher won't start.** `watcher-<hash>.err` in the state dir holds the stderr
of the detached process, including a traceback if it died on startup.

**Tab title flips between two different titles.** Two watchers are pushing to the
same client. Stop the plugin, confirm nothing survives, then start it again:

```sh
herdr plugin action invoke ghostty-tab-title.stop
pgrep -af 'herdr-ghostty-title run'      # expect nothing for this server
herdr plugin action invoke ghostty-tab-title.start
```

Always `stop` before upgrading or uninstalling: `herdr plugin uninstall` does not
signal a running watcher. `scripts/install-remote.sh` does this for you.

## Tests

```sh
python3 tests/test_render.py         # unit: counting, rendering, config merge
python3 tests/integration_test.py    # end-to-end, needs herdr on PATH
```

The integration test boots a throwaway herdr session inside a pty, synthesises agent states with `pane.report_agent`, and asserts on the OSC title bytes herdr writes to that pty — the same bytes Ghostty would receive.

## Notes

- Works with any terminal that honours OSC 0/2 titles. Ghostty is what it was built and tested against.
- Verified against herdr 0.7.4 and 0.8.0; see the compatibility table.
- herdr holds an attention state (`blocked`, `done`) on an unfocused pane until you look at it. That is herdr's behaviour, and the counts follow it.

## License

MIT
