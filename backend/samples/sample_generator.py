import os
from pathlib import Path
from backend.config import SAMPLES_DIR

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:
    letter = None


PREDATORY_RENTAL_LEASE = """RESIDENTIAL LEASE AGREEMENT

SECTION 1. PARTIES AND PREMISES
This Lease Agreement is entered into between Apex Property Holdings ("Landlord") and Tenant. Landlord leases to Tenant the residential premises located at 742 Evergreen Terrace, Unit 4B.

SECTION 2. TERM AND AUTOMATIC RENEWAL
The initial term shall be 12 months. This lease shall automatically renew for successive 12-month periods at an automatic 15% rent increase unless Tenant delivers certified written notice to vacate at least ninety (90) days prior to lease expiration.

SECTION 3. RENT AND LATE PAYMENT PENALTIES
Monthly rent is $2,200.00, due promptly on the 1st day of each month. If rent is not received by 5:00 PM on the 1st, a late fee of $75 per day shall accumulate until all overdue balances are paid in full. There is no grace period.

SECTION 4. NON-REFUNDABLE SECURITY DEPOSIT
Tenant shall deposit $3,500.00 as a non-refundable security deposit. Tenant agrees that the entire deposit shall be forfeited in full if Tenant vacates before the 12-month term or upon any minor breach of building guidelines, regardless of whether Landlord re-rents the unit.

SECTION 5. UNRESTRICTED LANDLORD ACCESS AND ENTRY
Landlord and Landlord's maintenance agents reserve the absolute right to enter the premises at any time 24/7 without prior notice for routine inspections, prospective buyer showings, or property evaluation. Tenant waives any right to prior written notice.

SECTION 6. STRUCTURAL MAINTENANCE AND HABITABILITY WAIVER
Tenant explicitly waives any and all implied warranties of habitability. Tenant agrees to bear full financial cost for replacing or repairing the roof, furnace, and HVAC system during the tenancy. Landlord shall have no obligation to perform repairs.

SECTION 7. SUBLETTING BAN
Subletting is strictly prohibited under any circumstances. Any attempt to sublet or host an unauthorized guest for more than 48 hours shall result in immediate eviction and a $1,500 penalty fee.

SECTION 8. UNILATERAL INDEMNIFICATION
Tenant agrees to defend, indemnify, and hold harmless Landlord against any and all claims, bodily injuries, or damages occurring on the property, even if caused by Landlord's own gross negligence or willful misconduct. Tenant waives any right to a jury trial.
"""

STANDARD_FAIR_LEASE = """STANDARD RESIDENTIAL LEASE AGREEMENT

SECTION 1. PARTIES AND PREMISES
This Lease Agreement is made between Oakridge Realty LLC ("Landlord") and Tenant for the premises located at 120 Elm Street, Apt 2A.

SECTION 2. LEASE TERM AND EXPIRATION NOTICE
The term of this Lease shall be for one (1) year. Either party may terminate this agreement at the conclusion of the initial term by providing thirty (30) days advance written notice.

SECTION 3. RENT AND GRACE PERIOD
Monthly rent is $1,800.00 due on the first day of each calendar month. If rent is received after the fifth (5th) day of the calendar month (the Grace Period), Tenant shall pay a flat late fee of $40. No additional daily penalties shall accrue.

SECTION 4. REFUNDABLE SECURITY DEPOSIT
Tenant shall deposit $1,800.00 (equivalent to one month's rent) as security. Landlord shall return the security deposit within twenty-one (21) days of surrender of the premises, together with an itemized accounting of any deductions for damages exceeding normal wear and tear.

SECTION 5. LANDLORD RIGHT OF ENTRY
Landlord shall provide at least twenty-four (24) hours advance written notice prior to entering the premises for inspections or non-emergency repairs during regular business hours (9:00 AM to 5:00 PM). Emergency entry is permitted in cases of fire or major plumbing leak.

SECTION 6. MAINTENANCE AND HABITABILITY
Landlord agrees to maintain the roof, foundation, exterior walls, and plumbing, heating, and electrical systems in safe operating condition in compliance with local housing codes. Tenant is responsible for replacing standard light bulbs and keeping the unit clean.

SECTION 7. SUBLETTING WITH REASONABLE CONSENT
Tenant may sublet the premises with the prior written consent of Landlord, which consent shall not be unreasonably withheld or delayed for qualified applicants meeting standard credit guidelines.

SECTION 8. MUTUAL INDEMNIFICATION AND GOVERNING LAW
Each party shall indemnify and hold harmless the other party from claims and liabilities arising directly from the indemnifying party's negligent acts. This agreement is governed by the laws of the State.
"""

