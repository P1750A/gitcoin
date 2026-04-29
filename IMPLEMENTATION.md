# GitCoin — Implementation Blueprint

> **Rule**: All code, comments, and documentation must be in English.

---

## 1. Overview

GitCoin is a blockchain-like token ecosystem hosted entirely on GitHub.
Every GitHub account that forks this repository becomes a full node.
Consensus is achieved through GitHub's native **Auto-merge** + a **status check workflow** —
no stored bot keys, no long-lived tokens.

```
Fork repo  →  Create PR (transaction)  →  validate-tx posts check
           →  assign-validators @mentions selected validators in a comment
           →  validators visit PR and comment "/approve"
           →  consensus-check counts /approve comments from active validators
           →  when ⌈2N/3⌉ reached: consensus-check posts PASSING check
           →  GitHub auto-merge triggers (all required checks passed)
           →  update-pages rebuilds ledger snapshot
```

### Key design constraints

| Constraint | Solution |
|---|---|
| Fork PRs block `GITHUB_TOKEN` writes | Use `pull_request_target` / `issue_comment` events (run on base branch, have write permissions) |
| Dynamic 2/3 threshold can't live in Branch Protection | `consensus-check.yml` workflow acts as the gatekeeper status check |
| Reviewers must be repo Collaborators to Approve | Use `issue_comment` voting instead — anyone can comment on a public repo; `user.login` is GitHub-authenticated |
| No stored bot keys | Only ephemeral `GITHUB_TOKEN` — auto-issued per run, expires on run end |

---

## 2. Repository Structure

```
gitcoin/
├── .github/
│   ├── workflows/
│   │   ├── validate-tx.yml        # Validates TX on PR open/update; posts tx-valid/tx-invalid label
│   │   ├── assign-validators.yml  # Randomly selects validators, adds as Collaborators, requests review
│   │   ├── consensus-check.yml    # On every review: counts approvals, posts PASS/FAIL status check
│   │   ├── expire-tx.yml          # Closes PRs that exceed 48h timeout
│   │   └── update-pages.yml       # Rebuilds GitHub Pages ledger snapshot after merge
├── utxo/
│   └── <txid>.json                # One file = one unspent coin (UTXO)
├── validators/
│   ├── registry.json              # Active validators and contribution scores
│   └── pubkeys.json               # Ed25519 public keys per GitHub username
├── genesis/
│   └── genesis.json               # Initial coin distribution (genesis block)
├── docs/                          # GitHub Pages source (gh-pages branch)
│   ├── index.html
│   └── ledger.json                # Balance snapshot rebuilt after every merge
└── IMPLEMENTATION.md
```

---

## 3. UTXO Model

### 3.1 Why UTXO

- Each UTXO is a **single file** inside `utxo/`.
- Spending a coin = **deleting** that file in the PR diff.
- Two PRs attempting to delete the same file → Git raises a **merge conflict** → second PR is automatically blocked.
- No sequential lock, no bot arbitration. Git's native conflict detection is the double-spend guard.

### 3.2 UTXO File Schema

File: `utxo/<txid>.json`

```json
{
  "txid": "a1b2c3d4e5f6...",
  "owner": "github_username",
  "amount": 100,
  "unit": "GTC",
  "created_at_block": "sha256_of_parent_merge_commit",
  "created_at_height": 42
}
```

| Field | Description |
|---|---|
| `txid` | SHA-256(`owner` + `amount` + `created_at_block`), hex-encoded |
| `owner` | GitHub username of the coin holder |
| `amount` | Token amount in **GTC** (integer, no decimals) |
| `created_at_block` | Merge commit SHA at creation time — links into hash chain |
| `created_at_height` | Number of confirmed merges before this UTXO was created |

### 3.3 PR File Structure for a Transaction

A transaction PR **must** contain exactly these file changes — no others:

| File operation | Purpose |
|---|---|
| DELETE `utxo/<input_txid>.json` (one per input) | Consume input coins |
| ADD `utxo/<output_txid>.json` | New UTXO for recipient (`TO`) |
| ADD `utxo/<change_txid>.json` (optional) | Change UTXO returned to sender |

`validate-tx.yml` reads the PR's changed-file list via the GitHub REST API and cross-checks it against the TX body fields. Any mismatch (extra files, missing deletes, wrong amounts) fails validation.

---

## 4. Transaction Format

### 4.1 PR Body Template

Every transaction PR must have a body matching this exact schema. The workflow parses it by reading `github.event.pull_request.body` — no code from the PR branch is ever executed.

```
TX_VERSION: 1
FROM: alice
TO: bob
AMOUNT: 50
INPUT_TXIDS: a1b2c3d4e5f6,d4e5f6a1b2c3
OUTPUT_TO_TXID: f7a8b9c0d1e2
OUTPUT_CHANGE_TXID: e3d4c5b6a7f8
MEMO: payment for work
SIGNATURE: <base64url-encoded Ed25519 signature>
```

