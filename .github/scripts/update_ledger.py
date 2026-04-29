#!/usr/bin/env python3
"""
GitCoin Ledger Updater

Scans utxo/ directory, aggregates balances per owner,
collects TX history from git log, reads validator registry,
and writes docs/ledger.json.

Run automatically by update-pages.yml after every merge to main.
Does NOT write to main branch. Output goes to docs/ for Pages deployment.
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_block_info() -> tuple[int, str]:
    height_result = subprocess.run(
        ['git', 'rev-list', '--count', 'HEAD'],
        capture_output=True, text=True
    )
    block_height = int(height_result.stdout.strip()) if height_result.returncode == 0 else 0

    hash_result = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        capture_output=True, text=True
    )
    block_hash = hash_result.stdout.strip() if hash_result.returncode == 0 else ('0' * 64)

    return block_height, block_hash


def scan_utxos() -> tuple[dict, int]:
    utxo_dir = Path('utxo')
    balances: dict[str, int] = {}
    utxo_count = 0

    for utxo_file in sorted(utxo_dir.glob('*.json')):
        if utxo_file.name == '.gitkeep':
            continue
        try:
            utxo = json.loads(utxo_file.read_text())
            owner = utxo.get('owner', '').strip()
            amount = int(utxo.get('amount', 0))
            if owner and amount > 0:
                balances[owner] = balances.get(owner, 0) + amount
                utxo_count += 1
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"Warning: skipping malformed UTXO {utxo_file.name}: {e}", file=sys.stderr)

    # Sort by balance descending
    sorted_balances = dict(sorted(balances.items(), key=lambda x: x[1], reverse=True))
    return sorted_balances, utxo_count


def get_tx_history() -> list:
    result = subprocess.run(
        ['git', 'log', '--pretty=format:%H|%aI|%s', '--diff-filter=AD', '--', 'utxo/*.json'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    seen: set = set()
    txs = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('|', 2)
        if len(parts) < 3:
            continue
        full_hash, date, subject = parts
        if full_hash in seen:
            continue
        seen.add(full_hash)
        tx: dict = {"hash": full_hash[:12], "full_hash": full_hash, "date": date, "subject": subject}
        m = re.match(r'tx:\s+(\S+)\s+[→\->]+\s+(\S+)\s+(\d+)\s+GTC', subject)
        if m:
            tx["from"] = m.group(1)
            tx["to"] = m.group(2)
            tx["amount"] = int(m.group(3))
        txs.append(tx)
    return txs


def get_validators() -> list:
    pubkeys_path = Path('validators/pubkeys.json')
    pubkeys: dict = {}
    if pubkeys_path.exists():
        try:
            pubkeys = json.loads(pubkeys_path.read_text())
        except (json.JSONDecodeError, ValueError):
            pass

    registry_map: dict = {}
    registry_path = Path('validators/registry.json')
    if registry_path.exists():
        try:
            reg = json.loads(registry_path.read_text())
            for v in reg.get('validators', []):
                registry_map[v['username']] = v
        except (json.JSONDecodeError, ValueError):
            pass

    validators = []
    for username, pubkey in pubkeys.items():
        reg_entry = registry_map.get(username, {})
        validators.append({
            "username": username,
            "pubkey": pubkey,
            "score": reg_entry.get('score', 100),
            "status": reg_entry.get('status', 'active'),
            "last_active": reg_entry.get('last_active', '')
        })
    return validators


def main():
    block_height, block_hash = get_block_info()
    balances, utxo_count = scan_utxos()
    txs = get_tx_history()
    validators = get_validators()

    ledger = {
        "block_height": block_height,
        "block_hash": block_hash,
        "updated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "unit": "GTC",
        "balances": balances,
        "utxo_count": utxo_count,
        "transactions": txs,
        "validators": validators
    }

    docs_dir = Path('docs')
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / 'ledger.json').write_text(json.dumps(ledger, indent=2))

    total_supply = sum(balances.values())
    print(f"Ledger updated: block={block_height}, utxos={utxo_count}, "
          f"accounts={len(balances)}, txs={len(txs)}, validators={len(validators)}, "
          f"supply={total_supply} GTC")


if __name__ == '__main__':
    main()
