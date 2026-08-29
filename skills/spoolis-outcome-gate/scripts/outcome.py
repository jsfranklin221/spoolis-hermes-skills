#!/usr/bin/env python3
"""Call the keyless Spoolis sandbox and inspect signed Outcome Receipts."""

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_URL = "https://spoolis.com"


class OutcomeError(Exception):
    """A user-facing verification or integrity error."""


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def receipt_digests(receipt):
    signed_payload = {key: value for key, value in receipt.items() if key not in ("signature", "signing_key_id")}
    id_body = {key: value for key, value in receipt.items() if key not in ("signature", "signing_key_id", "id")}
    return sha256(signed_payload), sha256(id_body)


def check_receipt(receipt):
    errors = []
    if not isinstance(receipt, dict):
        return ["Receipt must be a JSON object."], None
    if receipt.get("schema") != "spoolis/outcome-receipt@1":
        errors.append("Unknown or missing receipt schema.")
    if receipt.get("algorithm") != "Ed25519":
        errors.append("Unknown or missing signature algorithm.")
    signed_digest, id_digest = receipt_digests(receipt)
    expected_id = "ocr_" + id_digest[:24]
    if receipt.get("id") != expected_id:
        errors.append("Receipt ID does not match the canonical receipt content digest.")
    for path, value in (
        ("agreement.agreement_hash", (receipt.get("agreement") or {}).get("agreement_hash")),
        ("verification.plan_hash", (receipt.get("verification") or {}).get("plan_hash")),
        ("verification.run_digest", (receipt.get("verification") or {}).get("run_digest")),
        ("evidence_root", receipt.get("evidence_root")),
    ):
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            errors.append("%s is not a lowercase SHA-256 digest." % path)
    units = receipt.get("units")
    if units is not None:
        try:
            total = units["total"]
            accepted = units["accepted"]
            rejected = units["rejected"]
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (total, accepted, rejected)):
                raise ValueError
            if accepted + rejected != total:
                errors.append("Accepted and rejected units do not add up to total units.")
            rule = units.get("earning_rule", {})
            if rule.get("type") == "per_unit":
                earned = Decimal(receipt["amounts"]["earned"])
                unit_amount = Decimal(rule["unit_amount"])
                if unit_amount * accepted != earned:
                    errors.append("Earned value does not match accepted units times unit amount.")
        except (KeyError, TypeError, ValueError, InvalidOperation):
            errors.append("Unit or earned-value fields are malformed.")
    return errors, signed_digest


def request_json(opener, method, url, payload=None, token=None):
    data = None if payload is None else canonical_bytes(payload)
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(body)
            message = detail.get("error") or detail.get("message") or body
        except json.JSONDecodeError:
            message = body
        raise OutcomeError("Spoolis returned HTTP %s: %s" % (error.code, message)) from error
    except urllib.error.URLError as error:
        raise OutcomeError("Could not reach Spoolis: %s" % error.reason) from error
    try:
        result = json.loads(body)
    except json.JSONDecodeError as error:
        raise OutcomeError("Spoolis returned invalid JSON.") from error
    if isinstance(result, dict) and result.get("status") in ("limit_reached", "rate_limited", "resting", "unavailable"):
        raise OutcomeError("Spoolis did not verify the Outcome: %s" % (result.get("message") or result["status"]))
    return result


def verify_payload(source_input):
    allowed = {"conditions", "max_amount_cents", "unit", "evidence", "settlement", "idempotency_key"}
    extra = set(source_input) - allowed
    if extra:
        raise OutcomeError("Unsupported verification field(s): %s" % ", ".join(sorted(extra)))
    if source_input.get("settlement", "external") != "external":
        raise OutcomeError("The keyless sandbox supports settlement set to external only.")
    payload = dict(source_input)
    payload["settlement"] = "external"
    return payload


