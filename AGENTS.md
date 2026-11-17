# EHCC Admin — Development Notes

These instructions apply to all developers and coding agents working in this repository.

## Dashboard: sharing outstanding balances

- The dashboard's **Outstanding balances** card may expose a share action to admins only.
- The shared image must include only players whose net balance is positive (the player owes the team; net is owed minus paid). Do not include players with a negative net balance (the team owes the player), zero balances, or any unrelated player/account data.
- Derive the share rows from the server-rendered dashboard balance data; do not recalculate ledger balances in the browser.
- The share image should show the team name, generation date, player names, individual outstanding amounts, and a total.
- On the Android APK, use the native Android share bridge (ACTION_SEND) rather than the browser Web Share API inside WebView. On ordinary browsers, prefer native file sharing when supported and provide a direct PNG download fallback otherwise.
- Keep the action admin-only in the rendered UI and verify that viewers cannot see it.
- Preserve responsive dashboard layout and accessible button labeling.
- Add/maintain regression tests for positive-only filtering and admin-only visibility whenever this feature is changed.

## Engineering expectations

- Treat the ledger/services layer as the source of truth for financial balances. UI code must not independently derive accounting state.
- Keep team scoping intact; never mix players or balances across teams.
- For financial UI changes, cover positive, negative, and zero balances, viewer/admin permissions, and team isolation where relevant.
- Update static asset cache-busting versions when changing shared CSS or JavaScript.
- Do not claim a change is tested unless the relevant automated tests have actually been run.
