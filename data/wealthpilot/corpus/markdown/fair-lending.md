# Fair Lending and Non-Discrimination Standard

**ASHVA CAPITAL INTERNAL CREDIT POLICY MANUAL**
**SECTION 4: FAIR LENDING AND NON-DISCRIMINATION STANDARD**
**DOCUMENT ID: ACP-POL-FL-049**
**EFFECTIVE DATE: OCTOBER 1, 2023**
**ISSUED BY: OFFICE OF THE CHIEF CREDIT OFFICER**

---

### 4.1 PURPOSE AND SCOPE
This standard binds all Ashva Capital underwriters, automated underwriting systems, scoring model developers, and collection personnel. Compliance with this section is mandatory. Any deviation constitutes a Tier-1 policy breach resulting in immediate suspension of underwriting authority and mandatory review by the Ashva Capital Fair Lending Committee.

### 4.2 PROHIBITED PROTECTED ATTRIBUTES
1. Underwriters and algorithmic decision engines are strictly prohibited from collecting, storing, reviewing, or considering the following protected attributes when evaluating credit applications, setting credit limits, pricing loans, or structuring repayment terms:
   * 4.2.1 Religion or religious affiliation.
   * 4.2.2 Caste, tribe, or ancestral community lineage.
   * 4.2.3 Gender, gender identity, or sexual orientation.
   * 4.2.4 Marital status or familial obligations.
   * 4.2.5 Age (except to verify that the applicant has attained the legal age of majority, fixed at 18 years, which shall be processed as a binary pass/fail condition and excluded from risk-scoring models).
   * 4.2.6 Physical, sensory, or cognitive disability.
   * 4.2.7 Region of origin, native place, or current domicile outside of verified financial risk parameters.

### 4.3 PROHIBITED PROXY VARIABLES
1. To prevent indirect discrimination, the use of variables that serve as functional proxies for the attributes listed in Section 4.2 is prohibited in all credit scoring models, decision trees, and manual underwriting assessments. Prohibited proxies include, without limitation:
   * 4.3.1 Postal code alone (or any sub-municipal geographic polygon with a population density below 50,000 residents, unless paired with verified individual income data).
   * 4.3.2 Applicant first name, given name, or patronymic naming conventions.
   * 4.3.3 Institution of education attended (secondary or tertiary).
   * 4.3.4 Language of application or primary language declared in communications.

### 4.4 DISPARATE-IMPACT TESTING REQUIREMENT AND CADENCE
1. The Ashva Capital Quantitative Risk Unit shall conduct disparate-impact testing on all active credit decisioning models and underwriting portfolios according to the following schedule:
   * 4.4.1 **Cadence:** Quarterly testing must be completed no later than the 15th calendar day following the close of each financial quarter (Q1: April 15, Q2: July 15, Q3: October 15, Q4: January 15).
   * 4.4.2 **Threshold:** A model shall be deemed in violation of this standard if the approval rate for any protected demographic sub-segment falls below 80.0% of the approval rate of the highest-approving demographic segment (the Four-Fifths Rule).
   * 4.4.3 **Remediation:** If a model breaches the 80.0% threshold, the Head of Quantitative Risk must submit a remediation plan to the Chief Credit Officer within 5 business days. The model must be recalibrated or decommissioned within 30 calendar days of the test report date.

### 4.5 VOID DECISION RATIONALE RULE
1. Any credit decision rationale, memo, automated log, or scoring output that explicitly or implicitly references a protected attribute (Section 4.2) or a prohibited proxy variable (Section 4.3) is legally and operationally **void ab initio**.
   * 4.5.1 Upon identification of a void rationale by the Quality Assurance Team or Compliance Auditor, the underwriting file must be flagged immediately in the Ashva Core Lending System (ACLS).
   * 4.5.2 The credit decision must be completely re-run by a secondary underwriter of senior grade or higher, utilizing a sanitized data packet stripped of all prohibited attributes and proxies.
   * 4.5.3 The original file must be archived for audit trailing, and a mandatory incident report must be filed with the Chief Compliance Officer within 24 hours.

### 4.6 ADVERSE-ACTION NOTICE REQUIREMENTS
1. When an application for credit is denied, counter-offered on less favorable terms, or terminated due to risk parameters, Ashva Capital must issue an Adverse-Action Notice (AAN) adhering to the following protocols:
   * 4.6.1 **Deadline:** The AAN must be dispatched via registered electronic mail and physical post within 7 business days of the final credit decision.
   * 4.6.2 **Content:** The notice must explicitly state the primary numerical reasons for the adverse action (e.g., debt-to-income ratio exceeding 45.0%, credit bureau score below the minimum threshold of 620, or verified monthly cash flow shortfall).
   * 4.6.3 **Prohibition:** Under no circumstances may an adverse-action notice cite, reference, or imply reliance upon any protected attribute or proxy variable listed in Sections 4.2 and 4.3.
   * 4.6.4 **Reconsideration Window:** The notice must inform the applicant of their right to submit a formal request for reconsideration within 14 calendar days of receipt, provided new verifiable financial documentation is supplied.

---
**END OF SECTION 4**
