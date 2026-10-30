# tests/test_scrubber.py
from app.services.scrubber import scrub_personal_details


def test_indian_lab_report_pii_scrubbing_and_unit_preservation():
    """
    Verifies that realistic Indian lab report PII (Name, S/O, DOB, PAN, Aadhaar,
    spaced phone, Pincode, Clinic) is redacted, while units (mg/dL, g/dL),
    report dates, and patient header gender/age remain intact!
    """
    sample_indian_report = """
    Apollo Diagnostics Lab | Collection Date: 18/12/2024
    Patient Name: Mr. Rajesh Kumar Sharma | Age: 42 Years | Sex: Male
    S/O: Shri मोहन लाल शर्मा | DOB: 14/08/1982
    Mobile: +91 98765 43210 | Email: rajesh.sharma@gmail.com
    Aadhaar: 4567 8901 2345 | PAN: ABCDE1234F | UHID: AP-998877
    Address: Flat 302, Madhapur, Hyderabad - 500081

    TEST NAME          RESULT      UNIT     BIOLOGICAL REFERENCE RANGE
    Hemoglobin         14.2        g/dL     Male: 13.0 - 17.0, Female: 12.0 - 15.0
    Fasting Glucose    108.5       mg/dL    70 - 100 mg/dL
    Serum Creatinine   0.9         mg/dL    0.7 - 1.3 mg/dL
    L.F.T              Normal
    """

    res = scrub_personal_details(sample_indian_report)
    clean = res["clean_text"]
    demographics = res["demographics_preserved"]

    # 1. Verify PII is completely removed
    assert "Rajesh Kumar" not in clean
    assert "98765 43210" not in clean
    assert "rajesh.sharma@gmail.com" not in clean
    assert "4567 8901 2345" not in clean
    assert "ABCDE1234F" not in clean
    assert "14/08/1982" not in clean
    assert "AP-998877" not in clean
    assert "500081" not in clean

    # 2. Verify clinical units (mg/dL, g/dL) and report date were NOT corrupted!
    assert "mg/dL" in clean
    assert "g/dL" in clean
    assert "18/12/2024" in clean
    assert "14.2" in clean
    assert "108.5" in clean

    # 3. Verify patient header Gender ("Male") was picked, NOT "Female" from reference range
    assert demographics["age"] == "42 Years"
    assert demographics["gender"] == "Male"


def test_glued_ocr_names_and_international_phones():
    """Tests glued OCR strings from GCC/Wafid reports."""
    wafid_snippet = """
    Detailed candidate report | Gender | Male | Unmarried | 23 | Age
    Mentioned above is the medical report for Mr/Ms.MOHSINSHARIF who is Fit
    Doctor's name | DR.AYISHACH
    Phone:96614885270|Fax:96614885266|EmalID:info@wafid.com
    """
    res = scrub_personal_details(wafid_snippet)
    clean = res["clean_text"]

    assert "MOHSINSHARIF" not in clean
    assert "AYISHACH" not in clean
    assert "96614885270" not in clean
    assert "96614885266" not in clean
    assert "info@wafid.com" not in clean
    assert res["demographics_preserved"]["age"] == "23 Years"
    assert res["demographics_preserved"]["gender"] == "Male"

def test_name_review_edge_cases():
    """
    Tests every edge case reported in the branch review:
    - 'mg/dL\\nSri Sai Diagnostics Centre' must NOT eat 'mg/dL'
    - 'TSH 560012' and 'Platelets 250000' must NOT be redacted as pincodes
    - 'Patient: Priya Nair' and 'DOB 14 Mar 1985' must be redacted
    """
    review_sample = (
        "Patient: Priya Nair | DOB 14 Mar 1985 | Age: 39 | Gender: Female\n"
        "Fasting Sugar: 92 mg/dL\n"
        "Sri Sai Diagnostics Centre\n"
        "TSH: 560012 uIU/mL\n"
        "Platelets: 250000 /cumm\n"
        "Pin Code: 560001\n"
    )
    res = scrub_personal_details(review_sample)
    clean = res["clean_text"]

    assert "Priya Nair" not in clean
    assert "14 Mar 1985" not in clean
    assert "560001" not in clean
    assert "Sri Sai Diagnostics Centre" not in clean

    # Units and 6-digit lab numbers MUST remain intact!
    assert "92 mg/dL" in clean
    assert "560012" in clean
    assert "250000" in clean
    assert res["demographics_preserved"]["age"] == "39 Years"
    assert res["demographics_preserved"]["gender"] == "Female"