def run_verify(input_path, output_path=None, base_url=BASE_URL, opener=None):
    try:
        source_input = json.loads(Path(input_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OutcomeError("Could not read criteria and evidence JSON: %s" % error) from error
    if not isinstance(source_input, dict):
        raise OutcomeError("Criteria and evidence input must be a JSON object.")
    opener = opener or urllib.request.build_opener()
    base_url = base_url.rstrip("/")
    session = request_json(opener, "POST", base_url + "/api/sandbox/session", {})
    token = session.get("token") if isinstance(session, dict) else None
    if not token:
        raise OutcomeError("Sandbox session response is missing token.")
    outcome = request_json(opener, "POST", base_url + "/api/sandbox/verify", verify_payload(source_input), token)
    receipt = outcome.get("receipt") if isinstance(outcome, dict) else None
    if not isinstance(receipt, dict):
        raise OutcomeError("Verification response is missing the signed receipt.")
    if output_path:
        Path(output_path).write_text(json.dumps(outcome, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return outcome


def render_outcome(outcome):
    receipt = outcome["receipt"]
    signed_digest, _ = receipt_digests(receipt)
    lines = [
        "Outcome: %s" % receipt.get("result", "unknown"),
        "Conditions:",
    ]
    conditions = receipt.get("condition_results") or []
    if not conditions:
        lines.append("  (none reported)")
    for index, condition in enumerate(conditions, 1):
        detail = "  %d. %s: %s" % (index, condition.get("condition_id", "unknown"), condition.get("result", "unknown"))
        if condition.get("reason"):
            detail += " (%s)" % condition["reason"]
        lines.append(detail)
    units = receipt.get("units")
    accepted = outcome.get("accepted", units.get("accepted") if units else 0)
    rejected = outcome.get("rejected", units.get("rejected") if units else 0)
    lines.extend([
        "Accepted units: %s" % accepted,
        "Rejected units: %s" % rejected,
    ])
    for rejection in outcome.get("rejections", []):
        lines.append("  Rejected unit %s: %s" % (rejection.get("unit", "unknown"), rejection.get("reason", "No reason reported.")))
    amounts = receipt.get("amounts") or {}
    lines.extend([
        "Earned value: %s %s" % (amounts.get("earned", "unknown"), amounts.get("asset", "")),
        "Receipt ID: %s" % receipt.get("id", "unknown"),
        "Receipt URL: %s" % outcome.get("receipt_url", "not provided"),
        "Canonical signed-payload SHA-256: %s" % signed_digest,
        "Signature algorithm: %s" % receipt.get("algorithm", "unknown"),
        "Signing key ID: %s" % receipt.get("signing_key_id", "unknown"),
        "Signature: %s" % receipt.get("signature", "unknown"),
        "Signed Outcome receipt:",
        json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True),
    ])
    return "\n".join(lines)


def load_outcome(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OutcomeError("Could not read Outcome JSON: %s" % error) from error
    if isinstance(value, dict) and isinstance(value.get("receipt"), dict):
        return value["receipt"], value.get("receipt_url")
    if isinstance(value, dict):
        return value, None
    raise OutcomeError("Outcome JSON must be a receipt or an object containing receipt.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify criteria plus evidence in one call")
    verify_parser.add_argument("input", help="criteria and evidence JSON file")
    verify_parser.add_argument("--output", help="write the complete Outcome response to this file")
    verify_parser.add_argument("--base-url", default=BASE_URL, help=argparse.SUPPRESS)
    check_parser = subparsers.add_parser("check", help="re-check canonical receipt integrity offline")
    check_parser.add_argument("outcome", help="Outcome response or receipt JSON file")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            outcome = run_verify(args.input, args.output, args.base_url)
            print(render_outcome(outcome))
            return 0
        receipt, receipt_url = load_outcome(args.outcome)
        errors, digest = check_receipt(receipt)
        if errors:
            print("Integrity check failed:", file=sys.stderr)
            for error in errors:
                print("- " + error, file=sys.stderr)
            return 1
        print("Canonical receipt ID and content digest match.")
        print("Canonical signed-payload SHA-256: " + digest)
        if receipt_url:
            print("Hosted receipt URL: " + receipt_url)
        print("Note: this stdlib-only check did not verify the Ed25519 signature. Authoritative signature verification requires re-fetching the hosted receipt URL from Spoolis.")
        return 0
    except OutcomeError as error:
        print("Error: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
