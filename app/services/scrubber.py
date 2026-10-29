import re


def extract_anonymous_demographics(text: str) -> dict:
    """
    Captures Age and Gender even on multi-column forms where the label ('Age', 'Gender')
    is printed on the line above the value ('23', 'Male').
    """
    # 1. Catch Gender anywhere in the header/text
    gender_match = re.search(r"\b(Male|Female)\b", text, re.IGNORECASE)
    if not gender_match:
        gender_match = re.search(
            r"(?:Sex|Gender)\s*[:\-/|]?\s*(M|F|Other)\b", text, re.IGNORECASE
        )

    # 2. Catch Age (either "Age: 23" OR when "23" appears near "Age" or "BMI" or "Weight")
    age_match = re.search(
        r"(?:Age|Yrs|Years)\s*[:\-/|]?\s*(\d{1,3})\b", text, re.IGNORECASE
    )
    if not age_match:
        # Handle stacked forms where 'Age' is in the header and a 2-digit age (1-99) is nearby
        header_slice = text[:800]
        stacked_age = re.search(
            r"\b(?:Unmarried|Married|Single)\b.*?\b([1-8]\d)\b",
            header_slice,
            re.IGNORECASE | re.DOTALL,
        )
        if stacked_age:
            age_match = stacked_age

    age = f"{age_match.group(1).strip()} Years" if age_match else "Not specified"
    gender = gender_match.group(1).capitalize() if gender_match else "Not specified"

    return {"age": age, "gender": gender}


def scrub_personal_details(raw_text: str) -> dict:
    """
    Removes PII/PHI including international phone/fax numbers, merged OCR names
    (like Mr/Ms.MOHSINSHARIF or DR.AYISHACH), P.O. Boxes, Medical Centers, and IDs.
    """
    demographics = extract_anonymous_demographics(raw_text)
    scrubbed = raw_text
    redaction_counts = {
        "names_and_doctors": 0,
        "phone_and_fax": 0,
        "emails": 0,
        "medical_and_govt_ids": 0,
        "addresses_and_clinics": 0,
    }

    # 1. Scrub Emails (including OCR typos like EmalID:info@...)
    scrubbed, count = re.subn(
        r"(?:E?-?mail\s*(?:ID)?\s*[:\-]?\s*)?\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b",
        "[EMAIL_REDACTED]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    redaction_counts["emails"] += count

    # 2. Scrub Labeled Phone / Fax / Mobile Numbers (even with NO spaces, e.g., Phone:96614885270 or Fax96614885266)
    labeled_phone_pattern = (
        r"(?i)(?:Phone|Ph|Tel|Telephone|Mobile|Mob|Cell|Fax|Contact(?:\s*No)?)"
        r"\s*[:\-\.]?\s*\+?[0-9][0-9\s\-\(\)]{6,16}[0-9]"
    )
    scrubbed, count = re.subn(labeled_phone_pattern, "[PHONE_OR_FAX_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += count

    # 3. Scrub Standalone Phone Numbers (Indian 10-digit & International +966 / +971 / +91 formats)
    standalone_phone_pattern = (
        r"(?:\+\d{1,3}[\s\-]?)?\b(?:966|971|965|968|974|973)?[5-9]\d{8,9}\b"
    )
    scrubbed, count = re.subn(standalone_phone_pattern, "[PHONE_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += count

    # 4. Scrub Honorifics + Names (Handles "Mr/Ms.MOHSINSHARIF", "DR.AYISHACH", "Mr. Rahul", etc.)
    honorific_pattern = (
        r"(?:Mr\s*/?\s*Ms|Mr\.|Mrs\.|Ms\.|Miss|Master|Dr\.|DR\.|Smt\.|Shri)"
        r"[\.\s]*([A-Z][A-Za-z\.\s]{2,35})(?=\s*\||\s*\n|$|\s+who\b)"
    )
    scrubbed, count = re.subn(honorific_pattern, "[NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += count

    # 5. Scrub Certificate Phrases ("medical report for ...", "Doctor's name ...", "Signature ...")
    phrase_name_pattern = (
        r"(?i)(report\s*for\s*|Doctor'?s\s*name\s*\|?\s*|S[i]?gnature\s*\|?\s*)"
        r"([A-Za-z0-9\./\s]{3,35})(?=\s*\||\s*\n|$)"
    )
    scrubbed, count = re.subn(phrase_name_pattern, r"\1[NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += count

    # 6. Scrub Labeled Patient / Doctor / Candidate Names
    labeled_name_pattern = (
        r"(?i)\b(Patient\s*Name|Pt\.?\s*Name|Candidate\s*Name|Customer\s*Name|"
        r"Ref(?:erred)?\s*By|Consultant)\s*[:\-\.]+\s*([^\n\|]+)"
    )
    scrubbed, count = re.subn(labeled_name_pattern, r"\1: [NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += count

    # 7. Scrub Medical, Passport, GCC & Govt IDs (e.g., GHC Code, GCC Slip, Passport No, QW9143, UHID)
    id_pattern = (
        r"(?i)\b(G\.?H\.?C\.?\s*Code(?:\s*No\.?)?|GCC\s*Slip(?:\s*No\.?)?|Passport\s*No\.?|"
        r"UHID|Patient\s*ID|Lab\s*ID|Sample\s*ID|Reg(?:istration)?\.?\s*No|"
        r"Barcode(?:\s*No)?|MRN|ABHA(?:\s*ID)?|Aadhaar)\s*(?:\|\s*)?[:\-\.]?\s*([0-9A-Za-z\-\/:]{4,25})"
    )
    scrubbed, count = re.subn(id_pattern, r"\1: [ID_REDACTED]", scrubbed)
    redaction_counts["medical_and_govt_ids"] += count

    # Also scrub standalone GCC/Lab tracking codes like QW9143 or 02/04/02
    scrubbed, count = re.subn(
        r"\b[A-Z]{2}\d{4,8}\b|\b\d{2}[:/]\d{2}[:/]\d{2}\b",
        "[CODE_REDACTED]",
        scrubbed,
    )
    redaction_counts["medical_and_govt_ids"] += count

    # 8. Scrub P.O. Box, Addresses & Medical Center Names
    address_clinic_pattern = (
        r"(?i)(P\.?O\.?\s*Box[^\n\|]+|"
        r"\b[A-Za-z\s]{3,25}(?:Medical\s*Cent(?:re|er)|Hospital|Diagnostics|Clinic|Labs?)\b|"
        r"(?:Address|Location)\s*[:\-\.]+\s*([^\n\|]+))"
    )
    scrubbed, count = re.subn(
        address_clinic_pattern, "[CLINIC_OR_ADDRESS_REDACTED]", scrubbed
    )
    redaction_counts["addresses_and_clinics"] += count

    header = (
        f"--- ANONYMIZED PATIENT CONTEXT ---\n"
        f"Age: {demographics['age']} | Gender: {demographics['gender']}\n"
        f"----------------------------------\n\n"
    )

    return {
        "demographics_preserved": demographics,
        "redaction_summary": redaction_counts,
        "total_redactions": sum(redaction_counts.values()),
        "clean_text": header + scrubbed,
    }