# Deploy the shared super memory on DigitalOcean

This turns the per-developer local memory into a **shared, org-level** one: a small service
that ingests each repo's merged PRs (deterministically, no LLM) and serves the evolving
context to everyone's skills. It reuses the exact same `ingest_pr` / `consolidate` / `facts`
code as the CLI — the store is just markdown on a persistent volume behind HTTP.

The store is markdown on a Docker volume, so it needs **persistent disk**. The simplest
DO option is a Droplet running `docker compose` (App Platform's filesystem is ephemeral and
would lose the store on every redeploy).

## 1. Create a Droplet

```bash
doctl compute droplet create supermem \
  --image docker-20-04 --size s-1vcpu-1gb --region sfo3 \
  --ssh-keys <your-key-fingerprint>
ssh root@<droplet-ip>
```

## 2. Configure and run

```bash
git clone <this-repo> && cd <repo>
cp server/.env.example .env        # fill in tokens, webhook secret, GH_TOKEN
docker compose up -d --build
curl -s localhost:8000/health      # {"status":"ok"}
```

Put it behind TLS (Caddy/Nginx, or a DO Load Balancer with a managed cert) so tokens and
recalled context never travel in cleartext. Point a domain at the Droplet, e.g.
`https://supermem.yourorg.dev`.

## 3. Per-repo tokens

Each token grants access to exactly one repo's slice and is revocable on its own. Generate
one per repo and put them in `.env` under `YUNAKI_TOKENS`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # one per repo
```
```env
YUNAKI_TOKENS={"<tokenA>":"yourorg/api","<tokenB>":"yourorg/web"}
```

## 4. Wire each repo's webhook

In the repo: **Settings → Webhooks → Add webhook**
- Payload URL: `https://supermem.yourorg.dev/webhook`
- Content type: `application/json`
- Secret: the same value as `YUNAKI_WEBHOOK_SECRET`
- Events: **Pull requests** only

On a merged PR, GitHub calls `/webhook`; the service verifies the HMAC, then ingests +
consolidates that repo in the background. (Seed history once up front with
`curl -XPOST -H "Authorization: Bearer <token>" https://supermem.yourorg.dev/ingest`.)

## 5. Point developers' skills at it

Each developer sets two env vars so `recall.py` pulls the shared store as a third source
(alongside their local facts), then re-runs `./install.sh`:

```bash
export YUNAKI_SUPERMEM_URL=https://supermem.yourorg.dev
export YUNAKI_SUPERMEM_TOKEN=<that repo's token>
```

It's strictly additive and fail-open: if the service is unreachable, recall silently falls
back to local context, so skills keep working.

## Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | none | liveness |
| GET | `/recall?skill=&query=&limit=` | Bearer (per-repo) | markdown context for the token's repo |
| POST | `/ingest` | Bearer (per-repo) | manual seed/refresh of the token's repo |
| POST | `/webhook` | GitHub HMAC | merged-PR → ingest + consolidate |

## Cost / scaling

A 1 vCPU / 1 GB Droplet (~$6/mo) handles a small org. The store is markdown files on the
volume; back it up with a periodic `docker run --rm -v supermem_data:/data ... tar` to DO
Spaces. Scale up the Droplet before reaching for anything heavier.
