# app/services/scrubber.py
import re


def extract_anonymous_demographics(text: str) -> dict:
    """
    Scans up to the first 2,000 chars for Age and Gender while filtering out
    any lines containing reference range keywords.
    """
    header_lines = []
    for line in text[:2000].splitlines():
        if not re.search(
            r"\b(reference|range|interval|biological|normal\s+val|desirable|borderline)\b",
            line,
            re.IGNORECASE,
        ):
            header_lines.append(line)
    header_text = "\n".join(header_lines)

    gender_match = re.search(
        r"(?:Sex|Gender)\s*[:\-/|]?\s*\b(Male|Female|M|F|Other)\b",
        header_text,
        re.IGNORECASE,
    )
    if not gender_match:
        gender_match = re.search(r"\b(Male|Female)\b", header_text, re.IGNORECASE)

    age_match = re.search(
        r"(?:Age|Yrs|Years)\s*[:\-/|]?\s*(\d{1,3})\b", header_text, re.IGNORECASE
    )
    if not age_match:
        stacked_age = re.search(
            r"\b(?:Unmarried|Married|Single)\b.*?\b([1-8]\d)\b",
            header_text,
            re.IGNORECASE | re.DOTALL,
        )
        if stacked_age:
            age_match = stacked_age

    raw_gender = gender_match.group(1).upper() if gender_match else ""
    if raw_gender == "M":
        gender = "Male"
    elif raw_gender == "F":
        gender = "Female"
    elif raw_gender:
        gender = raw_gender.capitalize()
    else:
        gender = "Not specified"

    age = f"{age_match.group(1).strip()} Years" if age_match else "Not specified"
    return {"age": age, "gender": gender}


