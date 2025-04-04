import os
import re
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import pytesseract
from PIL import Image
import spacy
from werkzeug.utils import secure_filename
from twilio.rest import Client

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///visiting_cards.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Create upload folder if not exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Define database model
class VisitingCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    email_id = db.Column(db.String(150), nullable=True)
    address = db.Column(db.Text, nullable=True)
    phone_number = db.Column(db.String(50), nullable=True)

    def __repr__(self):
        return f'<VisitingCard {self.name}>'

with app.app_context():
    db.create_all()

# Initialize spaCy model (English)
nlp = spacy.load("en_core_web_sm")

# Regular expression patterns
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'\+?\d{1,4}[-.\s]?\(?\d{1,3}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}')
NAME_REGEX = re.compile(r'^[A-Za-z\s\.\-]+$')

def fix_common_email_misreads(email_candidate):
    """
    Fix common OCR misreads in the candidate email string.
    E.g., replace "gmaik" with "gmail" and "hotmaik" with "hotmail".
    """
    corrections = {
        r'gmaik': 'gmail',
        r'hotmaik': 'hotmail',
        # Add more corrections if needed.
    }
    for wrong, correct in corrections.items():
        email_candidate = re.sub(wrong, correct, email_candidate, flags=re.IGNORECASE)
    return email_candidate

def fix_email_candidate(email_candidate):
    """
    Apply corrections to the candidate email.
    Then, if the domain part is missing a dot, fix it accordingly.
    """
    email_candidate = fix_common_email_misreads(email_candidate)
    if "@" in email_candidate:
        local, domain = email_candidate.split("@", 1)
        if "." not in domain:
            domain_lower = domain.lower()
            if "gmail" in domain_lower:
                domain = "gmail.com"
            elif "hotmail" in domain_lower:
                domain = "hotmail.com"
            elif "yahoo" in domain_lower:
                domain = "yahoo.com"
            else:
                domain = domain + ".com"
        return local + "@" + domain
    return email_candidate

def is_email_candidate(text):
    """
    Returns True if the text contains an '@' symbol or one of the keywords:
    "gmail", "hotmail", ".in", or ".com".
    """
    text_lower = text.lower()
    if "@" in text_lower:
        return True
    if re.search(r'(gmail|hotmail|\.(in|com))', text_lower):
        return True
    return False

def extract_name(candidate_lines):
    """
    Use spaCy's NER to extract a person's name from candidate lines.
    Falls back to regex matching if NER doesn't yield a result.
    """
    for line in candidate_lines:
        doc = nlp(line)
        if any(ent.label_ == "PERSON" for ent in doc.ents):
            return line.strip()
    for line in candidate_lines:
        if NAME_REGEX.match(line.strip()):
            return line.strip()
    return candidate_lines[0].strip() if candidate_lines else "Unknown"

def is_address_line(line):
    """
    Determine if a given line is likely part of an address.
    It should not contain '@' and should include either '/' or '-' along with letters and digits.
    """
    line = line.strip()
    if "@" in line:
        return False
    if ("/" in line or "-" in line) and re.search(r'[A-Za-z]', line) and re.search(r'\d', line):
        return True
    return False

def perform_ocr_tesseract(image_path):
    """
    Perform OCR using Tesseract.
    Returns a list of results in the format: [bbox, text, confidence]
    """
    image = Image.open(image_path)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    results = []
    n_boxes = len(data['level'])
    for i in range(n_boxes):
        text = data['text'][i].strip()
        if text:
            try:
                conf = float(data['conf'][i])
            except:
                conf = 0
            x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
            bbox = [[x, y], [x+w, y], [x+w, y+h], [x, y+h]]
            results.append([bbox, text, conf])
    return results

def extract_details(ocr_results):
    """
    Process the OCR results to extract name, email, phone, and address.
    If an email is found, assume the address consists of all lines below the email line.
    """
    lines = []
    for result in ocr_results:
        bbox = result[0]
        # Ensure the OCR text is extracted as a string:
        raw_text = result[1]
        if isinstance(raw_text, (list, tuple)):
            text = " ".join(str(elem) for elem in raw_text)
        else:
            text = str(raw_text)
        text = text.strip()
        try:
            y = min(point[1] for point in bbox)
        except Exception:
            y = 0
        lines.append((text, y))
    
    # Sort lines top-to-bottom by y-coordinate.
    lines.sort(key=lambda x: x[1])
    extracted_text = [text for text, _ in lines]
    print("Extracted OCR text lines:", extracted_text)
    
    # Extract Name from the top 3 lines.
    candidate_name_lines = extracted_text[:3] if len(extracted_text) >= 3 else extracted_text
    name = extract_name(candidate_name_lines)
    
    # --- Email Extraction ---
    email = None
    for line in extracted_text:
        for word in line.split():
            if is_email_candidate(word):
                email_match = EMAIL_REGEX.search(word)
                if email_match:
                    candidate = email_match.group(0)
                    email = fix_email_candidate(candidate)
                    break
        if email:
            break
    if not email:
        combined_text = " ".join(extracted_text)
        for word in combined_text.split():
            if is_email_candidate(word):
                email_match = EMAIL_REGEX.search(word)
                if email_match:
                    candidate = email_match.group(0)
                    email = fix_email_candidate(candidate)
                    break
    
    # --- Phone Extraction ---
    phone = None
    for line in extracted_text:
        if any(label in line.lower() for label in ["tel", "phone", "mob"]):
            phone_match = PHONE_REGEX.search(line)
            if phone_match:
                phone = phone_match.group(0)
                break
    if not phone:
        for line in extracted_text:
            phone_match = PHONE_REGEX.search(line)
            if phone_match:
                phone = phone_match.group(0)
                break

    # --- Address Extraction ---
    # If email is found, take all lines below the email line.
    address = None
    if email:
        email_y = None
        for text, y in lines:
            if email in text:
                email_y = y
                break
        if email_y is not None:
            address_lines = [text for text, y in lines if y > email_y]
            address = ", ".join(address_lines).strip()
    # Fallback: if address is empty, join remaining lines (excluding those with name, email, or phone)
    if not address or address == "":
        remaining_lines = [text for text, _ in lines if text.strip() != name and (not email or email not in text) and (not phone or phone not in text)]
        if remaining_lines:
            address = ", ".join(remaining_lines).strip()
        else:
            address = "Not Provided"
    
    return name, email, phone, address

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Perform OCR using Tesseract
            ocr_results = perform_ocr_tesseract(file_path)
            name, email, phone, address = extract_details(ocr_results)
            
            new_card = VisitingCard(name=name, email_id=email, phone_number=phone, address=address)
            db.session.add(new_card)
            db.session.commit()
            
            # Send SMS via Twilio if phone is extracted
            if phone:
                account_sid = "Enter your sid from twilio account"
                auth_token = "Enter yourn token"
                twilio_number = "Enter your number"
                client = Client(account_sid, auth_token)
                try:
                    message = client.messages.create(
                        from_=twilio_number,
                        body="Your visiting card has been processed successfully!",
                        to=phone
                    )
                    print(f"Twilio message SID: {message.sid}")
                except Exception as e:
                    print("Twilio error:", e)
            else:
                print("No phone number available for notification")
            
            safe_name = secure_filename(name.replace(" ", "_"))
            ext = os.path.splitext(filename)[1]
            new_filename = safe_name + ext
            new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            os.rename(file_path, new_file_path)
            
            flash("Visiting card processed and saved successfully!")
            return redirect(url_for('index'))
    
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
