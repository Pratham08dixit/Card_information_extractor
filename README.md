# Visiting Card Information Extractor

A web-based application that allows users to upload a picture of their visiting card. The application extracts key information (name, address, contact number, and email ID) from the image using Tesseract OCR, stores the details in a SQLite database, renames and saves the image locally based on the extracted name, and sends a confirmation SMS via Twilio once the process is complete.

## Features

- **OCR Extraction:** Uses Tesseract OCR to extract information from the uploaded visiting card image.
- **Data Persistence:** Stores extracted information (name, address, contact number, and email ID) in a SQLite database.
- **Image Management:** Renames and saves the uploaded image locally using the extracted name.
- **SMS Notification:** Sends a confirmation SMS ("Your info saved successfully") to the contact number using Twilio.
- **Web Interface:** Simple HTML form interface for user uploads.



*Happy Coding!*
