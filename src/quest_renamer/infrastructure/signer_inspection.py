"""Read-only APK signer inspection backed by the bundled signing tool."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from quest_renamer.domain.inspection import CertificateDetail, SignatureDetail
from quest_renamer.domain.operations import CancellationToken
from quest_renamer.domain.signers import (
    SignerIdentity,
    SignerRegistryEntry,
    extract_rdn,
    identify_signer,
)
from quest_renamer.infrastructure.process_runner import ProcessRunner


def load_signer_registry(path: Path) -> tuple[SignerRegistryEntry, ...]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict) or not isinstance(payload.get("signers"), list):
        return ()
    entries: list[SignerRegistryEntry] = []
    for raw in payload["signers"]:
        if not isinstance(raw, dict):
            continue
        signer_id = raw.get("id")
        label = raw.get("label")
        needles = raw.get("dn_contains")
        if not isinstance(signer_id, str) or not isinstance(label, str):
            continue
        if not isinstance(needles, list) or not all(
            isinstance(value, str) for value in needles
        ):
            continue
        full_name = raw.get("full_name", label)
        color = raw.get("color", "#9b9b9b")
        entries.append(
            SignerRegistryEntry(
                signer_id,
                label,
                full_name if isinstance(full_name, str) else label,
                color if isinstance(color, str) else "#9b9b9b",
                tuple(needles),
            )
        )
    return tuple(entries)


def _first_certificate_subject(output: str) -> tuple[str | None, str | None]:
    """Parse both apksigner-style and uber-apk-signer-style certificate lines."""
    prefix = r"Signer\s*#1\s+certificate\s+"
    subject_match = re.search(
        prefix + r"(?:DN|subject)\s*:\s*([^\n\r]+)", output, re.IGNORECASE
    )
    issuer_match = re.search(prefix + r"issuer\s*:\s*([^\n\r]+)", output, re.IGNORECASE)
    if subject_match:
        return (
            subject_match.group(1).strip(),
            issuer_match.group(1).strip() if issuer_match else None,
        )

    subject_match = re.search(
        r"^\s*(?:-\s*)?Subject\s*:\s*([^\n\r]+)",
        output,
        re.IGNORECASE | re.MULTILINE,
    )
    issuer_match = re.search(
        r"^\s*(?:-\s*)?Issuer\s*:\s*([^\n\r]+)",
        output,
        re.IGNORECASE | re.MULTILINE,
    )
    return (
        subject_match.group(1).strip() if subject_match else None,
        issuer_match.group(1).strip() if issuer_match else None,
    )


def parse_signer_identity(
    output: str,
    registry: tuple[SignerRegistryEntry, ...],
) -> SignerIdentity | None:
    subject, issuer = _first_certificate_subject(output)
    return identify_signer(subject, issuer, registry)


def _digest(patterns: tuple[str, ...], text: str) -> str:
    for pattern in patterns:
        if match := re.search(pattern, text, re.IGNORECASE):
            return re.sub(r"[^0-9a-f]", "", match.group(1)).lower()
    return ""


def parse_signature_details(
    output: str,
    registry: tuple[SignerRegistryEntry, ...],
    *,
    error: str = "",
) -> SignatureDetail:
    schemes: list[str] = []
    for number in (1, 2, 3):
        enabled = bool(
            re.search(
                rf"(?:verified\s+using\s+v{number}\s+scheme|"
                rf"(?:signature\s+)?scheme\s+v{number}|v{number}\s+scheme)"
                rf"[^\n]*(?:true|verified|success)",
                output,
                re.IGNORECASE,
            )
        )
        if not enabled:
            signed_list = re.search(
                r"signed\s+with\s+(?:the\s+)?following\s+schemes?\s*:\s*([^\n]+)",
                output,
                re.IGNORECASE,
            )
            enabled = bool(
                signed_list and re.search(rf"\bv{number}\b", signed_list.group(1), re.I)
            )
        if not enabled:
            verified_list = re.search(
                r"signature\s+verified\s*\[([^\]]+)\]", output, re.IGNORECASE
            )
            enabled = bool(
                verified_list and re.search(rf"\bv{number}\b", verified_list.group(1), re.I)
            )
        if enabled:
            schemes.append(f"v{number}")

    certificates: list[CertificateDetail] = []
    signer_numbers = sorted(
        {
            int(value)
            for value in re.findall(r"Signer\s*#(\d+)\s+certificate", output, re.IGNORECASE)
        }
    )
    for number in signer_numbers:
        prefix = rf"Signer\s*#{number}\s+certificate\s+"
        subject = re.search(prefix + r"(?:DN|subject)\s*:\s*([^\n\r]+)", output, re.IGNORECASE)
        issuer = re.search(prefix + r"issuer\s*:\s*([^\n\r]+)", output, re.IGNORECASE)
        certificates.append(
            CertificateDetail(
                subject.group(1).strip() if subject else "",
                issuer.group(1).strip() if issuer else "",
                _digest(
                    (prefix + r"SHA-?256\s+(?:digest\s*)?:\s*([0-9a-f:\s]{64,})",),
                    output,
                ),
                _digest(
                    (prefix + r"SHA-?1\s+(?:digest\s*)?:\s*([0-9a-f:\s]{40,})",),
                    output,
                ),
            )
        )
    if not signer_numbers:
        subjects = re.findall(
            r"^\s*(?:-\s*)?Subject\s*:\s*([^\n\r]+)",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
        issuers = re.findall(
            r"^\s*(?:-\s*)?Issuer\s*:\s*([^\n\r]+)",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
        sha256s = re.findall(
            r"^\s*(?:-\s*)?SHA-?256\s*:\s*([0-9a-f:]{64,})",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
        sha1s = re.findall(
            r"^\s*(?:-\s*)?SHA-?1\s*:\s*([0-9a-f:]{40,})",
            output,
            re.IGNORECASE | re.MULTILINE,
        )
        for index, subject in enumerate(subjects):
            certificates.append(
                CertificateDetail(
                    subject.strip(),
                    issuers[index].strip() if index < len(issuers) else "",
                    re.sub(r"[^0-9a-f]", "", sha256s[index]).lower()
                    if index < len(sha256s)
                    else "",
                    re.sub(r"[^0-9a-f]", "", sha1s[index]).lower()
                    if index < len(sha1s)
                    else "",
                )
            )
    verified = bool(
        schemes
        or re.search(
            r"(?:file-signature\s+verified|signature\s+(?:is\s+valid|verified)|"
            r"verified\s*:\s*true)",
            output,
            re.IGNORECASE,
        )
    )
    identity = (
        identify_signer(certificates[0].subject, certificates[0].issuer, registry)
        if certificates
        else None
    )
    locality = extract_rdn(certificates[0].subject, "L") if certificates else None
    lineage = (
        locality
        if locality
        and (
            locality.lower().startswith("previously signed by")
            or locality.lower() == "fresh rename"
        )
        else ""
    )
    return SignatureDetail(
        signed=bool(certificates or schemes),
        verified=verified,
        schemes=tuple(schemes),
        certificates=tuple(certificates),
        identity=identity,
        error=error,
        lineage=lineage,
    )


def inspect_signer_identity(
    apk: Path,
    *,
    java: Path,
    signer: Path,
    registry: tuple[SignerRegistryEntry, ...],
    runner: ProcessRunner,
    token: CancellationToken,
) -> SignerIdentity | None:
    result = runner.run(
        (
            java,
            "-jar",
            signer,
            "--apks",
            apk,
            "--onlyVerify",
            "--verbose",
        ),
        token=token,
        check=False,
    )
    return parse_signature_details("\n".join(result.output), registry).identity


def inspect_signature_details(
    apk: Path,
    *,
    java: Path,
    signer: Path,
    registry: tuple[SignerRegistryEntry, ...],
    runner: ProcessRunner,
    token: CancellationToken,
) -> SignatureDetail:
    result = runner.run(
        (java, "-jar", signer, "--apks", apk, "--onlyVerify", "--verbose"),
        token=token,
        check=False,
    )
    error = ""
    if result.returncode != 0:
        error = "The APK signature could not be verified."
    return parse_signature_details("\n".join(result.output), registry, error=error)
