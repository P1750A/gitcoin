#!/usr/bin/env python3
"""
GitCoin Transaction Validator

Validates a transaction PR against the ledger rules.
Handles two TX types:
  - TRANSFER       (TX_VERSION: 1)
  - REGISTER_KEY   (TX_VERSION: REGISTER_KEY)

Exit codes:
  0 - Valid
  1 - Invalid (reason printed to stdout)

Usage:
  python3 validate_tx.py <pr_files.json> <pr_head_content.json>

Environment variables:
  PR_BODY    - Raw PR body text
  PR_AUTHOR  - GitHub login of PR author
"""

import os
import sys
import json
import base64
import hashlib
from pathlib import Path


def b64url_decode(s: str) -> bytes:
    s = s.strip()
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def parse_tx_body(body: str) -> dict:
    fields = {}
    valid_keys = {
        'TX_VERSION', 'FROM', 'TO', 'AMOUNT', 'INPUT_TXIDS',
        'OUTPUT_TO_TXID', 'OUTPUT_CHANGE_TXID', 'MEMO', 'SIGNATURE',
        'USERNAME', 'PUBLIC_KEY',
    }
    for line in body.replace('\r\n', '\n').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        key = key.strip()
        value = value.strip()
        if key in valid_keys:
            fields[key] = value
    return fields


def canonical_message(tx: dict) -> str:
    input_txids = sorted(t.strip() for t in tx['INPUT_TXIDS'].split(',') if t.strip())
    lines = [
        f"TX_VERSION:{tx['TX_VERSION']}",
        f"FROM:{tx['FROM']}",
        f"TO:{tx['TO']}",
        f"AMOUNT:{tx['AMOUNT']}",
        f"INPUT_TXIDS:{','.join(input_txids)}",
        f"OUTPUT_TO_TXID:{tx['OUTPUT_TO_TXID']}",
    ]
    if tx.get('OUTPUT_CHANGE_TXID'):
        lines.append(f"OUTPUT_CHANGE_TXID:{tx['OUTPUT_CHANGE_TXID']}")
    if tx.get('MEMO'):
        lines.append(f"MEMO:{tx['MEMO']}")
    return '\n'.join(lines)