| Field | Description |
|---|---|
| `FROM` | Sender GitHub username (must match PR author) |
| `TO` | Recipient GitHub username |
| `AMOUNT` | Amount to send in GTC |
| `INPUT_TXIDS` | Comma-separated txids of UTXOs being consumed |
| `OUTPUT_TO_TXID` | txid of the new UTXO added for `TO` |
| `OUTPUT_CHANGE_TXID` | txid of the change UTXO returned to `FROM` (omit if no change) |
| `SIGNATURE` | Ed25519 signature over the canonical message (see 4.2) |

### 4.2 Canonical Signature Message

The signed message is the UTF-8 byte sequence of the following string (fields in this fixed order, newline `\n` delimited, no trailing newline):

```
TX_VERSION:1
FROM:alice
TO:bob
AMOUNT:50
INPUT_TXIDS:a1b2c3d4e5f6,d4e5f6a1b2c3
OUTPUT_TO_TXID:f7a8b9c0d1e2
OUTPUT_CHANGE_TXID:e3d4c5b6a7f8
MEMO:payment for work
```

Rules:
- Keys and values are joined with `:` (no spaces).
- If `OUTPUT_CHANGE_TXID` is absent, that line is omitted entirely.
- `INPUT_TXIDS` are sorted lexicographically before joining with `,`.
- Signature is base64url-encoded (no padding).

### 4.3 Public Key Registry

File: `validators/pubkeys.json`

```json
{
  "alice": "base64url_ed25519_public_key",
  "bob":   "base64url_ed25519_public_key"
}
```

Public key registration is a PR of type `REGISTER_KEY` (TX_VERSION field set to `REGISTER_KEY`), approved by existing validators. The PR adds the entry to `validators/pubkeys.json`.

---

## 5. Validator System

### 5.1 Validator Registry

File: `validators/registry.json`

```json
{
  "validators": [
    {
      "username": "alice",
      "score": 840,
      "last_active": "2026-04-01",
      "status": "active"
    }
  ],
  "total_validators": 1,
  "last_updated_block": "sha256_of_last_merge_commit"
}
```

### 5.2 Validator Qualification Rules

| Rule | Value |
|---|---|
| Minimum score to become active | 100 points |
| Inactivity score decay | −10 points per week with no submitted review |
| Disqualification | Score drops below 0 → `status` set to `inactive` |
| Score gain per review submitted on a valid TX | +20 points |
| Score gain per valid TX submitted by this user | +5 points |

`update-pages.yml` recalculates scores and updates `registry.json` after every merge to `main`.

### 5.3 Validator Selection and Comment-Based Voting

When `assign-validators.yml` runs after a PR is labeled `tx-valid`:

1. Read `validators/registry.json` from `main` branch.
2. Filter for `status: active`.
3. Select **min(7, active_count)** validators at random, seeded by `GITHUB_RUN_ID`.
4. Post a PR comment that:
   - @mentions each selected validator (triggers GitHub notification).
   - States the required approval count and the 48-hour deadline.
   - Instructs validators: *comment `/approve` on this PR to cast your vote*.

No Collaborator registration. No `administration: write`. No formal review request.

Validators are notified via GitHub's standard @mention notification system. They click through to the PR and post `/approve` as a comment. Their `user.login` is set by GitHub authentication — it cannot be spoofed.

**Consensus threshold**: `required = ceil(selected_count * 2 / 3)`

This number is used by `consensus-check.yml` at runtime — it is **not** stored in Branch Protection.

---

## 6. GitHub Actions Workflows

### GITHUB_TOKEN permission model

All workflows use only the **ephemeral `GITHUB_TOKEN`** — automatically issued by GitHub per run, scoped to the minimum required permissions declared in each workflow, and expired when the run ends.

No personal access tokens (PAT), OAuth tokens, or stored secrets exist in this system.

---

### 6.1 `validate-tx.yml` — Transaction Validator

**Trigger**: `pull_request_target` (types: opened, synchronize, reopened)

> `pull_request_target` runs in the base repo context, so `GITHUB_TOKEN` has write permissions
> even for PRs from forks. The PR head branch code is **never checked out or executed**.

**Declared permissions**:
```yaml
permissions:
  pull-requests: write   # add labels, post comments
  statuses: write        # post commit status check
```

