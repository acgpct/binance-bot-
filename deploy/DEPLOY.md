# Deploying the rotation bot to a VPS

This guide walks you through deploying the bot to a cheap cloud server so it
runs 24/7 — even with your laptop closed. End-to-end takes ~15 minutes.

## What you'll get

- Bot running continuously on a $4–6/month Linux server
- Auto-restart on crashes (via `systemd`)
- Centralized logs (`journalctl`)
- Survives reboots, network blips, your laptop being off

## What you'll NOT get (yet)

- The Streamlit dashboard exposed publicly. The dashboard stays on your Mac;
  it queries the same testnet account directly so it still works.

---

## Step 1 — Pick a provider and create a server

Recommended for beginners: **DigitalOcean** ($4/mo) or **Hetzner** (€3.79/mo).

### DigitalOcean

1. Sign up at https://www.digitalocean.com (referrals get $200 free credit, look around)
2. **Create → Droplets**
3. Image: **Ubuntu 24.04 LTS x64**
4. Size: Basic → Regular → **$4/mo (512MB RAM, 1 vCPU, 10GB disk)** is enough; $6 if you want headroom
5. Datacenter: any near you (Frankfurt for EU, NYC for US)
6. Authentication: **SSH Key** (easiest, paste your `~/.ssh/id_ed25519.pub`) — if you don't have one, use **Password** for now (they email it to you)
7. Hostname: `binance-bot`
8. Click **Create Droplet**, wait ~30 seconds, copy the public IP

### Hetzner Cloud (cheaper)

1. Sign up at https://www.hetzner.com/cloud
2. Create project → **Add Server**
3. Location: any
4. Image: **Ubuntu 24.04**
5. Type: **CAX11** (€3.79/mo, ARM, 2 vCPU, 4GB) or **CX22** (€4.51/mo, x86)
6. SSH key: paste yours (or skip; password emailed)
7. Name: `binance-bot`, click **Create & Buy now**

---

## Step 2 — SSH in

From your Mac terminal:

```bash
ssh root@<YOUR-SERVER-IP>
```

Accept the host key fingerprint when prompted. You should see something like
`root@binance-bot:~#`.

---

## Step 3 — Run the setup script

The repo includes a one-shot script that does everything: installs Python, clones the repo, sets up a `botuser`, creates the venv, installs deps, configures the systemd service, and enables a basic firewall.

The repo is **private**, so you need to authenticate. Easiest path: `gh auth login` first, then clone.

```bash
# On the server (still root)
apt-get update && apt-get install -y gh git
gh auth login          # GitHub.com → HTTPS → web browser → paste code

# Clone and run setup
git clone https://github.com/acgpct/binance-bot-.git /tmp/repo
bash /tmp/repo/deploy/setup.sh
```

Wait ~2 minutes. At the end you'll see:

```
==> ✅ Setup complete.

Next steps:
  1. Edit testnet keys:    nano /home/botuser/binance-bot-/.env
  2. Start the bot:        systemctl enable --now binance-bot
  ...
```

---

## Step 4 — Add your testnet API keys

```bash
nano /home/botuser/binance-bot-/.env
```

Replace the placeholder values with your testnet keys. Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

> **Important.** Use a *fresh* set of testnet keys for the server, not the ones
> on your Mac. If your Mac's keys ever leak, you can revoke them without
> affecting the server (and vice versa).

---

## Step 5 — Start the bot

```bash
systemctl enable --now binance-bot
```

This both **enables** (auto-start on reboot) and **starts** the service immediately. Verify it's running:

```bash
systemctl status binance-bot
```

You should see `Active: active (running)`. If not, check `journalctl -u binance-bot -n 50` for the error.

---

## Step 6 — Watch the first rebalance

```bash
journalctl -u binance-bot -f
```

(`-f` = follow live, like `tail -f`. Ctrl+C to exit.)

You'll see log lines for the rebalance cycle: universe scan, top 5 picks, buy orders, then "Sleeping ~86400s until next rebalance".

Disconnect from SSH (`exit`). The bot keeps running.

---

## Useful commands once it's running

```bash
# Check status
systemctl status binance-bot

# Recent logs
journalctl -u binance-bot -n 100 --no-pager

# Live logs
journalctl -u binance-bot -f

# Stop / start / restart
systemctl stop binance-bot
systemctl start binance-bot
systemctl restart binance-bot

# Disable auto-start (keep installed, won't run on boot)
systemctl disable binance-bot
```

## Updating the bot when you make changes

When you push commits to GitHub:

```bash
ssh root@<IP>
sudo -u botuser git -C /home/botuser/binance-bot- pull
sudo -u botuser /home/botuser/binance-bot-/.venv/bin/pip install -q -r /home/botuser/binance-bot-/requirements.txt
systemctl restart binance-bot
journalctl -u binance-bot -f    # verify it came back up
```

## Connecting your local dashboard to the deployed bot

Your Mac dashboard (`streamlit run dashboard/app.py`) reads:

- **Live exchange balances** — works automatically as long as your local `.env` has the *same testnet keys as the server*. Both query the same Binance account.
- **Equity history** — local-only, so the chart will be empty unless you sync the history file. Easy ad-hoc sync:

  ```bash
  # On your Mac, periodically pull the equity log down
  scp root@<IP>:/home/botuser/binance-bot-/data/equity_history.csv ./data/equity_history.csv
  ```

Or set up a cron on the VPS to push it to a Gist / S3 / your private GH repo.

---

## Cost summary

- **DigitalOcean** $4/mo droplet → ~$48/yr
- **Hetzner** CAX11 €3.79/mo → ~€45/yr

For testnet exploration, this is silly money — equivalent to a fancy coffee a
month. For real-money trading, it's a rounding error.

## Hardening for live trading (before going `BINANCE_LIVE=true`)

If you eventually move to real funds, consider:

- [ ] Disable root SSH (`PermitRootLogin no` in `/etc/ssh/sshd_config`)
- [ ] Use SSH keys only, no password auth
- [ ] Fail2ban for SSH
- [ ] Restrict Binance API key to "spot trading only" + IP-allowlist your VPS
- [ ] Set up off-server alerting (Telegram, email) for big drawdowns or bot crashes
- [ ] Take a snapshot of the droplet before any code changes
- [ ] Rotate API keys quarterly

But none of this matters until your testnet results are consistently good for at least 30 days.
