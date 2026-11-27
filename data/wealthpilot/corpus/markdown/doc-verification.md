# Document Verification and Fraud Screening Procedure

**ASHVA CAPITAL INTERNAL CREDIT POLICY MANUAL**
**SECTION 4: DOCUMENT VERIFICATION AND FRAUD DETECTION PROCEDURES**
**Document ID: CP-SME-2024-04**
**Effective Date: October 1, 2024**
**Owner: Chief Credit Officer**

---

### 4.1 Mandatory Document Set for SME Applications

Every Small and Medium Enterprise (SME) credit application processed through the Ashva Capital digital origination platform must contain the complete, unedited digital document set prior to underwriting file assignment. Incomplete submissions shall be automatically rejected by the intake engine after 7 calendar days of pending status.

1. **KYC and Entity Verification:**
   * Certificate of Incorporation or valid Trade License.
   * Permanent Account Number (PAN) or national tax identifier for the entity and all ultimate beneficial owners holding $\ge 25\%$ equity.
   * Government-issued photo identification and residential address proof for all directors, partners, or proprietors.

2. **Financial Records:**
   * Audited financial statements (Balance Sheet, Profit and Loss Statement, Cash Flow Statement) for the last 2 completed financial years, certified by a registered Chartered Accountant or statutory auditor.
   * Unaudited provisional financial statements for the current financial year-to-date, closed within 45 calendar days of the application date.

3. **Tax and Statutory Filings:**
   * Goods and Services Tax (GST) returns (Form GSTR-3B and GSTR-1) for the preceding 12 consecutive months.
   * Annual corporate income tax returns for the last 2 assessment years.

4. **Banking Records:**
   * Electronic bank statements in native PDF or direct API-fetched format for the primary operational current accounts covering the last 12 consecutive months. Password-protected files must be accompanied by the verified password provided directly by the applicant via secure portal.

---

### 4.2 Document Verification Protocols

Underwriters and automated verification modules must execute the following validation checks for each document category.

#### 4.2.1 Bank Statements
1. **Metadata Inspection:** Underwriters must inspect file properties for creation dates, editing software footprints (e.g., Adobe Acrobat Pro, Microsoft Word), and layer anomalies. Any statement showing signs of digital manipulation, font inconsistencies, or alignment shifts shall be rejected immediately.
2. **Transaction Continuity:** Verify that the opening balance of month $N$ matches the closing balance of month $N-1$. Identify any gaps in sequence numbers or missing page numbers.
3. **Cash Flow Reconciliation:** Cross-reference incoming credit transactions against declared customer invoices and GST turnover to ensure business-operational provenance. Inter-account transfers and director infusions must be segregated from operational revenue.
4. **Direct Source Pull:** Whenever available via consent-based aggregators (e.g., ApexData API), bank statements must be pulled directly from the banking institution. Direct-pull statements override uploaded PDF documents for all credit decisioning.

#### 4.2.2 GST Returns (GSTR-3B vs. GSTR-1)
1. **Filing Status Check:** Verify filing timestamps on the national tax portal to ensure returns were filed on or before statutory due dates. Late filings exceeding 30 days in the review period require a written justification signed by the managing director.
2. **Cross-Return Reconciliation:** Compare total taxable outward supplies reported in GSTR-1 against taxable turnover declared in GSTR-3B for each corresponding tax period. Variance exceeding $2\%$ between GSTR-1 and GSTR-3B requires mandatory explanation and reconciliation by the applicant.
3. **Input Tax Credit (ITC) Ratio:** Calculate the ratio of ITC claimed to total purchases. An ITC claim ratio exceeding $90\%$ or falling below $10\%$ flags the file for further investigation regarding supplier authenticity.

#### 4.2.3 Audited Financials
1. **Auditor Verification:** Cross-check the membership number and firm registration number of the certifying auditor against the national registry of chartered accountants (e.g., Institute Board registry).
2. **Schedule Cross-Checking:** Ensure that figures reported in the Profit and Loss statement reconcile precisely with the respective schedules and notes to accounts.
3. **Ratio Benchmarking:** Calculate Debt-to-Equity, Current Ratio, and Debt Service Coverage Ratio (DSCR). Any audited DSCR below $1.25\times$ fails standard credit policy parameters and requires explicit sign-off from Credit Committee Member Marcus Vance.

---

### 4.3 Fraud Hold Triggers and Red Flags

A file shall be placed on an immediate **FRAUD_HOLD** and routed to the Special Investigation Unit (SIU) headed by Priya Sharma if any of the following 12 red flags are detected:

