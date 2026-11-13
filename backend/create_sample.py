from fpdf import FPDF

pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", size=12)

content = """
CogniFlow OS - Test Document

This is a sample PDF document created to test the backend API upload endpoint.
CogniFlow OS automatically extracts text from uploaded documents using pypdf and Tesseract OCR.
Once text is extracted, it sends the content to Google Gemini API to generate an automated summary.
"""

for line in content.strip().split("\n"):
    pdf.cell(200, 10, txt=line, ln=1)

pdf.output("sample_test.pdf")
print("Successfully created sample_test.pdf!")