**Steps**:
1. Read PR body from `github.event.pull_request.body` — no checkout required.
2. Parse TX fields with a regex parser running on `main` branch code.
3. Verify `FROM` field matches `github.event.pull_request.user.login`.
4. Call GitHub REST API to list files changed in the PR (no checkout of fork branch).
5. Verify deleted files match `INPUT_TXIDS` exactly.
6. Verify added output files match `OUTPUT_TO_TXID` and `OUTPUT_CHANGE_TXID`.
7. Read `utxo/<txid>.json` from `main` branch for each input; verify they exist and are owned by `FROM`.
8. Verify sum of input amounts = `AMOUNT` + change amount (conservation of value).
9. Read `validators/pubkeys.json` from `main`; verify Ed25519 signature.
10. **If valid**: add label `tx-valid`; post `success` commit status on `validate-tx/validate`.
11. **If invalid**: add label `tx-invalid`; post `failure` commit status (blocks auto-merge).

---

### 6.2 `assign-validators.yml` — Validator Selector

**Trigger**: `pull_request_target` (types: labeled) — fires when `tx-valid` label is added

**Declared permissions**:
```yaml
permissions:
  pull-requests: write     # post comment
```

**Steps**: See Section 5.3. No Collaborator registration, no `administration: write`.

---

### 6.3 `consensus-check.yml` — Approval Counter

**Trigger**: `issue_comment` (types: created)

> `issue_comment` fires for comments on both issues and PRs. It runs in the base repo
> context and has write permissions. `github.event.comment.user.login` is set by GitHub
> authentication and cannot be forged by the commenter.

**Declared permissions**:
```yaml
permissions:
  statuses: write        # post commit status check
  pull-requests: read    # read PR comments list
  issues: read           # issue_comment event context
```

**Steps**:
1. Ignore if the event is not on a PR (check `github.event.issue.pull_request` exists).
2. Ignore if the comment body (trimmed, lowercased) is not exactly `/approve`.
3. Read `validators/registry.json` from `main`.
4. Check if `github.event.comment.user.login` is an `active` validator. If not, post a reply and exit.
5. List all comments on this PR via REST API.
6. Collect distinct `user.login` values where comment body is `/approve` AND the user is an active validator in the registry.
7. Find the `assign-validators.yml` comment on this PR; parse the selected validator list and `required` count.
8. Count how many selected validators have posted `/approve`.
9. If `approval_count >= required`: post `success` on `consensus-check/passed`.
10. Else: post `pending` on `consensus-check/passed` (not failure — keeps PR open).

> **Security note**: Only the first `/approve` from each user is counted (distinct login set).
> The comment body is matched as a literal string, never executed.

When both `validate-tx/validate` and `consensus-check/passed` are `success`, GitHub auto-merge triggers automatically.

---

### 6.4 `expire-tx.yml` — Timeout Enforcer

**Trigger**: `schedule` (cron: `0 */6 * * *` — every 6 hours)

**Declared permissions**:
```yaml
permissions:
  pull-requests: write   # close PR, add label
  issues: write          # add label (labels API shared with issues)
```

**Steps**:
1. List all open PRs with label `tx-valid` via REST API.
2. For each PR older than 48 hours where `consensus-check/passed` is not `success`:
   - Add label `tx-expired`.
   - Close PR with a comment explaining expiry.
3. Prevents the mempool from clogging with abandoned transactions.

---

### 6.5 `update-pages.yml` — Ledger Snapshot Builder

**Trigger**: `push` to `main` (fires after auto-merge completes)

**Declared permissions**:
```yaml
permissions:
  contents: write        # commit to gh-pages branch
  pages: write           # deploy GitHub Pages
```

**Steps**:
1. Checkout `main`.
2. Scan all files in `utxo/`; parse each JSON.
3. Aggregate balances per `owner`.
4. Recalculate validator scores; update `validators/registry.json`; commit to `main`.
5. Write `docs/ledger.json` with current block height and balances.
6. Commit and push `docs/` to `gh-pages` branch.

---

## 7. Branch Protection Rules

Configured manually by the repo owner **once** at launch. Cannot be changed without a validator-approved PR because "Include administrators" is enabled.

```
Branch: main

Required status checks (must pass before auto-merge):
  ✅ validate-tx / validate        ← TX is structurally valid + signature correct
  ✅ consensus-check / passed      ← ⌈2N/3⌉ validator approvals reached

Required approving reviews: 0
  (Human approval count is tracked by consensus-check.yml, not enforced here.
   Setting this to 0 allows auto-merge to trigger on status checks alone.)

Include administrators:
  ✅ ENABLED  ← Repo owner cannot bypass consensus

Allow auto-merge:
  ✅ ENABLED

Allow force pushes:
  ❌ DISABLED

Allow deletions:
  ❌ DISABLED
```

> **Why "Required approvals = 0"?**
> The 2/3 validator consensus is enforced by the `consensus-check/passed` status check.
> Setting Branch Protection's required approvals to a fixed number would require
> updating Branch Protection every time the validator count changes — which needs Admin
> API access and breaks decentralization. Status checks are dynamic and need no manual updates.

---

## 8. Hash Chain Integrity