PREDATORY_LOAN_AGREEMENT = """PROMISSORY NOTE AND LOAN DISCLOSURE

SECTION 1. PRINCIPAL AND EXTREME INTEREST RATE
Borrower promises to pay to the order of QuickCash Capital ("Lender") the principal sum of $10,000.00. The loan shall bear interest at an annual percentage rate (APR) of 48% compounded monthly. Any late installment shall trigger a default APR of 65%.

SECTION 2. PREPAYMENT PENALTY
In the event Borrower pays off this promissory note prior to maturity, Borrower shall pay a prepayment penalty equal to all remaining unearned interest through the full 5-year term.

SECTION 3. CONFESSION OF JUDGMENT
Borrower irrevocably authorizes any attorney of any court of record to appear for Borrower and confess judgment against Borrower for the full balance plus a 25% collection fee without notice or hearing.

SECTION 4. IMMEDIATE ACCELERATION
Failure to pay on the due date triggers immediate acceleration of all principal and unearned interest without notice or opportunity to cure.
"""


def generate_pdf(filename: str, text: str):
    """Creates a clean PDF version of a text contract."""
    if letter is None:
        return
    
    pdf_path = SAMPLES_DIR / filename
    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, rightMargin=54, leftMargin=54, topMargin=54, bottomMargin=54)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=16,
        leading=20,
        spaceAfter=12
    )
    
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading3'],
        fontSize=11,
        leading=14,
        spaceBefore=10,
        spaceAfter=4,
        textColor='#1e293b'
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=13.5,
        spaceAfter=6,
        textColor='#334155'
    )
    
    story = []
    lines = text.strip().split("\n")
    
    # Title
    story.append(Paragraph(lines[0], title_style))
    story.append(Spacer(1, 8))
    
    current_section = ""
    current_body = []
    
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith("SECTION ") or line.startswith("ARTICLE "):
            if current_section or current_body:
                if current_section:
                    story.append(Paragraph(current_section, section_style))
                if current_body:
                    story.append(Paragraph(" ".join(current_body), body_style))
                current_body = []
            current_section = line
        else:
            current_body.append(line)
            
    if current_section:
        story.append(Paragraph(current_section, section_style))
    if current_body:
        story.append(Paragraph(" ".join(current_body), body_style))
        
    doc.build(story)


def generate_all_samples():
    """Generates sample TXT and PDF documents in the samples directory."""
    os.makedirs(SAMPLES_DIR, exist_ok=True)
    
    # Text files
    with open(SAMPLES_DIR / "predatory_rental_lease.txt", "w", encoding="utf-8") as f:
        f.write(PREDATORY_RENTAL_LEASE)
        
    with open(SAMPLES_DIR / "standard_fair_lease.txt", "w", encoding="utf-8") as f:
        f.write(STANDARD_FAIR_LEASE)
        
    with open(SAMPLES_DIR / "predatory_loan_agreement.txt", "w", encoding="utf-8") as f:
        f.write(PREDATORY_LOAN_AGREEMENT)
        
    # PDF files
    try:
        generate_pdf("predatory_rental_lease.pdf", PREDATORY_RENTAL_LEASE)
        generate_pdf("standard_fair_lease.pdf", STANDARD_FAIR_LEASE)
        generate_pdf("predatory_loan_agreement.pdf", PREDATORY_LOAN_AGREEMENT)
    except Exception as e:
        print(f"PDF generation note: {e}")


if __name__ == "__main__":
    generate_all_samples()
    print("Sample contracts generated successfully.")
