# GitCoin ⛓

A fully decentralized token ecosystem that runs entirely on GitHub.
No servers, no wallets, no gas fees — just forks, pull requests, and consensus.

**Live Balance Explorer**: `https://<owner>.github.io/gitcoin/`

---

## How It Works

| Blockchain concept | GitCoin equivalent |
|---|---|
| Full node | Fork of this repository |
| Transaction | Pull Request with UTXO file changes |
| Block | Merge commit on `main` |
| Hash chain | Git commit history |
| Validator / miner | GitHub account with contribution score ≥ 100 |
| Consensus | ⌈2/3⌉ selected validators comment `/approve` |
| Double-spend guard | Git merge conflict (two PRs can't delete the same file) |
| Total supply | 4,294,967,295 GTC (fixed, no inflation) |
| Minimum unit | 1 GTC (integer amounts only) |

### Transaction lifecycle

```
1. You fork this repo and pull the latest main branch
2. You run create_transaction.py to build and sign a TX
3. You push the file changes to your fork and open a PR
4. validate-tx.yml verifies your signature and UTXO ownership
5. assign-validators.yml @mentions up to 7 randomly selected validators
6. Validators comment /approve on the PR
7. When ⌈2/3⌉ approvals are reached, GitHub auto-merge fires
8. update-pages.yml rebuilds the balance explorer
```

---

## Requirements

```bash
pip install cryptography
```

You also need:
- A GitHub account
- Git installed locally
- `gh` CLI (optional, for convenience): https://cli.github.com

---

## Quick Start

### Step 1 — Fork this repository

Click **Fork** at the top of this page. Your fork is your full node — it contains the entire ledger history.

### Step 2 — Generate your Ed25519 identity

```bash
git clone https://github.com/YOUR_USERNAME/gitcoin
cd gitcoin
python3 .github/scripts/generate_keypair.py
```

Output:
```
⚠️  PRIVATE KEY — Keep this secret, never commit it:
  <your-private-key-base64url>

✅  PUBLIC KEY — Share this in your REGISTER_KEY PR:
  <your-public-key-base64url>
```

**Store your private key in a password manager.** If you lose it, you lose access to your coins. Never commit it to any repository.

### Step 3 — Register your public key

Before you can send GTC, validators must know your public key.

**Create a PR** from your fork to this repo's `main` branch with:

**Changed file** — modify `validators/pubkeys.json` to add your entry:
```json
{
  "existing_user": "their_key",
  "YOUR_GITHUB_USERNAME": "YOUR_PUBLIC_KEY_BASE64URL"
}
```

**PR body** — must contain exactly:
```
TX_VERSION: REGISTER_KEY
USERNAME: YOUR_GITHUB_USERNAME
PUBLIC_KEY: YOUR_PUBLIC_KEY_BASE64URL
```

**PR title**: `register: YOUR_GITHUB_USERNAME`

Once ⌈2/3⌉ validators approve the PR, it auto-merges and you can start transacting.

---

## Checking Your Balance

Visit the live balance explorer:
```
https://<owner>.github.io/gitcoin/
```

Or inspect the ledger directly:
```bash
git pull origin main
cat docs/ledger.json
```

Or scan your UTXOs manually:
```bash
grep -rl '"owner": "YOUR_USERNAME"' utxo/
```

---

## Sending GTC

### Step 1 — Pull the latest state

```bash
git pull origin main
```

### Step 2 — Find your UTXOs

```bash
grep -rl '"owner": "YOUR_USERNAME"' utxo/
```

Note the txid values (the filenames without `.json`).

### Step 3 — Run the transaction builder

```bash
python3 .github/scripts/create_transaction.py
```

You will be prompted for:
- Your GitHub username
- Your private key
- Recipient username
- Amount to send (GTC)
- UTXO txids to spend (comma-separated)
- Optional memo

The script outputs the exact PR body to copy and the file changes to make. It can also write the output UTXO files automatically.

### Step 4 — Commit and push the changes

```bash
git add utxo/
git commit -m "tx: YOUR_USERNAME → RECIPIENT 50 GTC"
git push origin main
```

### Step 5 — Open a PR

Open a Pull Request from **your fork's `main` branch** to **this repository's `main` branch**.

- **PR title**: `tx: YOUR_USERNAME → RECIPIENT 50 GTC`
- **PR body**: paste the output from the transaction builder (the `TX_VERSION: 1 ...` block)

### Step 6 — Wait for consensus

The `validate-tx.yml` workflow runs automatically. If valid, validators are @mentioned and have 48 hours to comment `/approve`. When ⌈2/3⌉ of selected validators approve, the PR auto-merges.

---

## Becoming a Validator

Validators are GitHub accounts with a **contribution score ≥ 100**.

### How to earn score

| Action | Points |
|---|---|
| Approved review (comment `/approve` on a valid TX) | +20 |
| Submitting a valid TX that gets merged | +5 |

### Score decay

If you are inactive for weeks (no `/approve` comments), your effective score decreases by **10 points per week**. If your effective score drops below 0, you are temporarily excluded from validator selection until you participate again.

### How to vote

When a transaction PR is opened:

1. You receive a GitHub notification via @mention (watch this repo or enable notifications).
2. Visit the PR and review the changes in `utxo/`.
3. Verify the transaction looks correct (amounts, ownership).
4. Comment exactly `/approve` to cast your vote.

You have 48 hours. If the threshold is not reached, the PR is automatically closed.

---

## Transaction Reference

### Transfer (TX_VERSION: 1)

```
TX_VERSION: 1
FROM: alice
TO: bob
AMOUNT: 50
INPUT_TXIDS: a1b2c3d4e5f6...,d4e5f6a1b2c3...
OUTPUT_TO_TXID: f7a8b9c0d1e2...
OUTPUT_CHANGE_TXID: e3d4c5b6a7f8...
MEMO: payment for work
SIGNATURE: <base64url Ed25519 signature>
```

| Field | Required | Description |
|---|---|---|
| `TX_VERSION` | ✅ | Must be `1` |
| `FROM` | ✅ | Must match PR author's GitHub login |
| `TO` | ✅ | Recipient GitHub username |
| `AMOUNT` | ✅ | Integer GTC to send (minimum: 1 GTC) |
| `INPUT_TXIDS` | ✅ | Comma-separated txids of UTXOs you are spending |
| `OUTPUT_TO_TXID` | ✅ | txid of new UTXO file added for the recipient |
| `OUTPUT_CHANGE_TXID` | if change | txid of change UTXO returned to you |
| `MEMO` | optional | Free-text note |
| `SIGNATURE` | ✅ | Ed25519 signature over the canonical message |

**Conservation rule**: `sum(inputs) == AMOUNT + change`. No GTC can be created or destroyed.

> **Note**: All amounts are integers. The minimum transactable unit is **1 GTC**. Decimal amounts are not supported.

### Key Registration (TX_VERSION: REGISTER_KEY)

```
TX_VERSION: REGISTER_KEY
USERNAME: alice
PUBLIC_KEY: <base64url Ed25519 public key>
```

PR must only modify `validators/pubkeys.json` by adding one new entry.

---

## UTXO File Format

Each file in `utxo/` represents one unspent coin:

```json
{
  "txid": "a1b2c3d4...",
  "owner": "alice",
  "amount": 100,
  "unit": "GTC",
  "created_at_block": "<merge commit SHA>",
  "created_at_height": 42
}
```

The filename must match the `txid` field: `utxo/<txid>.json`.

**Computing a txid**:
```python
import hashlib
txid = hashlib.sha256(f"{owner}{amount}{created_at_block}".encode()).hexdigest()
```

---

## Founder / Repository Setup Guide

Follow these steps once when deploying a new GitCoin instance.

### 1. Create the repository

Create a new public GitHub repository. Do **not** enable Branch Protection yet.

### 2. Generate your keypair

```bash
python3 .github/scripts/generate_keypair.py
```

### 3. Compute your genesis txid

```python
import hashlib
owner = "YOUR_GITHUB_USERNAME"
amount = 4294967295
block_hash = "0" * 64
txid = hashlib.sha256(f"{owner}{amount}{block_hash}".encode()).hexdigest()
print(txid)
```

### 4. Edit the genesis files

**`genesis/genesis.json`** — replace `REPLACE_WITH_FOUNDER_USERNAME` and `REPLACE_WITH_GENESIS_TXID`.

**`validators/pubkeys.json`** — replace placeholders with your username and public key.

**`validators/registry.json`** — replace `REPLACE_WITH_FOUNDER_USERNAME` with your username.

**Create `utxo/<genesis_txid>.json`**:
```json
{
  "txid": "<your computed genesis txid>",
  "owner": "YOUR_GITHUB_USERNAME",
  "amount": 4294967295,
  "unit": "GTC",
  "created_at_block": "0000000000000000000000000000000000000000000000000000000000000000",
  "created_at_height": 0
}
```

### 5. Commit everything to main

```bash
git add .
git commit -m "genesis: initialize GitCoin ledger"
git push origin main
```

### 6. Enable GitHub Pages

In your repository **Settings → Pages**:
- Set **Source** to **GitHub Actions**

### 7. Configure Branch Protection (do this last)

In **Settings → Branches → Add rule** for `main`:

- [x] **Require status checks to pass before merging**
  - Add required check: `validate-tx / validate`
  - Add required check: `consensus-check / passed`
- [x] **Require branches to be up to date before merging**
- [x] **Include administrators** ← CRITICAL: do not skip this
- [x] **Allow auto-merge**
- [ ] Allow force pushes — leave unchecked
- [ ] Allow deletions — leave unchecked

> After enabling "Include administrators", even you cannot merge without going through consensus. This is intentional — it is the foundation of the system's trustlessness.

### 8. Create required labels

In your repository Issues → Labels, create:
- `tx-valid` (color: `#2ea043`)
- `tx-invalid` (color: `#f85149`)
- `tx-expired` (color: `#8b949e`)

---

## Security Notes

| Property | How it is enforced |
|---|---|
| No stored bot keys | All workflows use only ephemeral `GITHUB_TOKEN` (auto-issued per run, expires on completion) |
| No admin bypass | Branch Protection includes administrators |
| No double-spend | Git merge conflict blocks the second PR deleting the same UTXO file |
| No code injection from PR | `pull_request_target` runs `main` branch code; the PR head branch is never checked out or executed |
| No shell injection from PR body | PR body is parsed as plain text by Python, never interpolated into shell commands |
| Signature forgery | Ed25519 signatures are verified against the registered public key for each sender |
| Sybil validators | Contribution score required; new accounts start at 0 |

---

## Architecture Overview

```
.github/
├── workflows/
│   ├── validate-tx.yml        pull_request_target → verify TX structure + Ed25519 sig
│   ├── assign-validators.yml  pull_request_target (labeled) → @mention selected validators
│   ├── consensus-check.yml    issue_comment → count /approve from active validators
│   ├── expire-tx.yml          schedule (6h) → close PRs past 48h deadline
│   └── update-pages.yml       push to main → rebuild ledger.json + deploy Pages
└── scripts/
    ├── validate_tx.py          Core validation logic (TRANSFER + REGISTER_KEY)
    ├── update_ledger.py        UTXO scanner and ledger.json builder
    ├── generate_keypair.py     User tool: generate Ed25519 keypair
    └── create_transaction.py   User tool: build and sign a transaction

utxo/                          One JSON file per unspent coin
validators/
    registry.json              Active validators and contribution scores
    pubkeys.json               Ed25519 public keys per GitHub username
genesis/
    genesis.json               Genesis block metadata
docs/
    index.html                 Balance explorer (static, served via GitHub Pages)
    ledger.json                Balance snapshot (rebuilt after every merge to main)
```

---

## Portability

If GitHub ever becomes unavailable, the entire ledger history is preserved in every fork's `git log`. The same workflow logic can be migrated to:

- **GitLab** (GitLab CI/CD)
- **Gitea / Forgejo** (Gitea Actions)
- **Radicle** (decentralized git hosting)

The UTXO files and commit history are the canonical truth. No data lives outside the repository.
