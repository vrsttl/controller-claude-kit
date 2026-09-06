# /// script
# requires-python = ">=3.12"
# dependencies = ["keyring>=25"]
# ///
"""Secrets from the OS credential store (Windows Credential Manager via keyring).

uv run scripts/get_secret.py set szamlazz.hu agent-key
uv run scripts/get_secret.py check
"""

from __future__ import annotations

import argparse
import getpass
import sys

import keyring

SECRETS: list[tuple[str, str, str]] = [
    ("szamlazz.hu", "agent-key", "Számla Agent kulcs"),
    ("nav.gov.hu", "tech-login", "NAV technikai felhasználó neve"),
    ("nav.gov.hu", "tech-password", "NAV technikai felhasználó jelszava"),
    ("nav.gov.hu", "signing-key", "NAV aláírókulcs"),
    ("nav.gov.hu", "tax-number", "Adószám első 8 számjegye"),
]


class SecretMissing(Exception):
    """Raised when a required secret is not stored. Message tells her the exact command."""

    def __init__(self, service: str, name: str) -> None:
        self.service = service
        self.name = name
        super().__init__(
            f"Hiányzó titok: {service} / {name}. Tárold el ezzel a paranccsal: "
            f"uv run scripts/get_secret.py set {service} {name}"
        )


def get_secret(service: str, name: str, required: bool = True) -> str | None:
    value = keyring.get_password(service, name)
    if value is None or value == "":
        if required:
            raise SecretMissing(service, name)
        return None
    return value


def set_secret(service: str, name: str, value: str) -> None:
    keyring.set_password(service, name, value)


def check_all() -> list[tuple[str, str, str, str]]:
    """(service, name, label, state) rows; state is 'megvan' | 'hiányzik' | 'hiba: ...'."""
    rows = []
    for service, name, label in SECRETS:
        try:
            value = keyring.get_password(service, name)
        except Exception as exc:  # backend failure, keep the table useful
            state = f"hiba: {type(exc).__name__}"
        else:
            state = "megvan" if value else "hiányzik"
        rows.append((service, name, label, state))
    return rows


def _cmd_set(args: argparse.Namespace) -> int:
    value = getpass.getpass(f"Add meg az értéket ({args.service} / {args.name}), nem látszik: ")
    if not value:
        print("Üres érték, nem mentettem el.")
        return 2
    set_secret(args.service, args.name, value)
    print(f"Elmentve: {args.service} / {args.name}")
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    rows = check_all()
    width = max(len(f"{s} / {n}") for s, n, _, _ in rows)
    print(f"{'Titok'.ljust(width)}  Állapot   Leírás")
    for service, name, label, state in rows:
        print(f"{(service + ' / ' + name).ljust(width)}  {state.ljust(8)}  {label}")
    missing = [r for r in rows if r[3] != "megvan"]
    if missing:
        print()
        print("Hiányzó tétel tárolása: uv run scripts/get_secret.py set <szolgáltatás> <név>")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="get_secret.py", description="Titkok kezelése a Windows hitelesítőtárban."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set", help="Titok eltárolása (az érték beírása nem látszik).")
    p_set.add_argument("service", help="Szolgáltatás, pl. szamlazz.hu vagy nav.gov.hu")
    p_set.add_argument("name", help="Név, pl. agent-key, tech-login, signing-key")
    p_set.set_defaults(func=_cmd_set)
    p_check = sub.add_parser("check", help="Az 5 szükséges titok állapota, értékek nélkül.")
    p_check.set_defaults(func=_cmd_check)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
