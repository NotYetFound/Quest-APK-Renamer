"""Signer recognition and certificate-lineage naming rules.

The rules in this module are deliberately independent of Java and the UI so
they can be reused by automatic analysis, builds, and the future APK inspector.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DN_VALUE_MAX_LENGTH = 200
_DN_RESERVED = ',"\\=<>;+'


@dataclass(frozen=True, slots=True)
class SignerIdentity:
    id: str
    label: str
    full_name: str
    color: str = "#9b9b9b"

    @property
    def recognized(self) -> bool:
        return self.id not in {"", "unknown"}


@dataclass(frozen=True, slots=True)
class SignerRegistryEntry:
    id: str
    label: str
    full_name: str
    color: str
    dn_contains: tuple[str, ...]


def extract_rdn(dn: str | None, key: str) -> str | None:
    """Extract one relative distinguished-name value from a certificate DN."""
    if not dn:
        return None
    match = re.search(
        rf"(?:^|,)\s*{re.escape(key)}\s*=\s*((?:\\.|[^,])*)",
        dn,
        re.IGNORECASE,
    )
    return match.group(1).replace("\\,", ",").strip() if match else None


def identify_signer(
    subject: str | None,
    issuer: str | None,
    registry: tuple[SignerRegistryEntry, ...],
) -> SignerIdentity | None:
    """Recognize a signer using CN/O only, with first registry match winning.

    OU intentionally holds the user's rename tag and L may hold an embedded
    lineage breadcrumb. Excluding both prevents those fields from recognizing
    an APK as a signer it merely mentions.
    """
    if not subject and not issuer:
        return None
    searchable: list[str] = []
    for dn in (subject, issuer):
        for key in ("CN", "O"):
            value = extract_rdn(dn, key)
            if value:
                searchable.extend((value, f"{key}={value}"))
    haystack = " ".join(searchable).lower()
    for entry in registry:
        if any(needle.lower() in haystack for needle in entry.dn_contains):
            return SignerIdentity(entry.id, entry.label, entry.full_name, entry.color)
    common_name = extract_rdn(subject, "CN")
    return SignerIdentity(
        "unknown",
        common_name or "Unknown signer",
        common_name or "Unrecognized signing certificate",
        "#b9975b",
    )


def sanitize_dn_value(value: str | None, max_length: int = DN_VALUE_MAX_LENGTH) -> str:
    """Remove characters that could terminate a keytool dname field and cap it."""
    if not value:
        return ""
    cleaned = "".join(character for character in str(value) if character not in _DN_RESERVED)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_length].strip()


def describe_previous_signer(identity: SignerIdentity | None) -> tuple[str, str] | None:
    """Return the display name and label only for a recognized source signer."""
    if identity is None or not identity.recognized or not identity.full_name:
        return None
    return identity.full_name, identity.label or identity.full_name


def build_lineage_dn(
    *,
    signer_name: str = "Quest APK Renamer",
    signature_text: str = "Renamed build",
    short_code: str = "QAR",
    previous: tuple[str, str] | None = None,
) -> str:
    """Build the certificate DN used by a provenance-embedded signing key."""
    common_name = sanitize_dn_value(signer_name) or "Quest APK Renamer"
    organizational_unit = sanitize_dn_value(signature_text) or "Renamed build"
    organization = sanitize_dn_value(short_code) or "QAR"
    if previous:
        full_name = sanitize_dn_value(previous[0])
        label = sanitize_dn_value(previous[1])
        if full_name and label and label.lower() != full_name.lower():
            locality = sanitize_dn_value(f"Previously signed by {full_name} ({label})")
        elif full_name:
            locality = sanitize_dn_value(f"Previously signed by {full_name}")
        else:
            locality = "Fresh rename"
    else:
        locality = "Fresh rename"
    return f"CN={common_name}, OU={organizational_unit}, O={organization}, L={locality}"


def rename_signature_text(old_package: str, new_package: str) -> str:
    """Describe an appended suffix or inserted namespace tag for certificate OU."""
    old_package = (old_package or "").strip()
    new_package = (new_package or "").strip()
    if not new_package or new_package == old_package:
        return "Renamed build"
    if old_package and new_package.startswith(old_package):
        added = new_package[len(old_package) :].lstrip(".")
        if added:
            return added
    old_parts = old_package.split(".") if old_package else []
    new_parts = new_package.split(".")
    if (
        len(new_parts) == len(old_parts) + 1
        and old_parts
        and new_parts[0] == old_parts[0]
        and new_parts[2:] == old_parts[1:]
    ):
        return new_parts[1]
    return "Renamed build"