def scrub_personal_details(raw_text: str) -> dict:
    demographics = extract_anonymous_demographics(raw_text)
    scrubbed = raw_text
    redaction_counts = {
        "names_and_doctors": 0,
        "phone_and_fax": 0,
        "emails": 0,
        "medical_and_govt_ids": 0,
        "addresses_and_clinics": 0,
    }

    # 1. Emails
    scrubbed, c = re.subn(
        r"(?:E?-?mail[ \t]*(?:ID)?[ \t]*[:\-]?[ \t]*)?\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b",
        "[EMAIL_REDACTED]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    redaction_counts["emails"] += c

    # 2. PAN Card & Aadhaar (Full or partial/masked XXXX-XXXX-1234)
    scrubbed, c = re.subn(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "[PAN_REDACTED]", scrubbed)
    redaction_counts["medical_and_govt_ids"] += c

    scrubbed, c = re.subn(
        r"(?i)\b(?:Aadhaar[ \t]*(?:No|Number)?[ \t]*[:\-]?[ \t]*[0-9Xx\*\- ]{4,16}|\d{4}[ \t\-]\d{4}[ \t\-]\d{4}|[Xx\*]{4}[ \t\-]?[Xx\*]{4}[ \t\-]?\d{4})\b",
        "[AADHAAR_REDACTED]",
        scrubbed,
    )
    redaction_counts["medical_and_govt_ids"] += c

    # 3. Date of Birth (Handles slashes, hyphens, AND spaces like "DOB 14 Mar 1985" or "DOB: 14 March 1985")
    scrubbed, c = re.subn(
        r"(?i)\b(D\.?O\.?B\.?|Date[ \t]*of[ \t]*Birth)[ \t]*[:\-\|]?[ \t]*\d{1,2}[ \t\-/\.]+[A-Za-z0-9]{2,9}[ \t\-/\.]+\d{2,4}",
        r"\1: [DOB_REDACTED]",
        scrubbed,
    )
    redaction_counts["medical_and_govt_ids"] += c

    # 4. Labeled & Spaced Phone / Fax Numbers
    labeled_phone = (
        r"(?i)(?:Phone|Ph|Tel|Telephone|Mobile|Mob|Cell|Fax|Contact(?:[ \t]*No)?)"
        r"[ \t]*[:\-\.]?[ \t]*\+?[0-9][0-9 \t\-\(\)]{6,16}[0-9]"
    )
    scrubbed, c = re.subn(labeled_phone, "[PHONE_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += c

    spaced_phone = r"(?:\+?\d{1,3}[ \t\-]?)?\b[6-9]\d{4}[ \t\-]?\d{5}\b|\b(?:966|971|965)[ \t]*\d[\d \t]{7,9}\b"
    scrubbed, c = re.subn(spaced_phone, "[PHONE_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += c

    # 5. Labeled Names (Includes standalone "Patient:", "Name:", "Father's Name:", "S/O", etc.)
    labeled_name = (
        r"(?i)\b(Patient(?:[ \t]*Name)?|Pt\.?[ \t]*Name|Candidate[ \t]*Name|Customer[ \t]*Name|"
        r"Father'?s[ \t]*Name|Husband'?s[ \t]*Name|Mother'?s[ \t]*Name|S/O|D/O|W/O|C/O|"
        r"Ref(?:erred)?[ \t]*By|Ref\.?[ \t]*Doctor|Consultant|Doctor'?s[ \t]*name|S[i]?gnature|Name)"
        r"[ \t]*[:\-\.]+[ \t]*([^\n\|]{2,40})"
    )
    scrubbed, c = re.subn(labeled_name, r"\1: [NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += c

    # 6. Honorifics + Names (Single-line horizontal whitespace [ \t] only!)
    honorifics = (
        r"(?:Mr[ \t]*/?[ \t]*Ms|Mr\.|Mrs\.|Ms\.|Miss|Master|Dr\.|DR\.|Smt\.|Shri|Kumari)"
        r"[\. \t]*([A-Z][A-Za-z\. \t]{2,35})(?=[ \t]*\||[ \t]*\n|$|[ \t]+who\b)"
    )
    scrubbed, c = re.subn(honorifics, "[NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += c

    # 7. Medical, Passport, GCC & Lab IDs
    id_pattern = (
        r"(?i)\b(G\.?H\.?C\.?[ \t]*Code(?:[ \t]*No\.?)?|GCC[ \t]*Slip(?:[ \t]*No\.?)?|Passport[ \t]*No\.?|"
        r"UHID|Patient[ \t]*ID|Lab[ \t]*ID|Sample[ \t]*ID|Reg(?:istration)?\.?[ \t]*No|"
        r"Barcode(?:[ \t]*No)?|MRN|ABHA(?:[ \t]*ID)?)[ \t]*(?:\|[ \t]*)?[:\-\.]?[ \t]*([0-9A-Za-z\-\/]{4,25})"
    )
    scrubbed, c = re.subn(id_pattern, r"\1: [ID_REDACTED]", scrubbed)
    redaction_counts["medical_and_govt_ids"] += c

    # 8. P.O. Box & Labeled Addresses (Horizontal spaces only!)
    labeled_addr = r"(?i)(?:P\.?O\.?[ \t]*Box[^\n\|]+|\b(?:Address|Location|Collection[ \t]*Center)[ \t]*[:\-\.]+[ \t]*[^\n\|]+)"
    scrubbed, c = re.subn(labeled_addr, "[ADDRESS_OR_CLINIC_REDACTED]", scrubbed)
    redaction_counts["addresses_and_clinics"] += c

    # 9. Clinic / Diagnostic Names (Case-sensitive start [A-Z], horizontal spaces [ \t] ONLY so "mg/dL\nSri Sai..." NEVER matches "dL"!)
    clinic_pattern = (
        r"\b[A-Z][A-Za-z0-9&' \t]{1,30}[ \t]+"
        r"(?:Medical[ \t]+Cent(?:re|er)|Hospital|Diagnostics(?:[ \t]+Cent(?:re|er)|[ \t]+Lab)?|PathLabs|Pathology[ \t]+Lab|Polyclinic|Health[ \t]+Centre)\b"
    )
    scrubbed, c = re.subn(clinic_pattern, "[ADDRESS_OR_CLINIC_REDACTED]", scrubbed)
    redaction_counts["addresses_and_clinics"] += c

    # 10. Pincodes (ONLY when labeled as Pin/Pincode OR preceded by "City/Address - 560001", NEVER matching "TSH 560012" or "250000"!)
    pincode_pattern = r"(?i)(?:\b(?:Pin(?:[ \t]*Code)?|Postal[ \t]*Code)[ \t]*[:\-]?[ \t]*[1-9]\d{2}[ \t]?\d{3}\b|(?<=[A-Za-z][ \t]\-[ \t])[1-9]\d{5}\b)"
    scrubbed, c = re.subn(pincode_pattern, "[PINCODE_REDACTED]", scrubbed)
    redaction_counts["addresses_and_clinics"] += c

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