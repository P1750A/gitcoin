#!/usr/bin/env python3
"""
GitCoin Ledger Updater

Scans utxo/ directory, aggregates balances per owner,
and writes docs/ledger.json.

Run automatically by update-pages.yml after every merge to main.
Does NOT write to main branch. Output goes to docs/ for Pages deployment.
"""

import json
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


def main():
    block_height, block_hash = get_block_info()
    balances, utxo_count = scan_utxos()

    ledger = {
        "block_height": block_height,
        "block_hash": block_hash,
        "updated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        "unit": "GTC",
        "balances": balances,
        "utxo_count": utxo_count
    }

    docs_dir = Path('docs')
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / 'ledger.json').write_text(json.dumps(ledger, indent=2))

    total_supply = sum(balances.values())
    print(f"Ledger updated: block={block_height}, utxos={utxo_count}, "
          f"accounts={len(balances)}, supply={total_supply} GTC")


if __name__ == '__main__':
    main()
