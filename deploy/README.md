# Deploying Hunter on a server

1. Rent an Ubuntu 24.04 server (target: 8 vCPU, 16-32 GB RAM, about $40/month or less).
2. Copy this folder to the server and run, as root: `bash deploy/bootstrap-server.sh`.
3. Optional: put `FRED_API_KEY=...` in `/opt/hunter/feeds.env` (mode 600, owner hunter) to enable ALFRED vintages.
4. Open the app through an SSH tunnel: `ssh -L 8765:127.0.0.1:8765 hunter@<server>` then http://127.0.0.1:8765.

The feed refresh runs Tuesday to Saturday at 22:30 UTC (after the NYSE close) and writes
under `/opt/hunter/app/.local/data/feeds`. Check it with `systemctl list-timers hunter-feeds.timer`
and `journalctl -u hunter-feeds`.
