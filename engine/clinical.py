"""The clinical catalog: what a learner can examine, order, and give.

The catalog is GENERIC and identical for every case. That is deliberate: a list
that changed per case would tell the learner which tests matter. Each item has
a realistic unremarkable default, so a case file only records what is abnormal
(or what is specifically normal and worth teaching).

Units are SI / UK conventions (mmol/L, micromol/L, g/L), matching the guideline
bodies the debrief cites.

`minutes` is simulated turnaround shown to the learner; `delay` is how many
real seconds the result takes to arrive in a practice encounter.
"""

from __future__ import annotations

EXAMS = [
    {"id": "general", "name": "General inspection",
     "normal": "Alert and orientated. Comfortable at rest. No pallor, jaundice, cyanosis or clubbing."},
    {"id": "hands", "name": "Hands and peripheries",
     "normal": "Warm, well-perfused peripheries. Capillary refill under 2 seconds. No palmar erythema, tremor or flap."},
    {"id": "hydration", "name": "Hydration status",
     "normal": "Moist mucous membranes. Normal skin turgor. Not clinically dehydrated."},
    {"id": "cardiovascular", "name": "Cardiovascular",
     "normal": "Pulse regular. Heart sounds I and II with no added sounds or murmurs. JVP not raised. No peripheral oedema."},
    {"id": "respiratory", "name": "Respiratory",
     "normal": "Trachea central. Equal chest expansion. Resonant to percussion. Vesicular breath sounds, no added sounds."},
    {"id": "abdominal", "name": "Abdominal",
     "normal": "Soft and non-tender. No organomegaly or masses. No shifting dullness. Bowel sounds normal."},
    {"id": "neurological", "name": "Neurological",
     "normal": "GCS 15/15. Pupils equal and reactive. Cranial nerves intact. Normal tone, power, reflexes, sensation and coordination."},
    {"id": "cognition", "name": "Cognition (AMTS)",
     "normal": "Abbreviated Mental Test Score 10/10. Attention and short-term recall intact."},
    {"id": "eyes", "name": "Eyes and fundoscopy",
     "normal": "Sclerae white. Visual acuity grossly normal. Fundi: no papilloedema or retinopathy."},
    {"id": "skin", "name": "Skin",
     "normal": "No rash, bruising, petechiae, spider naevi or lesions."},
    {"id": "legs", "name": "Legs and calves",
     "normal": "Calves soft and non-tender. No swelling, erythema or pitting oedema."},
    {"id": "ent", "name": "Ears, nose and throat",
     "normal": "Oropharynx clear. No tonsillar exudate. No lymphadenopathy."},
    {"id": "genitourinary", "name": "Genitourinary",
     "normal": "External genitalia normal. No tenderness or swelling."},
    {"id": "musculoskeletal", "name": "Musculoskeletal",
     "normal": "Full range of movement. No joint swelling, tenderness or deformity."},
]

