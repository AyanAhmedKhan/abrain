# gbrain — Documentation

The **company brain** for Dexter Capital: Gmail call notes (and later more
sources) → structured notes, financial time-series, semantic search, and a
knowledge graph.

## Index

| Doc | What's in it |
|---|---|
| [PIPELINE.md](PIPELINE.md) | How it works — architecture, the 6 pipeline stages, the classifier, the data model, and how retrieval works. Start here to understand the system. |
| [RUNBOOK.md](RUNBOOK.md) | How to run & operate it — services, connecting Gmail, ingesting/backfilling, viewing data, the graph viewer, config, cost, testing, deploying, troubleshooting. |
| [PROGRESS.md](PROGRESS.md) | What's done vs remaining, plus a quick health-check snippet. |

## 30-second orientation

- Code: `/opt/gbrain` (runs as the `gbrain` user). Config: `/opt/gbrain/.env`.
- Pipeline (always-on systemd workers): `normalize → preprocess → extract → embed → resolve`.
- Ingestion: `workers/connectors/gmail.py` (OAuth, multi-mailbox) → `gbrain-gmail.timer`.
- Graph viewer: `http://localhost:8099/graph_viewer.html` (forward port 8099 in VS Code).
- Spend only happens in `extract` (Gemini on Vertex credits); a classifier gates cost & privacy.

```bash
# is it healthy?
systemctl list-units 'gbrain-*'
# go live on Gmail
systemctl enable --now gbrain-gmail.timer
# add a mailbox
sudo -u gbrain /opt/gbrain/.venv/bin/python -m workers.connectors.gmail_auth
```
