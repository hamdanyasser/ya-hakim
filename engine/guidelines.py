"""The guideline registry.

A debrief may cite ONLY entries from this list, by id. The model is given the
registry and asked to pick ids; the engine then resolves them to titles and
URLs. A citation the model invents has no id here and is dropped. That is the
whole mechanism: the model cannot fabricate a source, because it never writes
a source -- it only points at one.

Entries are the current major public guidelines (NICE, RCEM, BSG, ESC, AHA,
ADA, JBDS, GINA, GOLD, BTS, Resuscitation Council UK, UK NPIS). URLs are the
publisher's landing pages, which are stable across revisions.
"""

from __future__ import annotations

REGISTRY = [
    # --- liver / alcohol
    {"id": "nice-cg100", "org": "NICE", "code": "CG100",
     "title": "Alcohol-use disorders: diagnosis and management of physical complications",
     "url": "https://www.nice.org.uk/guidance/cg100", "topics": ["alcohol", "liver", "withdrawal"]},
    {"id": "nice-cg115", "org": "NICE", "code": "CG115",
     "title": "Alcohol-use disorders: diagnosis, assessment and management of harmful drinking and alcohol dependence",
     "url": "https://www.nice.org.uk/guidance/cg115", "topics": ["alcohol", "dependence"]},
    {"id": "bsg-decompensated-cirrhosis", "org": "BSG / BASL", "code": "Decompensated cirrhosis care bundle",
     "title": "Decompensated cirrhosis care bundle: first 24 hours",
     "url": "https://www.bsg.org.uk/clinical-resource/bsg-basl-decompensated-cirrhosis-care-bundle-first-24-hours",
     "topics": ["liver", "cirrhosis", "ascites", "encephalopathy"]},
    {"id": "easl-decompensated-cirrhosis", "org": "EASL", "code": "2018",
     "title": "EASL Clinical Practice Guidelines for the management of patients with decompensated cirrhosis",
     "url": "https://easl.eu/publication/easl-clinical-practice-guidelines-for-the-management-of-patients-with-decompensated-cirrhosis/",
     "topics": ["liver", "cirrhosis"]},
    # --- diabetes
    {"id": "jbds-dka", "org": "JBDS-IP", "code": "DKA 2023",
     "title": "The management of diabetic ketoacidosis in adults",
     "url": "https://abcd.care/joint-british-diabetes-societies-jbds-inpatient-care-group",
     "topics": ["diabetes", "dka", "ketoacidosis"]},
    {"id": "nice-ng17", "org": "NICE", "code": "NG17",
     "title": "Type 1 diabetes in adults: diagnosis and management",
     "url": "https://www.nice.org.uk/guidance/ng17", "topics": ["diabetes", "type 1"]},
    {"id": "nice-ng28", "org": "NICE", "code": "NG28",
     "title": "Type 2 diabetes in adults: management",
     "url": "https://www.nice.org.uk/guidance/ng28", "topics": ["diabetes", "type 2"]},
    {"id": "ada-standards", "org": "ADA", "code": "Standards of Care",
     "title": "Standards of Care in Diabetes",
     "url": "https://diabetesjournals.org/care/issue/47/Supplement_1", "topics": ["diabetes"]},
    # --- carbon monoxide / toxicology
    {"id": "npis-toxbase-co", "org": "UK NPIS / TOXBASE", "code": "Carbon monoxide",
     "title": "TOXBASE: carbon monoxide poisoning",
     "url": "https://www.toxbase.org/", "topics": ["carbon monoxide", "poisoning", "toxicology"]},
    {"id": "ukhsa-co", "org": "UKHSA", "code": "CO guidance",
     "title": "Carbon monoxide: toxicological overview and clinical management",
     "url": "https://www.gov.uk/government/publications/carbon-monoxide-properties-incident-management-and-toxicology",
     "topics": ["carbon monoxide", "poisoning"]},
    {"id": "rcem-co", "org": "RCEM", "code": "Best practice",
     "title": "RCEM best practice guideline: carbon monoxide poisoning",
     "url": "https://rcem.ac.uk/clinical-guidelines/", "topics": ["carbon monoxide", "emergency"]},
    {"id": "nice-cg16-paracetamol", "org": "UK NPIS / MHRA", "code": "Paracetamol",
     "title": "Paracetamol overdose: treatment nomogram and acetylcysteine",
     "url": "https://www.gov.uk/drug-safety-update/treating-paracetamol-overdose-with-intravenous-acetylcysteine-new-guidance",
     "topics": ["paracetamol", "overdose", "toxicology"]},
    # --- cardiology
    {"id": "esc-acs-2023", "org": "ESC", "code": "2023",
     "title": "ESC Guidelines for the management of acute coronary syndromes",
     "url": "https://www.escardio.org/Guidelines/Clinical-Practice-Guidelines/Acute-Coronary-Syndromes-ACS-Guidelines",
     "topics": ["acs", "chest pain", "myocardial infarction"]},
    {"id": "nice-ng185", "org": "NICE", "code": "NG185",
     "title": "Acute coronary syndromes",
     "url": "https://www.nice.org.uk/guidance/ng185", "topics": ["acs", "chest pain"]},
    {"id": "aha-chest-pain-2021", "org": "AHA / ACC", "code": "2021",
     "title": "Guideline for the evaluation and diagnosis of chest pain",
     "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001029", "topics": ["chest pain"]},
    {"id": "esc-pe-2019", "org": "ESC", "code": "2019",
     "title": "ESC Guidelines for the diagnosis and management of acute pulmonary embolism",
     "url": "https://www.escardio.org/Guidelines/Clinical-Practice-Guidelines/Acute-Pulmonary-Embolism-Diagnosis-and-Management-of",
     "topics": ["pulmonary embolism", "vte"]},
    {"id": "nice-ng158", "org": "NICE", "code": "NG158",
     "title": "Venous thromboembolic diseases: diagnosis, management and thrombophilia testing",
     "url": "https://www.nice.org.uk/guidance/ng158", "topics": ["vte", "dvt", "pulmonary embolism"]},
    {"id": "esc-hf-2021", "org": "ESC", "code": "2021",
     "title": "ESC Guidelines for the diagnosis and treatment of acute and chronic heart failure",
     "url": "https://www.escardio.org/Guidelines/Clinical-Practice-Guidelines/Acute-and-Chronic-Heart-Failure",
     "topics": ["heart failure"]},
    # --- respiratory
    {"id": "gina-2024", "org": "GINA", "code": "2024",
     "title": "Global Strategy for Asthma Management and Prevention",
     "url": "https://ginasthma.org/reports/", "topics": ["asthma"]},
    {"id": "bts-asthma-2024", "org": "BTS / NICE / SIGN", "code": "NG245",
     "title": "Asthma: diagnosis, monitoring and chronic asthma management",
     "url": "https://www.nice.org.uk/guidance/ng245", "topics": ["asthma"]},
    {"id": "gold-2024", "org": "GOLD", "code": "2024",
     "title": "Global Strategy for the Diagnosis, Management, and Prevention of COPD",
     "url": "https://goldcopd.org/2024-gold-report/", "topics": ["copd"]},
    {"id": "bts-cap", "org": "BTS / NICE", "code": "NG138",
     "title": "Pneumonia (community-acquired): antimicrobial prescribing",
     "url": "https://www.nice.org.uk/guidance/ng138", "topics": ["pneumonia"]},
    {"id": "bts-oxygen-2017", "org": "BTS", "code": "2017",
     "title": "BTS Guideline for oxygen use in adults in healthcare and emergency settings",
     "url": "https://www.brit-thoracic.org.uk/quality-improvement/guidelines/emergency-oxygen/",
     "topics": ["oxygen"]},
    # --- sepsis / acute care
    {"id": "nice-ng51", "org": "NICE", "code": "NG51",
     "title": "Suspected sepsis: recognition, diagnosis and early management",
     "url": "https://www.nice.org.uk/guidance/ng51", "topics": ["sepsis"]},
    {"id": "ssc-2021", "org": "Surviving Sepsis Campaign", "code": "2021",
     "title": "International Guidelines for Management of Sepsis and Septic Shock",
     "url": "https://www.sccm.org/SurvivingSepsisCampaign/Guidelines/Adult-Patients", "topics": ["sepsis"]},
    {"id": "rcuk-als-2021", "org": "Resuscitation Council UK", "code": "2021",
     "title": "Adult advanced life support guidelines",
     "url": "https://www.resus.org.uk/library/2021-resuscitation-guidelines/adult-advanced-life-support-guidelines",
     "topics": ["arrest", "resuscitation", "abcde"]},
    {"id": "rcuk-abcde", "org": "Resuscitation Council UK", "code": "ABCDE",
     "title": "The ABCDE approach",
     "url": "https://www.resus.org.uk/library/abcde-approach", "topics": ["abcde", "assessment"]},
    {"id": "nice-ng148", "org": "NICE", "code": "NG148",
     "title": "Acute kidney injury: prevention, detection and management",
     "url": "https://www.nice.org.uk/guidance/ng148", "topics": ["aki", "kidney"]},
    {"id": "nice-cg174", "org": "NICE", "code": "CG174",
     "title": "Intravenous fluid therapy in adults in hospital",
     "url": "https://www.nice.org.uk/guidance/cg174", "topics": ["fluids"]},
    # --- GI / surgical
    {"id": "nice-cg141", "org": "NICE", "code": "CG141",
     "title": "Acute upper gastrointestinal bleeding in over 16s: management",
     "url": "https://www.nice.org.uk/guidance/cg141", "topics": ["gi bleed", "upper gi"]},
    {"id": "nice-ng104", "org": "NICE", "code": "NG104",
     "title": "Pancreatitis",
     "url": "https://www.nice.org.uk/guidance/ng104", "topics": ["pancreatitis"]},
    # --- neuro
    {"id": "nice-ng128", "org": "NICE", "code": "NG128",
     "title": "Stroke and transient ischaemic attack in over 16s: diagnosis and initial management",
     "url": "https://www.nice.org.uk/guidance/ng128", "topics": ["stroke", "tia"]},
    {"id": "nice-ng232", "org": "NICE", "code": "NG232",
     "title": "Head injury: assessment and early management",
     "url": "https://www.nice.org.uk/guidance/ng232", "topics": ["head injury"]},
    {"id": "nice-ng103", "org": "NICE", "code": "NG103",
     "title": "Flu, COVID-19 and other respiratory infections; and NG103 meningitis (bacterial) and meningococcal septicaemia",
     "url": "https://www.nice.org.uk/guidance/ng240", "topics": ["meningitis"]},
    # --- endocrine / other
    {"id": "endo-adrenal-crisis", "org": "Society for Endocrinology", "code": "Emergency guidance",
     "title": "Emergency management of acute adrenal insufficiency (adrenal crisis) in adults",
     "url": "https://www.endocrinology.org/adrenal-crisis/", "topics": ["adrenal", "addison"]},
    {"id": "rcem-anaphylaxis", "org": "Resuscitation Council UK", "code": "2021",
     "title": "Emergency treatment of anaphylaxis: guidelines for healthcare providers",
     "url": "https://www.resus.org.uk/library/additional-guidance/guidance-anaphylaxis", "topics": ["anaphylaxis"]},
    {"id": "nice-ng225", "org": "NICE", "code": "NG225",
     "title": "Self-harm: assessment, management and preventing recurrence",
     "url": "https://www.nice.org.uk/guidance/ng225", "topics": ["self-harm", "overdose", "mental health"]},
    # --- communication / consultation skills
    {"id": "gmc-gmp", "org": "GMC", "code": "Good medical practice 2024",
     "title": "Good medical practice",
     "url": "https://www.gmc-uk.org/professional-standards/good-medical-practice-2024",
     "topics": ["communication", "professionalism", "consent"]},
    {"id": "calgary-cambridge", "org": "Kurtz & Silverman", "code": "Calgary-Cambridge",
     "title": "The Calgary-Cambridge guide to the medical interview",
     "url": "https://www.skillscascade.com/", "topics": ["communication", "history taking"]},
    {"id": "gmc-decision-making", "org": "GMC", "code": "Decision making and consent",
     "title": "Decision making and consent",
     "url": "https://www.gmc-uk.org/professional-standards/professional-standards-for-doctors/decision-making-and-consent",
     "topics": ["consent", "communication"]},
]

BY_ID = {g["id"]: g for g in REGISTRY}


def resolve(ids) -> list:
    """Drop anything not in the registry -- that is the anti-fabrication rule."""
    out, seen = [], set()
    for gid in ids or []:
        if gid in BY_ID and gid not in seen:
            seen.add(gid)
            out.append({k: BY_ID[gid][k] for k in ("id", "org", "code", "title", "url")})
    return out


def registry_text(ids=None) -> str:
    """The registry as the model sees it: id, org, code, title. No URLs -- it
    only needs to choose, not to write."""
    rows = [BY_ID[i] for i in ids] if ids else REGISTRY
    return "\n".join("- %s | %s %s | %s" % (g["id"], g["org"], g["code"], g["title"]) for g in rows)


def for_case(case: dict) -> list:
    """The case's own list first, then anything topically related."""
    ids = [g for g in case.get("guidelines", []) if g in BY_ID]
    return ids
