RENTEASE ADVANCED - RUNNABLE STUDENT PROTOTYPE

FEATURES
- Registration with town/area (use test details only)
- GPS location permission OR manual town/area search
- Nearby dashboard with 5 km default radius and adjustable radius
- Nearby listing counts, categories, recommendations
- Search, category and hourly-price filters
- Map pins for listings with saved coordinates
- Add items with photos, category, hourly price and pickup area
- Booking requests, owner approval/decline
- Demo online-payment selection OR direct-to-owner payment record
- Rental countdown and extension requests/owner approval
- Owner dashboard with listing and booking metrics
- Saved items, ratings and reviews after return

INSTALLATION
1. Install Python 3.10 or newer.
2. Extract this ZIP.
3. Open a terminal in the extracted folder.
4. Run:
     pip install -r requirements.txt
5. Run:
     streamlit run app.py
6. Open the local URL shown in the terminal (normally http://localhost:8501).

LOCATION NOTES
- GPS requires internet, browser location permission and a supported browser.
- Manual location uses OpenStreetMap's Nominatim geocoding service (internet required).
- Approximate listing coordinates are used for distance filtering. Do not publish exact home addresses.
- If a listing has no coordinates, it can appear in search with distance unavailable.

PAYMENT AND SECURITY NOTES
- "Online payment (demo only)" does not charge money. It is not connected to a payment provider.
- Never collect card details, UPI PINs, passwords or OTPs in this prototype.
- Real payments require a legitimate provider account, server-side payment verification,
  webhooks, HTTPS, refund/cancellation handling and secure deployment.
- This prototype stores phone numbers and other demo data in a local SQLite file without
  production-grade encryption/authentication. Use fictional test data only.
- For public deployment, add secure login, authorization, privacy controls, validation,
  moderation, backup, rate limits and proper handling of disputes.
- This is a student demo, not a production-ready marketplace.

DATA
- Database: rentease.db (created automatically)
- Uploaded photos: uploads/
- Keep both if you want to preserve your local test project data.
