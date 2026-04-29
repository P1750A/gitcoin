#!/usr/bin/env python3
"""
GitCoin Key Generator

Generates an Ed25519 keypair for use with GitCoin.
KEEP YOUR PRIVATE KEY SECRET. Only share the public key.

Usage:
  pip install cryptography
  python3 generate_keypair.py
"""

import base64
import sys

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    print("ERROR: Please install the cryptography library first:")
    print("  pip install cryptography")
    sys.exit(1)


def main():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes_raw()
    public_bytes = public_key.public_bytes_raw()

    private_b64 = base64.urlsafe_b64encode(private_bytes).decode().rstrip('=')
    public_b64 = base64.urlsafe_b64encode(public_bytes).decode().rstrip('=')

    print("=" * 60)
    print("GitCoin Ed25519 Keypair")
    print("=" * 60)
    print()
    print("PRIVATE KEY — Keep this secret, never commit it:")
    print(f"  {private_b64}")
    print()
    print("PUBLIC KEY — Share this in your REGISTER_KEY PR:")
    print(f"  {public_b64}")
    print()
    print("Store your private key somewhere safe (e.g. a password manager).")
    print("You will need it every time you send a transaction.")


if __name__ == '__main__':
    main()
