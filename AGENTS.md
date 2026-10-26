# Gateway agent entry point

Read [the knowledge base](docs/knowledge-base/README.md), then
[the handoff checklist](docs/knowledge-base/HANDOFF.md) before changing this project.
The main [README](README.md) contains user-facing startup instructions.

- The user's name for this portable stack is **gateway**. Repository and image
  tags still use MT5Scraper. Unrelated containers named `mt5-gateway` and
  `mt5-marketdata-*` are not part of this project.
- Preserve `.env`, `.image`, `data`, and Docker volumes unless the user explicitly
  requests otherwise. Never publish credentials or saved terminal state.
- Current requested core cap is 4 CPU / 4 GiB; retain it unless the user asks
  for another change. Dashboard remains 0.25 CPU / 256 MiB, with no extra swap.
- Unrestricted scraping previously used over 10 GiB; the user reported laptop
  crashes, so retain the 4 GiB memory cap.
- Use project `mt5scraper-portable` and `--project-directory . -f
  docker/compose.server.yaml` from the repository root. Root Compose is a
  separate local configuration with different storage.
- Substantial implementation is uncommitted/untracked. Do not assume untracked
  files are residue; do not reset or clean the checkout.
- This is a market-data collector. Do not add broker order placement implicitly.
- Check Python changes with `python -B -m unittest discover -s tests -q` and
  JavaScript with `node --check dashboard/static/app.js`. Validate Compose
  quietly so expanded credentials are not printed.
- An image build does not update running containers. Recreate only affected
  services when necessary; restarting the core briefly interrupts collection.
- Update the knowledge base when behavior, schemas, commands, or deployment change.