INVESTIGATIONS = [
    # --- bedside
    {"id": "ecg", "name": "12-lead ECG", "group": "Bedside", "minutes": 5, "delay": 3, "routine": True,
     "normal": "Sinus rhythm. Normal axis. No ST or T-wave changes. Normal intervals."},
    {"id": "cbg", "name": "Capillary blood glucose", "group": "Bedside", "minutes": 1, "delay": 1, "routine": True,
     "normal": "5.8 mmol/L"},
    {"id": "urine_dip", "name": "Urine dipstick", "group": "Bedside", "minutes": 2, "delay": 2, "routine": True,
     "normal": "Glucose negative, ketones negative, protein negative, blood negative, leucocytes negative, nitrites negative."},
    {"id": "blood_ketones", "name": "Capillary blood ketones", "group": "Bedside", "minutes": 1, "delay": 1,
     "normal": "0.2 mmol/L"},
    {"id": "urine_hcg", "name": "Urine pregnancy test (hCG)", "group": "Bedside", "minutes": 3, "delay": 2,
     "normal": "Negative"},
    {"id": "peak_flow", "name": "Peak expiratory flow", "group": "Bedside", "minutes": 2, "delay": 1,
     "normal": "Within 10% of predicted."},
    # --- blood tests
    {"id": "fbc", "name": "Full blood count", "group": "Blood tests", "minutes": 60, "delay": 25, "routine": True,
     "normal": "Hb 142 g/L, WCC 7.2 x10^9/L, neutrophils 4.6, platelets 264 x10^9/L, MCV 88 fL."},
    {"id": "ue", "name": "Urea and electrolytes", "group": "Blood tests", "minutes": 60, "delay": 25, "routine": True,
     "normal": "Na 139, K 4.2, urea 5.1 mmol/L, creatinine 78 micromol/L, eGFR >90."},
    {"id": "crp", "name": "C-reactive protein", "group": "Blood tests", "minutes": 60, "delay": 25, "routine": True,
     "normal": "CRP 3 mg/L"},
    {"id": "lft", "name": "Liver function tests", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "Bilirubin 11 micromol/L, ALT 24 IU/L, AST 22 IU/L, ALP 78 IU/L, GGT 30 IU/L, albumin 42 g/L."},
    {"id": "coag", "name": "Clotting screen (PT/INR, APTT)", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "PT 12 s, INR 1.0, APTT 30 s."},
    {"id": "bone", "name": "Bone profile", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "Adjusted calcium 2.35 mmol/L, phosphate 1.1 mmol/L."},
    {"id": "magnesium", "name": "Magnesium", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "Mg 0.85 mmol/L"},
    {"id": "troponin", "name": "High-sensitivity troponin", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "hs-troponin T 6 ng/L (below 99th percentile)."},
    {"id": "d_dimer", "name": "D-dimer", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "D-dimer 0.3 mg/L FEU (below age-adjusted cut-off)."},
    {"id": "lipase", "name": "Lipase / amylase", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "Lipase 32 U/L"},
    {"id": "tft", "name": "Thyroid function", "group": "Blood tests", "minutes": 240, "delay": 30,
     "normal": "TSH 1.8 mU/L, free T4 15 pmol/L."},
    {"id": "hba1c", "name": "HbA1c", "group": "Blood tests", "minutes": 240, "delay": 30,
     "normal": "HbA1c 36 mmol/mol"},
    {"id": "ck", "name": "Creatine kinase", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "CK 110 U/L"},
    {"id": "cortisol", "name": "Random cortisol", "group": "Blood tests", "minutes": 240, "delay": 30,
     "normal": "Cortisol 420 nmol/L"},
    {"id": "tox_levels", "name": "Paracetamol and salicylate levels", "group": "Blood tests", "minutes": 60, "delay": 25,
     "normal": "Paracetamol not detected. Salicylate not detected."},
    {"id": "blood_cultures", "name": "Blood cultures", "group": "Blood tests", "minutes": 2880, "delay": 35,
     "normal": "No growth at 48 hours."},
    {"id": "hepatitis_screen", "name": "Viral hepatitis screen", "group": "Blood tests", "minutes": 1440, "delay": 35,
     "normal": "HBsAg negative, anti-HCV negative, HAV IgM negative."},
    {"id": "group_save", "name": "Group and save / crossmatch", "group": "Blood tests", "minutes": 45, "delay": 20,
     "normal": "Group O RhD positive. Antibody screen negative."},
    {"id": "vbg", "name": "Venous blood gas (with lactate)", "group": "Blood gases", "minutes": 5, "delay": 4,
     "normal": "pH 7.39, pCO2 5.6 kPa, HCO3 25 mmol/L, lactate 1.1 mmol/L, glucose 5.9, K 4.1."},
    {"id": "abg", "name": "Arterial blood gas (co-oximetry)", "group": "Blood gases", "minutes": 5, "delay": 4,
     "normal": "On room air: pH 7.41, pO2 12.4 kPa, pCO2 5.3 kPa, HCO3 24 mmol/L, lactate 1.0 mmol/L, COHb 1.2%, MetHb 0.8%."},
    # --- imaging
    {"id": "cxr", "name": "Chest X-ray", "group": "Imaging", "minutes": 45, "delay": 30, "routine": True,
     "normal": "Clear lung fields. Normal cardiac silhouette. No effusion or pneumothorax."},
    {"id": "axr", "name": "Abdominal X-ray", "group": "Imaging", "minutes": 45, "delay": 30,
     "normal": "Normal bowel gas pattern. No dilated loops."},
    {"id": "us_abdomen", "name": "Ultrasound abdomen", "group": "Imaging", "minutes": 120, "delay": 40,
     "normal": "Liver normal size and echotexture. Gallbladder normal. No free fluid. Kidneys normal. Spleen normal size."},
    {"id": "ct_head", "name": "CT head (non-contrast)", "group": "Imaging", "minutes": 60, "delay": 40,
     "normal": "No intracranial haemorrhage, mass or acute infarct. Ventricles normal size."},
    {"id": "ctpa", "name": "CT pulmonary angiogram", "group": "Imaging", "minutes": 90, "delay": 45,
     "normal": "No pulmonary embolus. Lungs clear."},
    {"id": "ct_abdomen", "name": "CT abdomen and pelvis (contrast)", "group": "Imaging", "minutes": 90, "delay": 45,
     "normal": "No acute intra-abdominal pathology."},
    {"id": "us_pelvis", "name": "Ultrasound pelvis (transvaginal)", "group": "Imaging", "minutes": 90, "delay": 40,
     "normal": "Normal uterus and ovaries. No free fluid."},
    {"id": "us_doppler_leg", "name": "Leg vein Doppler ultrasound", "group": "Imaging", "minutes": 120, "delay": 40,
     "normal": "Compressible deep veins. No deep vein thrombosis."},
    {"id": "echo", "name": "Echocardiogram", "group": "Imaging", "minutes": 240, "delay": 45,
     "normal": "Normal biventricular size and function. No significant valve disease."},
    # --- procedures
    {"id": "ascitic_tap", "name": "Diagnostic ascitic tap", "group": "Procedures", "minutes": 90, "delay": 35,
     "normal": "Insufficient fluid to aspirate."},
    {"id": "lumbar_puncture", "name": "Lumbar puncture", "group": "Procedures", "minutes": 120, "delay": 40,
     "normal": "Opening pressure 15 cmH2O. Clear CSF. WCC 1, protein 0.3 g/L, glucose 3.4 mmol/L (paired serum 5.6). No xanthochromia."},
]

