# Secure Document Exchange System

A student project that demonstrates secure document exchange using hybrid cryptography and digital signatures.

## Project Overview

The system is designed to protect documents during transfer by combining symmetric encryption, public-key cryptography, and digital signatures.

The planned cryptographic workflow uses:

- **AES-256-GCM** for document encryption and integrity protection.
- **RSA-OAEP with SHA-256** for securely wrapping the AES encryption key.
- **RSA-PSS with SHA-256** for digital signatures.
- **SHA-256 fingerprints** to help identify trusted public keys.

This is an educational prototype, not a production-ready document-sharing service.

## Current Status

The repository is being prepared in stages. Cryptographic functionality, the web interface, and security tests will be added and verified incrementally.

## Planned Project Structure

```text
secure-document-exchange/
├── sdx/
│   └── __init__.py
├── tests/
│   └── test_setup.py
├── templates/
├── static/
├── docs/
│   ├── diagrams/
│   └── screenshots/
├── check_setup.py
├── pytest.ini
├── requirements.txt
├── .gitignore
├── .gitattributes
└── README.md
```

## Development Setup

Python and the dependencies listed in `requirements.txt` are required to run and test the application locally.

Detailed setup and test instructions will be added after the initial environment has been verified on the team members' computers.

## Security Notes

- Private keys must not be committed to the repository.
- Public keys must be checked against a trusted local source.
- A document must not be released as decrypted output unless signature verification and authenticated decryption succeed.
- Security claims will be based on tests that have actually been run.

## Team

This project is being developed as a three-member student team.