GitCoin does not use a separate blockchain database. The **Git commit history itself** is the hash chain.

- Every merge commit SHA is a cryptographic hash of its content + parent commit SHA.
- `created_at_block` in each UTXO records the merge commit SHA at creation time.
- Anyone can verify the entire history with `git log --pretty=format:"%H %P %s"`.
- Tampering with any historical UTXO would require rewriting all subsequent commits — immediately detectable by any fork holder whose local history diverges.

---

## 9. GitHub Pages — Balance Explorer

URL: `https://<owner>.github.io/gitcoin/`

### 9.1 `docs/ledger.json` Schema

Rebuilt after every merge by `update-pages.yml`:

```json
{
  "block_height": 42,
  "block_hash": "sha256_of_latest_merge_commit",
  "updated_at": "2026-04-29T12:00:00Z",
  "unit": "GTC",
  "balances": {
    "alice": 150,
    "bob": 50
  },
  "utxo_count": 4
}
```

### 9.2 `docs/index.html` — Static Balance Viewer

- Fetches `ledger.json` from the same origin (no external API calls).
- Displays per-account balance table sorted by balance descending.
- Shows block height and block hash for independent verification.
- No JavaScript frameworks — vanilla HTML + fetch API only.

---

## 10. Genesis Block

File: `genesis/genesis.json`

```json
{
  "block_height": 0,
  "block_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "timestamp": "2026-04-29T00:00:00Z",
  "initial_supply": 4294967295,
  "unit": "GTC",
  "distributions": [
    { "owner": "repo_owner_username", "amount": 4294967295, "unit": "GTC", "txid": "genesis_txid_0" }
  ]
}
```

The genesis UTXO file `utxo/genesis_txid_0.json` is committed directly to `main` at repository creation. This is the only commit that bypasses consensus — it is performed once by the founder before Branch Protection rules are enabled.

---

## 11. Attack Surface Analysis

| Attack | Mitigation |
|---|---|
| Double-spend via two concurrent PRs | UTXO file deletion causes Git merge conflict; second PR cannot merge |
| Long-lived bot key theft | No stored keys exist — only ephemeral `GITHUB_TOKEN` per run |
| Admin unilateral merge | Branch protection includes administrators; owner cannot self-merge |
| Sybil validator attack | Contribution score required; new GitHub accounts start at 0 |
| Workflow code injection via PR | `pull_request_target` / `issue_comment` run `main` branch code; PR head is never checked out |
| Forged TX body (inject shell commands) | PR body is parsed as plain text by a regex parser, never passed to shell |
| Balance tampering in `docs/` | `ledger.json` is fully derived from `utxo/` on every push; any tampering is overwritten |
| Validator set capture (bought approvals) | Score decay evicts inactive validators; Sybil score barrier |
| GitHub platform shutdown | Full node = fork clone; entire ledger history portable to GitLab/Forgejo/Radicle |
| Malicious `consensus-check.yml` PR | Changing workflow files is itself a PR requiring 2/3 consensus |

---

## 12. GITHUB_TOKEN Usage Audit

| Workflow | Event | Permissions needed | Scope |
|---|---|---|---|
| `validate-tx.yml` | `pull_request_target` | `pull-requests: write`, `statuses: write` | Label PR, post status check |
| `assign-validators.yml` | `pull_request_target` (labeled) | `pull-requests: write` | Post @mention comment |
| `consensus-check.yml` | `issue_comment` | `statuses: write`, `pull-requests: read`, `issues: read` | Count `/approve` comments, post status check |
| `expire-tx.yml` | `schedule` | `pull-requests: write`, `issues: write` | Close PR, add label |
| `update-pages.yml` | `push` to `main` | `contents: write`, `pages: write` | Commit ledger snapshot |

All tokens are ephemeral (issued per run, expired on run end). No token is stored in repo Secrets.

---

## 13. Implementation Phases

### Phase 1 — Genesis (Manual, one-time)
- [ ] Create repository
- [ ] Commit genesis files: `genesis/genesis.json`, `utxo/genesis_txid_0.json`, `validators/pubkeys.json`, `validators/registry.json`
- [ ] Enable Branch Protection rules (Section 7) — do this LAST
- [ ] Register founder public key in `validators/pubkeys.json`

### Phase 2 — Core Workflows
- [ ] Implement `validate-tx.yml`
- [ ] Implement `assign-validators.yml`
- [ ] Implement `consensus-check.yml`
- [ ] Implement `expire-tx.yml`

### Phase 3 — Pages
- [ ] Implement `update-pages.yml`
- [ ] Build `docs/index.html`

### Phase 4 — Validator Onboarding
- [ ] First external contributors fork and submit `REGISTER_KEY` PRs
- [ ] Founder approves initial validators (founder has score 840 at genesis)
- [ ] Once ≥ 3 active validators exist, founder's unilateral control ends