1. **Digital Footprint Anomalies:** Bank statements or tax returns bearing modification timestamps post-dating the transaction period, or metadata revealing author tags associated with known document-forgery software.
2. **Name Mismatches:** Discrepancies in entity legal name, registration number, or tax identifiers across GST filings, bank statements, and corporate registry records.
3. **Round-Tripping Indicators:** High-frequency, recurring transfers of identical sums between the applicant’s operating account and connected accounts of suppliers or sister concerns within a 48-hour window.
4. **Circular Transactions:** Identification of funds originating from the applicant company, passing through intermediary accounts, and returning as customer revenue or capital infusion.
5. **Freshly Created Accounts:** Primary operational bank accounts opened less than 90 calendar days prior to the loan application date.
6. **Address Red Flags:** Registered corporate address or operational premises matching known virtual office providers, residential properties in unrelated jurisdictions, or postal drop-boxes without physical verification sign-off.
7. **Round-Sum Depositing:** Consistent, uncharacteristic cash deposits in round figures just prior to month-end or application submission, lacking corresponding invoice backup.
8. **Tax-Turnover Disconnect:** GST turnover exceeding declared bank credit inflows by more than $30\%$, or vice versa, without a valid working capital or credit-term explanation.
9. **Auditor Disrepute:** Audited financials certified by an auditor who has been subject to disciplinary action or debarment by regulatory bodies.
10. **Multiple Application Footprints:** IP address or device fingerprinting revealing multiple credit applications submitted for different entities from the same physical location within a 72-hour window.
11. **Altered PDF Layers:** Text extraction failures or selectable text mismatching the visual raster image in uploaded bank or tax documents.
12. **Director History:** Any director or beneficial owner linked to an entity previously blacklisted by Ashva Capital or flagged in the national default database.

---

### 4.4 Revenue Variance Tolerance Thresholds

Underwriters must compare the annual revenue declared in the loan application form against the verified revenue derived by combining audited financials, 12-month bank statements, and GST returns. The following numeric tolerances and routing rules are strictly binding:

1. **Acceptance Threshold ($\le 10\% \text{ Variance}$):**
   * If the declared revenue is within **10 percent** of the verified revenue (either positive or negative variance), the figure is accepted. The underwriter proceeds with underwriting using the verified revenue figure. No special code is required.

2. **Human Review Threshold ($> 10\% \text{ and } \le 25\% \text{ Variance}$):**
   * If the difference between declared and verified revenue exceeds **10 percent** but is less than or equal to **25 percent**, the application shall carry reason code **DOC_MISMATCH**. 
   * The file is automatically suspended from automated processing and routed to a human credit reviewer for mandatory documentary interrogation and borrower clarification.

3. **Fraud Hold Threshold ($> 25\% \text{ Variance}$):**
   * If the difference between declared and verified revenue exceeds **25 percent**, the application carries reason code **FRAUD_HOLD**. 
   * This discrepancy triggers an immediate fraud hold, locking the application workflow, notifying the Chief Risk Officer, and transferring the file to the Special Investigation Unit (SIU) for forensic review.

$$\text{Revenue Variance (\%)} = \left| \frac{\text{Declared Revenue} - \text{Verified Revenue}}{\text{Verified Revenue}} \right| \times 100$$

| Variance Range | System Reason Code | Routing Action |
| :--- | :--- | :--- |
| $0\% - 10\%$ | None | Proceed with verified revenue |
| $>10\%$ to $\le 25\%$ | `DOC_MISMATCH` | Route to human credit reviewer |
| $>25\%$ | `FRAUD_HOLD` | Route to SIU / Fraud Operations |

---

### 4.5 Escalation Path and Exception Governance

1. **Level 1 Escalation (`DOC_MISMATCH`):**
   * Handled by Assigned Credit Analyst. The analyst must issue a Clarification Notice to the applicant via the secure portal within 24 hours of code assignment.
   * Applicant has 5 business days to provide reconciliation documents. Failure to respond results in application declination under code `DECL_DOC_TIMEOUT`.

2. **Level 2 Escalation (`FRAUD_HOLD`):**
   * Handled by SIU Investigator Priya Sharma. Investigation must be completed within 3 business days from the imposition of the hold.
   * If the SIU determines the variance is due to an innocent accounting classification error (e.g., inclusion of non-operating income), the investigator may lift the `FRAUD_HOLD` and replace it with `DOC_MISMATCH` only upon the written joint approval of Head of Credit Marcus Vance and Chief Risk Officer Elena Rostova.

3. **Policy Exception Sign-Off:**
   * Under no circumstances may an underwriter override a revenue variance exceeding $25\%$ without written sign-off from both the Chief Risk Officer and the Chief Credit Officer. All approved exceptions must be logged in the monthly Credit Policy Compliance Register for internal audit review.
