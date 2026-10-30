# app/services/scrubber.py
import re


def extract_anonymous_demographics(text: str) -> dict:
    """
    Extracts Age and Gender strictly from the top patient header (first 600 chars)
    and ignores lines containing 'reference', 'range', or 'interval' so it never
    picks the wrong gender from reference-range tables!
    """
    header_lines = []
    for line in text[:700].splitlines():
        if not re.search(r"\b(reference|range|interval|biological|normal\s+val)\b", line, re.IGNORECASE):
            header_lines.append(line)
    header_text = "\n".join(header_lines)

    # 1. Gender in header
    gender_match = re.search(
        r"(?:Sex|Gender)\s*[:\-/|]?\s*\b(Male|Female|M|F|Other)\b",
        header_text,
        re.IGNORECASE,
    )
    if not gender_match:
        gender_match = re.search(r"\b(Male|Female)\b", header_text, re.IGNORECASE)

    # 2. Age in header
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
    """
    Fixed PII Scrubber:
    - Never corrupts units like mg/dL or g/dL.
    - Preserves report dates.
    - Redacts Name, Father/Spouse Name (S/O, W/O, D/O), DOB, PAN, Aadhaar, Pincode,
      spaced Indian/International phones, Emails, Passport/UHID/GCC IDs, and Clinics.
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

    # 1. Emails
    scrubbed, c = re.subn(
        r"(?:E?-?mail\s*(?:ID)?\s*[:\-]?\s*)?\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b",
        "[EMAIL_REDACTED]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    redaction_counts["emails"] += c

    # 2. PAN Card ([A-Z]{5}[0-9]{4}[A-Z]) & Aadhaar (12 digits or masked XXXX-XXXX-1234)
    scrubbed, c = re.subn(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "[PAN_REDACTED]", scrubbed)
    redaction_counts["medical_and_govt_ids"] += c

    scrubbed, c = re.subn(
        r"\b(?:\d{4}[\s\-]\d{4}[\s\-]\d{4}|[Xx\*]{4}[\s\-]?[Xx\*]{4}[\s\-]?\d{4})\b",
        "[AADHAAR_REDACTED]",
        scrubbed,
    )
    redaction_counts["medical_and_govt_ids"] += c

    # 3. Date of Birth (DOB) — only when labeled as DOB/Birth so report dates stay intact!
    scrubbed, c = re.subn(
        r"(?i)\b(D\.?O\.?B\.?|Date\s*of\s*Birth)\s*[:\-\|]?\s*\d{1,2}[\-/\.][A-Za-z0-9]{2,3}[\-/]\d{2,4}",
        r"\1: [DOB_REDACTED]",
        scrubbed,
    )
    redaction_counts["medical_and_govt_ids"] += c

    # 4. Labeled & Spaced Phone / Fax / Mobile Numbers
    labeled_phone = (
        r"(?i)(?:Phone|Ph|Tel|Telephone|Mobile|Mob|Cell|Fax|Contact(?:\s*No)?)"
        r"\s*[:\-\.]?\s*\+?[0-9][0-9\s\-\(\)]{6,16}[0-9]"
    )
    scrubbed, c = re.subn(labeled_phone, "[PHONE_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += c

    # Spaced Indian (+91 98765 43210) & GCC/International mobile numbers
    spaced_phone = r"(?:\+?\d{1,3}[\s\-]?)?\b[6-9]\d{4}[\s\-]?\d{5}\b|\b(?:966|971|965)\s*\d[\d\s]{7,9}\b"
    scrubbed, c = re.subn(spaced_phone, "[PHONE_REDACTED]", scrubbed)
    redaction_counts["phone_and_fax"] += c

    # 5. Labeled Names (Patient Name, Name, Father's Name, S/O, D/O, W/O, Referred By)
    labeled_name = (
        r"(?i)\b(Patient\s*Name|Pt\.?\s*Name|Candidate\s*Name|Customer\s*Name|"
        r"Father'?s\s*Name|Husband'?s\s*Name|Mother'?s\s*Name|S/O|D/O|W/O|C/O|"
        r"Ref(?:erred)?\s*By|Ref\.?\s*Doctor|Consultant|Doctor'?s\s*name|S[i]?gnature|Name)"
        r"\s*[:\-\.]+\s*([^\n\|]{2,40})"
    )
    scrubbed, c = re.subn(labeled_name, r"\1: [NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += c

    # 6. Honorifics + Names (Handles Mr/Ms.MOHSINSHARIF, DR.AYISHACH, Mr. Rahul, etc.)
    honorifics = (
        r"(?:Mr\s*/?\s*Ms|Mr\.|Mrs\.|Ms\.|Miss|Master|Dr\.|DR\.|Smt\.|Shri|Kumari)"
        r"[\.\s]*([A-Z][A-Za-z\.\s]{2,35})(?=\s*\||\s*\n|$|\s+who\b)"
    )
    scrubbed, c = re.subn(honorifics, "[NAME_REDACTED]", scrubbed)
    redaction_counts["names_and_doctors"] += c

    # 7. Medical, Passport, GCC & Lab IDs
    id_pattern = (
        r"(?i)\b(G\.?H\.?C\.?\s*Code(?:\s*No\.?)?|GCC\s*Slip(?:\s*No\.?)?|Passport\s*No\.?|"
        r"UHID|Patient\s*ID|Lab\s*ID|Sample\s*ID|Reg(?:istration)?\.?\s*No|"
        r"Barcode(?:\s*No)?|MRN|ABHA(?:\s*ID)?)\s*(?:\|\s*)?[:\-\.]?\s*([0-9A-Za-z\-\/]{4,25})"
    )
    scrubbed, c = re.subn(id_pattern, r"\1: [ID_REDACTED]", scrubbed)
    redaction_counts["medical_and_govt_ids"] += c

    # 8. Pincodes, P.O. Boxes, Addresses & Specific Clinic Names (Fixed so mg/dL is NEVER touched!)
    address_clinic = (
        r"(?i)(P\.?O\.?\s*Box[^\n\|]+|"
        r"\b(?:Address|Location|Collection\s*Center)\s*[:\-\.]+\s*[^\n\|]+|"
        r"\b[A-Z][A-Za-z\s]{2,25}\s+(?:Medical\s*Cent(?:re|er)|Hospital|Diagnostics|PathLabs|Polyclinic)\b|"
        r"\b(?:Pin(?:\s*Code)?\s*[:\-]?\s*)?[1-9]\d{2}\s?\d{3}\b(?=\s*\||\s*\n|$))"
    )
    scrubbed, c = re.subn(address_clinic, "[ADDRESS_OR_CLINIC_REDACTED]", scrubbed)
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