def verify_ed25519(public_key_b64: str, message: str, signature_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
        pub_bytes = b64url_decode(public_key_b64)
        sig_bytes = b64url_decode(signature_b64)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        pub_key.verify(sig_bytes, message.encode('utf-8'))
        return True
    except Exception:
        return False


def fail(reason: str):
    print(f"INVALID: {reason}")
    sys.exit(1)


def validate_register_key(tx: dict, pr_author: str, pr_files: list, head_content: dict):
    # Only validators/pubkeys.json should be modified
    changed = [f['filename'] for f in pr_files]
    if changed != ['validators/pubkeys.json']:
        fail(f"REGISTER_KEY PR must only modify validators/pubkeys.json. Got: {changed}")

    if pr_files[0].get('status') != 'modified':
        fail("validators/pubkeys.json must be modified (not added/deleted)")

    username = tx.get('USERNAME', '').strip()
    pubkey = tx.get('PUBLIC_KEY', '').strip()

    if not username:
        fail("Missing USERNAME field")
    if not pubkey:
        fail("Missing PUBLIC_KEY field")
    if username != pr_author:
        fail(f"USERNAME '{username}' must match PR author '{pr_author}'")

    # Verify the public key is valid base64url-encoded 32-byte Ed25519 key
    try:
        key_bytes = b64url_decode(pubkey)
        if len(key_bytes) != 32:
            fail(f"PUBLIC_KEY must be 32 bytes (Ed25519). Got {len(key_bytes)} bytes.")
        # Verify it loads as a valid Ed25519 public key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(key_bytes)
    except Exception as e:
        fail(f"PUBLIC_KEY is not a valid Ed25519 public key: {e}")

    # Verify the new pubkeys.json contains the registration
    new_content_str = head_content.get('validators/pubkeys.json', '')
    if not new_content_str:
        fail("Could not fetch new validators/pubkeys.json content from PR head")
    try:
        new_pubkeys = json.loads(new_content_str)
    except json.JSONDecodeError:
        fail("validators/pubkeys.json in PR head is not valid JSON")

    if new_pubkeys.get(username) != pubkey:
        fail(f"validators/pubkeys.json does not contain the correct entry for '{username}'")

    # Verify no other entries were changed
    existing_path = Path('validators/pubkeys.json')
    if existing_path.exists():
        existing = json.loads(existing_path.read_text())
        for key, val in existing.items():
            if new_pubkeys.get(key) != val:
                fail(f"REGISTER_KEY PR must only add one new entry. Entry '{key}' was modified.")
        added = set(new_pubkeys.keys()) - set(existing.keys())
        if len(added) != 1 or list(added)[0] != username:
            fail(f"REGISTER_KEY PR must add exactly one new entry for '{username}'")


def validate_transfer(tx: dict, pr_author: str, pr_files: list, head_content: dict):
    required = ['TX_VERSION', 'FROM', 'TO', 'AMOUNT', 'INPUT_TXIDS', 'OUTPUT_TO_TXID', 'SIGNATURE']
    for field in required:
        if not tx.get(field):
            fail(f"Missing required field: {field}")

    if tx['FROM'] != pr_author:
        fail(f"FROM='{tx['FROM']}' does not match PR author '{pr_author}'")

    try:
        amount = int(tx['AMOUNT'])
        if amount <= 0:
            fail(f"AMOUNT must be a positive integer, got: {tx['AMOUNT']}")
    except ValueError:
        fail(f"AMOUNT is not a valid integer: {tx['AMOUNT']}")

    # All changed files must be in utxo/
    for fi in pr_files:
        if not fi['filename'].startswith('utxo/') or not fi['filename'].endswith('.json'):
            fail(f"PR may only add/delete files in utxo/*.json. Found: {fi['filename']}")

    deleted = {f['filename'] for f in pr_files if f['status'] == 'removed'}
    added = {f['filename'] for f in pr_files if f['status'] == 'added'}

    input_txids = sorted(t.strip() for t in tx['INPUT_TXIDS'].split(',') if t.strip())
    if not input_txids:
        fail("INPUT_TXIDS is empty")

    expected_deleted = {f"utxo/{txid}.json" for txid in input_txids}
    if deleted != expected_deleted:
        fail(f"Deleted files {sorted(deleted)} do not match INPUT_TXIDS {sorted(expected_deleted)}")

    expected_added = {f"utxo/{tx['OUTPUT_TO_TXID']}.json"}
    if tx.get('OUTPUT_CHANGE_TXID'):
        expected_added.add(f"utxo/{tx['OUTPUT_CHANGE_TXID']}.json")
    if added != expected_added:
        fail(f"Added files {sorted(added)} do not match expected outputs {sorted(expected_added)}")

    # Read input UTXOs from main branch
    input_total = 0
    for txid in input_txids:
        utxo_path = Path(f"utxo/{txid}.json")
        if not utxo_path.exists():
            fail(f"Input UTXO '{txid}' does not exist in main branch")
        try:
            utxo = json.loads(utxo_path.read_text())
        except json.JSONDecodeError:
            fail(f"Input UTXO '{txid}' is not valid JSON")
        if utxo.get('owner') != tx['FROM']:
            fail(f"Input UTXO '{txid}' is owned by '{utxo.get('owner')}', not '{tx['FROM']}'")
        if utxo.get('unit') != 'GTC':
            fail(f"Input UTXO '{txid}' has unexpected unit '{utxo.get('unit')}' (expected 'GTC')")
        input_total += int(utxo.get('amount', 0))

    # Read output UTXOs from PR head
    output_total = 0
    for filename, content in head_content.items():
        if not filename.startswith('utxo/'):
            continue
        try:
            utxo = json.loads(content)
        except json.JSONDecodeError:
            fail(f"Output file {filename} is not valid JSON")
        expected_txid = filename[len('utxo/'):-len('.json')]
        if utxo.get('txid') != expected_txid:
            fail(f"UTXO file {filename}: txid field '{utxo.get('txid')}' does not match filename")
        if utxo.get('unit') != 'GTC':
            fail(f"Output UTXO {expected_txid} must have unit 'GTC'")
        output_total += int(utxo.get('amount', 0))

    # Conservation of value
    if input_total != output_total:
        fail(f"Value not conserved: inputs={input_total} GTC, outputs={output_total} GTC")

    # Verify TO output
    to_file = f"utxo/{tx['OUTPUT_TO_TXID']}.json"
    if to_file in head_content:
        to_utxo = json.loads(head_content[to_file])
        if to_utxo.get('owner') != tx['TO']:
            fail(f"Output UTXO {tx['OUTPUT_TO_TXID']} owner '{to_utxo.get('owner')}' != TO '{tx['TO']}'")
        if int(to_utxo.get('amount', 0)) != amount:
            fail(f"Output UTXO amount {to_utxo.get('amount')} GTC != AMOUNT {amount} GTC")

    # Verify change output
    if tx.get('OUTPUT_CHANGE_TXID'):
        change_file = f"utxo/{tx['OUTPUT_CHANGE_TXID']}.json"
        if change_file in head_content:
            change_utxo = json.loads(head_content[change_file])
            if change_utxo.get('owner') != tx['FROM']:
                fail(f"Change UTXO owner '{change_utxo.get('owner')}' != FROM '{tx['FROM']}'")
            expected_change = input_total - amount
            if int(change_utxo.get('amount', 0)) != expected_change:
                fail(f"Change amount {change_utxo.get('amount')} GTC != expected {expected_change} GTC")

    # Verify Ed25519 signature
    pubkeys_path = Path('validators/pubkeys.json')
    if not pubkeys_path.exists():
        fail("validators/pubkeys.json not found on main branch")

    pubkeys = json.loads(pubkeys_path.read_text())
    if tx['FROM'] not in pubkeys:
        fail(f"No public key registered for '{tx['FROM']}'. Submit a REGISTER_KEY PR first.")

    msg = canonical_message(tx)
    if not verify_ed25519(pubkeys[tx['FROM']], msg, tx['SIGNATURE']):
        fail("Ed25519 signature verification failed")


def main():
    if len(sys.argv) < 3:
        print("Usage: validate_tx.py <pr_files.json> <pr_head_content.json>")
        sys.exit(1)

    pr_body = os.environ.get('PR_BODY', '')
    pr_author = os.environ.get('PR_AUTHOR', '')

    if not pr_body.strip():
        fail("PR body is empty. Must contain TX fields.")

    with open(sys.argv[1]) as f:
        pr_files = json.load(f)
    with open(sys.argv[2]) as f:
        head_content = json.load(f)

    tx = parse_tx_body(pr_body)

    tx_version = tx.get('TX_VERSION', '')
    if not tx_version:
        fail("Missing TX_VERSION field")

    if tx_version == 'REGISTER_KEY':
        validate_register_key(tx, pr_author, pr_files, head_content)
    elif tx_version == '1':
        validate_transfer(tx, pr_author, pr_files, head_content)
    else:
        fail(f"Unknown TX_VERSION: '{tx_version}'. Supported: '1', 'REGISTER_KEY'")

    print("Transaction is valid")
    sys.exit(0)


if __name__ == '__main__':
    main()