TREATMENTS = [
    {"id": "oxygen_high_flow", "name": "High-flow oxygen (15 L non-rebreather)", "group": "Airway and breathing"},
    {"id": "oxygen_titrated", "name": "Titrated oxygen to target saturations", "group": "Airway and breathing"},
    {"id": "nebulised_salbutamol", "name": "Nebulised salbutamol", "group": "Airway and breathing"},
    {"id": "iv_access_bloods", "name": "IV access (wide bore x2)", "group": "Circulation"},
    {"id": "iv_fluids", "name": "IV crystalloid bolus (0.9% sodium chloride)", "group": "Circulation"},
    {"id": "blood_transfusion", "name": "Blood transfusion", "group": "Circulation"},
    {"id": "iv_insulin_frii", "name": "Fixed-rate IV insulin infusion", "group": "Drugs"},
    {"id": "iv_potassium", "name": "IV potassium replacement", "group": "Drugs"},
    {"id": "iv_antibiotics", "name": "IV broad-spectrum antibiotics", "group": "Drugs"},
    {"id": "iv_thiamine", "name": "IV thiamine (Pabrinex)", "group": "Drugs"},
    {"id": "chlordiazepoxide", "name": "Chlordiazepoxide (withdrawal regimen)", "group": "Drugs"},
    {"id": "iv_hydrocortisone", "name": "IV hydrocortisone", "group": "Drugs"},
    {"id": "im_adrenaline", "name": "IM adrenaline 0.5 mg", "group": "Drugs"},
    {"id": "iv_acetylcysteine", "name": "IV acetylcysteine", "group": "Drugs"},
    {"id": "aspirin_loading", "name": "Aspirin 300 mg", "group": "Drugs"},
    {"id": "lmwh_treatment", "name": "Treatment-dose anticoagulation", "group": "Drugs"},
    {"id": "iv_opioid", "name": "IV opioid analgesia", "group": "Drugs"},
    {"id": "paracetamol", "name": "Paracetamol", "group": "Drugs"},
    {"id": "nsaid", "name": "NSAID analgesia (e.g. ibuprofen)", "group": "Drugs"},
    {"id": "antiemetic", "name": "Antiemetic", "group": "Drugs"},
    {"id": "iv_ppi", "name": "IV proton pump inhibitor", "group": "Drugs"},
    {"id": "terlipressin", "name": "Terlipressin", "group": "Drugs"},
    {"id": "spironolactone", "name": "Spironolactone", "group": "Drugs"},
    {"id": "benzodiazepine_sedation", "name": "Benzodiazepine for agitation", "group": "Drugs"},
    {"id": "nil_by_mouth", "name": "Nil by mouth", "group": "Nursing"},
    {"id": "cardiac_monitoring", "name": "Continuous cardiac monitoring", "group": "Nursing"},
    {"id": "urinary_catheter", "name": "Urinary catheter and fluid balance", "group": "Nursing"},
    {"id": "senior_review", "name": "Escalate to senior / critical care", "group": "Escalation"},
    {"id": "surgical_referral", "name": "Urgent surgical referral", "group": "Escalation"},
    {"id": "specialist_referral", "name": "Specialist referral", "group": "Escalation"},
]

EXAM_BY_ID = {e["id"]: e for e in EXAMS}
INVESTIGATION_BY_ID = {i["id"]: i for i in INVESTIGATIONS}
TREATMENT_BY_ID = {t["id"]: t for t in TREATMENTS}


def public_catalog() -> dict:
    """What the simulator UI shows. Contains nothing case-specific."""
    return {
        "exams": [{"id": e["id"], "name": e["name"]} for e in EXAMS],
        "investigations": [
            {"id": i["id"], "name": i["name"], "group": i["group"], "minutes": i["minutes"]}
            for i in INVESTIGATIONS
        ],
        "treatments": [{"id": t["id"], "name": t["name"], "group": t["group"]} for t in TREATMENTS],
    }


def exam_finding(case: dict, exam_id: str) -> str:
    found = (case.get("exam") or {}).get(exam_id)
    return found if found else EXAM_BY_ID[exam_id]["normal"]


def investigation_result(case: dict, test_id: str) -> dict:
    """{"text": ..., "abnormal": bool}"""
    found = (case.get("investigations") or {}).get(test_id)
    if found:
        if isinstance(found, str):
            return {"text": found, "abnormal": True}
        return {"text": found["result"], "abnormal": bool(found.get("abnormal", True))}
    return {"text": INVESTIGATION_BY_ID[test_id]["normal"], "abnormal": False}
