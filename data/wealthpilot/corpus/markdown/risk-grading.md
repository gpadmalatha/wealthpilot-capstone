# Internal Risk Grading and Pricing Grid

**ASHVA CAPITAL PRIVATE LIMITED**
**INTERNAL CREDIT POLICY MANUAL**
**SECTION 4: RISK GRADING AND PRICING METHODOLOGY**
**DOCUMENT ID: ACM-CP-2024-04**
**EFFECTIVE DATE: 1 JANUARY 2025**

---

### 4.1 RISK GRADING STRUCTURE AND ASSIGNMENT RULES

**4.1.1** The Ashva Capital automated underwriting engine and manual underwriting desk shall grade all credit applications using the eight-tier internal risk grading scale defined in this section, spanning from Grade A1 (lowest risk) to Grade D2 (highest risk).

**4.1.2** Grade Assignment Logic: An application shall be assigned the highest risk grade for which it simultaneously satisfies both the minimum Debt Service Coverage Ratio (DSCR) and the minimum bureau score criteria. If an application meets the criteria for multiple grades, it shall be assigned the superior grade.

**4.1.3** The quantitative thresholds, indicative interest rate spreads, lending rates (based on an Ashva Lending Base Rate of 9.50% per annum), maximum permissible tenors, and minimum collateral coverage requirements for each internal grade are strictly defined in Table 4.1 below.

#### Table 4.1: Risk Grading Matrix

| Grade | Min. DSCR | Min. Bureau Score | Spread Over Base (bps) | Indicative Interest Rate (% p.a.) | Max. Tenor (Months) | Min. Collateral Cover (%) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A1** | 2.00 | 750 | 150 | 11.00% | 84 | 0% |
| **A2** | 1.75 | 700 | 200 | 11.50% | 72 | 25% |
| **B1** | 1.50 | 650 | 275 | 12.25% | 60 | 50% |
| **B2** | 1.35 | 600 | 350 | 13.00% | 60 | 75% |
| **C1** | 1.25 | 550 | 450 | 14.00% | 48 | 100% |
| **C2** | 1.15 | 500 | 575 | 15.25% | 36 | 125% |
| **D1** | 1.00 | 450 | 725 | 16.75% | 24 | 150% |
| **D2** | N/A (Below D1) | N/A (Below D1) | 900 | 18.50% | 12 | 150% |

---

### 4.2 TENOR LIMITATIONS AND BREACH HANDLING

**4.2.1** The loan tenor offered to any borrower shall not exceed the maximum tenor prescribed for their assigned risk grade in Table 4.1, nor shall it exceed the maximum sector tenor specified in Section 8 of this manual, whichever limit is shorter.

**4.2.2** If a borrower requests a loan tenor exceeding either the grade maximum or the sector maximum:
1. The underwriting system shall flag the application with reason code **TENOR_ABOVE_LIMIT**.
2. Auto-approval is immediately revoked regardless of loan size or risk grade.
3. The application shall be routed to a human credit reviewer for manual exception assessment.

---

### 4.3 COLLATERAL VALUATION AND SHORTFALL PROTOCOLS

**4.3.1** Collateral cover is expressed as a mandatory percentage of the total approved loan amount. Valuations must be certified by an Ashva Capital-empanelled valuer in accordance with Section 11 (Collateral Management Policy).

**4.3.2** If the appraised and verified value of the collateral offered provides coverage below the minimum percentage required for the assigned grade in Table 4.1:
1. The underwriting system shall flag the application with reason code **COLLATERAL_SHORTFALL**.
2. The application shall be halted and routed to a human reviewer.
3. The human reviewer may either require the borrower to post additional eligible collateral to eliminate the shortfall or decline the facility. Under no circumstances shall an application with an active **COLLATERAL_SHORTFALL** flag proceed to disbursement.

---

### 4.4 AUTO-APPROVAL ELIGIBILITY AND RESTRICTIONS

**4.4.1** Applications assigned to risk grades **A1, A2, B1, B2, and C1** are eligible for automated underwriting and auto-approval, provided the requested loan amount does not exceed **1,000,000 INR** (One Million Indian Rupees) and all policy checks pass without exception flags.

**4.4.2** Applications assigned to risk grades **C2, D1, and D2** are strictly prohibited from receiving auto-approval, regardless of the loan size, requested tenor, or collateral coverage. Every application falling under grades C2, D1, or D2 must undergo mandatory manual review and sign-off by a designated Credit Officer holding appropriate lending authority as defined in Section 2 of this manual.

---
*End of Section 4*
