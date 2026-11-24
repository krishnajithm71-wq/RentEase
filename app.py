import streamlit as st
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2
from PIL import Image
import uuid
import json
import time

# Optional components. The app still runs without map/GPS extras.
try:
    from streamlit_geolocation import streamlit_geolocation
except Exception:
    streamlit_geolocation = None

try:
    import folium
    from streamlit_folium import st_folium
except Exception:
    folium = None
    st_folium = None

try:
    from geopy.geocoders import Nominatim
except Exception:
    Nominatim = None

APP_DIR = Path(__file__).parent
UPLOAD_DIR = APP_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = APP_DIR / "rentease.db"

st.set_page_config(page_title="RentEase | Local Rental Marketplace", page_icon="🏡", layout="wide")

# ----------------- DATABASE -----------------
def connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

def setup_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL UNIQUE,
            address TEXT NOT NULL DEFAULT '',
            area TEXT DEFAULT '',
            latitude REAL,
            longitude REAL,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_phone TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'Other',
            price_per_hour REAL NOT NULL,
            image_path TEXT,
            area TEXT DEFAULT '',
            latitude REAL,
            longitude REAL,
            available INTEGER DEFAULT 1,
            created_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            renter_phone TEXT NOT NULL,
            hours INTEGER NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT,
            end_at TEXT,
            payment_method TEXT,
            payment_status TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS extensions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            requested_hours INTEGER NOT NULL,
            extra_cost REAL NOT NULL,
            status TEXT NOT NULL,
            requested_at TEXT,
            decided_at TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            reviewer_phone TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(item_id, reviewer_phone)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS favorites(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            user_phone TEXT NOT NULL,
            UNIQUE(item_id, user_phone)
        )""")
        # Upgrade older RentEase databases safely.
        upgrades = {
            "users": [("area", "TEXT"), ("latitude", "REAL"), ("longitude", "REAL"), ("created_at", "TEXT")],
            "items": [("area", "TEXT"), ("latitude", "REAL"), ("longitude", "REAL")],
            "bookings": [("end_at", "TEXT"), ("payment_method", "TEXT"), ("payment_status", "TEXT")]
        }
        for table, fields in upgrades.items():
            existing = columns(c, table)
            for name, definition in fields:
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        c.commit()

setup_db()

# ----------------- HELPERS -----------------
def get_user(phone):
    with connect() as c:
        return c.execute("SELECT name,phone,address,area,latitude,longitude FROM users WHERE phone=?", (phone,)).fetchone()

def save_photo(file):
    im = Image.open(file).convert("RGB")
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}.jpg"
    im.save(path, "JPEG", quality=88)
    return str(path)

def parse_dt(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None

def haversine(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371.0
    dlat, dlon = radians(lat2-lat1), radians(lon2-lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return 2*r*atan2(sqrt(a), sqrt(1-a))

def geocode_place(place):
    if not place.strip() or Nominatim is None:
        return None, None
    try:
        loc = Nominatim(user_agent="rentease_student_demo").geocode(place, timeout=8)
        if loc:
            return float(loc.latitude), float(loc.longitude)
    except Exception:
        pass
    return None, None

def rupees(value):
    return f"₹{float(value):,.2f}"

def average_rating(item_id):
    with connect() as c:
        row = c.execute("SELECT AVG(rating),COUNT(*) FROM reviews WHERE item_id=?", (item_id,)).fetchone()
    return (round(row[0], 1) if row[0] is not None else None, row[1])

def nearby_items(lat, lon, radius_km, search="", category="All", max_price=None):
    with connect() as c:
        rows = c.execute("""SELECT i.id,i.owner_phone,i.name,i.description,i.category,
            i.price_per_hour,i.image_path,i.area,i.latitude,i.longitude,i.available,
            u.name,u.area
            FROM items i LEFT JOIN users u ON i.owner_phone=u.phone
            WHERE i.available=1 AND i.owner_phone<>? ORDER BY i.created_at DESC""",
            (st.session_state.phone,)).fetchall()
    results = []
    for row in rows:
        (iid, owner, name, desc, cat, price, img, area, ilat, ilon, available, owner_name, owner_area) = row
        haystack = f"{name} {desc or ''} {cat or ''}".lower()
        if search and search.lower() not in haystack:
            continue
        if category != "All" and cat != category:
            continue
        if max_price is not None and price > max_price:
            continue
        distance = haversine(lat, lon, ilat, ilon) if lat is not None and lon is not None else None
        # If location coordinates exist, enforce radius. If not, keep result and label distance unknown.
        if distance is not None and distance > radius_km:
            continue
        results.append({
            "id": iid, "owner": owner, "name": name, "description": desc or "",
            "category": cat or "Other", "price": price, "image": img,
            "area": area or owner_area or "Area not provided", "lat": ilat, "lon": ilon,
            "owner_name": owner_name or "Community member", "distance": distance
        })
    results.sort(key=lambda x: (x["distance"] is None, x["distance"] if x["distance"] is not None else 9999))
    return results

def product_recommendations(items):
    # Lightweight, explainable recommendation: prioritize well-rated, reasonably priced, nearby items.
    # This avoids pretending a small demo dataset is a trained production ML model.
    scored = []
    for item in items:
        rating, count = average_rating(item["id"])
        distance_score = 0 if item["distance"] is None else max(0, 5-item["distance"])
        rating_score = (rating or 3.5) * min(count, 5) / 5
        price_score = 1 / max(item["price"], 1)
        score = distance_score + rating_score + price_score * 20
        scored.append((score, item))
    return [x[1] for x in sorted(scored, key=lambda x: x[0], reverse=True)]

def get_geo():
    if streamlit_geolocation is None:
        st.info("GPS helper is not installed. Use manual location below, or install the requirements.")
        return None
    try:
        return streamlit_geolocation()
    except Exception:
        st.warning("Browser location was unavailable. You can enter a location manually.")
        return None

# ----------------- SESSION -----------------
for key, default in {
    "phone": None, "page": "dashboard", "gps": None,
    "location_lat": None, "location_lon": None,
    "location_label": "", "radius": 5
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ----------------- SIDEBAR -----------------
st.sidebar.title("🏡 RentEase")
st.sidebar.caption("Rent locally. Share more. Waste less.")
if st.session_state.phone:
    me = get_user(st.session_state.phone)
    if me:
        st.sidebar.write(f"Hi, **{me[0]}**")
    pages = [
        ("Overview", "dashboard"), ("Explore nearby", "explore"),
        ("Give for rent", "give"), ("My rentals", "rentals"),
        ("Owner dashboard", "owner"), ("Messages & requests", "requests"),
        ("Saved items", "saved")
    ]
    for label, page in pages:
        if st.sidebar.button(label, use_container_width=True, type="primary" if st.session_state.page == page else "secondary"):
            st.session_state.page = page
            st.rerun()
    st.sidebar.divider()
    if st.sidebar.button("Log out", use_container_width=True):
        st.session_state.phone = None
        st.session_state.page = "dashboard"
        st.rerun()

# ----------------- REGISTER -----------------
if not st.session_state.phone:
    st.title("🏡 RentEase")
    st.subheader("Your neighbourhood's rental marketplace")
    st.write("Borrow useful things nearby. Earn from items you are not using.")
    st.info("For this student prototype, use test contact details. Do not enter sensitive personal information.")
    with st.form("signup"):
        full_name = st.text_input("Name")
        phone = st.text_input("Phone number")
        address = st.text_input("Address or neighbourhood (avoid exact house details)")
        area = st.text_input("Town / area", placeholder="Example: Kanhangad")
        signup = st.form_submit_button("Create account")
    if signup:
        p = phone.strip().replace(" ", "")
        if not full_name.strip() or not p or not area.strip():
            st.error("Please enter your name, phone and town/area.")
        elif not p.replace("+", "").isdigit() or len(p) < 7:
            st.error("Enter a valid-looking phone number.")
        else:
            lat, lon = geocode_place(area)
            try:
                with connect() as c:
                    c.execute("""INSERT INTO users(name,phone,address,area,latitude,longitude,created_at)
                        VALUES(?,?,?,?,?,?,?)""",
                        (full_name.strip(), p, address.strip(), area.strip(), lat, lon, datetime.now().isoformat()))
                    c.commit()
                st.session_state.phone = p
                st.session_state.location_lat, st.session_state.location_lon = lat, lon
                st.session_state.location_label = area.strip()
                st.rerun()
            except sqlite3.IntegrityError:
                existing = get_user(p)
                if existing:
                    st.session_state.phone = p
                    st.rerun()
                else:
                    st.error("Could not create this account.")
    st.stop()

me = get_user(st.session_state.phone)
if not me:
    st.session_state.phone = None
    st.rerun()

# Use saved profile location as initial default.
if st.session_state.location_lat is None and me[4] is not None:
    st.session_state.location_lat, st.session_state.location_lon = me[4], me[5]
if not st.session_state.location_label:
    st.session_state.location_label = me[3] or ""

# ----------------- SHARED LOCATION PANEL -----------------
def location_panel():
    st.subheader("📍 Set your search location")
    tab_gps, tab_manual = st.tabs(["Use GPS", "Enter location manually"])
    with tab_gps:
        st.caption("Your browser may ask permission to share your approximate location.")
        if streamlit_geolocation is not None:
            gps_data = get_geo()
            if isinstance(gps_data, dict) and gps_data.get("latitude") is not None and gps_data.get("longitude") is not None:
                st.session_state.location_lat = float(gps_data["latitude"])
                st.session_state.location_lon = float(gps_data["longitude"])
                st.session_state.location_label = "Current GPS location"
                st.success("GPS location received for this session.")
            elif st.button("Try GPS again"):
                st.rerun()
        else:
            st.info("Install streamlit-geolocation using requirements.txt to enable browser GPS.")
    with tab_manual:
        place = st.text_input("Town, area or PIN code", value=st.session_state.location_label, key="manual_place")
        if st.button("Use this location"):
            lat, lon = geocode_place(place)
            if lat is not None:
                st.session_state.location_lat, st.session_state.location_lon = lat, lon
                st.session_state.location_label = place
                st.success("Location found.")
            else:
                st.warning("Could not find coordinates. Check the spelling or use a more specific town/area.")
    if st.session_state.location_lat is not None:
        st.caption(f"Search centred near: {st.session_state.location_label or 'Selected location'}")
    else:
        st.warning("Choose GPS or enter a location to calculate nearby distances. Listings without coordinates may still appear with unknown distance.")

# ----------------- DASHBOARD -----------------
if st.session_state.page == "dashboard":
    st.title(f"Good day, {me[0]} 👋")
    st.markdown("### Find what you need, right around you.")
    location_panel()
    st.session_state.radius = st.select_slider("Nearby search radius", options=[1, 5, 10, 20, 50], value=st.session_state.radius, format_func=lambda x: f"{x} km")
    all_items = nearby_items(st.session_state.location_lat, st.session_state.location_lon, st.session_state.radius)
    known = [x for x in all_items if x["distance"] is not None]
    categories = len(set(x["category"] for x in all_items))
    k1, k2, k3 = st.columns(3)
    k1.metric("Nearby listings", len(all_items))
    k2.metric("Categories", categories)
    k3.metric("Within selected radius", len(known))
    st.divider()
    st.subheader("✨ Recommended for you")
    picks = product_recommendations(all_items)[:4]
    if not picks:
        st.info("No listings yet. Be the first to list an item, or change your location/radius.")
    cards = st.columns(4)
    for col, item in zip(cards, picks):
        with col:
            if item["image"] and Path(item["image"]).exists():
                st.image(item["image"], use_container_width=True)
            st.markdown(f"**{item['name']}**")
            st.caption(f"{rupees(item['price'])}/hour")
            st.caption(f"{item['distance']:.1f} km away" if item["distance"] is not None else item["area"])
            if st.button("View", key=f"dash_view_{item['id']}"):
                st.session_state.page = "explore"
                st.session_state.focus_item = item["id"]
                st.rerun()
    st.divider()
    left, right = st.columns(2)
    with left:
        if st.button("🔎 Explore nearby products", use_container_width=True):
            st.session_state.page = "explore"
            st.rerun()
    with right:
        if st.button("➕ List something for rent", use_container_width=True):
            st.session_state.page = "give"
            st.rerun()

# ----------------- EXPLORE -----------------
elif st.session_state.page == "explore":
    st.title("🔎 Explore nearby products")
    location_panel()
    c1, c2, c3 = st.columns([2,1,1])
    with c1:
        search = st.text_input("Search products", placeholder="Camera, bicycle, laptop...")
    with c2:
        category = st.selectbox("Category", ["All", "Electronics", "Books", "Sports", "Tools", "Furniture", "Kitchen", "Clothing", "Other"])
    with c3:
        max_price = st.number_input("Max ₹/hour", min_value=0, value=0, step=50)
    radius = st.select_slider("Search radius", options=[1,5,10,20,50], value=st.session_state.radius, format_func=lambda x:f"{x} km")
    st.session_state.radius = radius
    results = nearby_items(st.session_state.location_lat, st.session_state.location_lon, radius, search, category, max_price if max_price > 0 else None)
    st.write(f"**{len(results)}** matching listings")
    if folium is not None and st_folium is not None and st.session_state.location_lat is not None:
        mp = folium.Map(location=[st.session_state.location_lat, st.session_state.location_lon], zoom_start=12)
        folium.Marker([st.session_state.location_lat, st.session_state.location_lon], tooltip="Your selected area", icon=folium.Icon(color="blue")).add_to(mp)
        for item in results:
            if item["lat"] is not None and item["lon"] is not None:
                label = f"{item['name']} · {rupees(item['price'])}/hour"
                folium.Marker([item["lat"], item["lon"]], tooltip=label, popup=label).add_to(mp)
        st_folium(mp, width=None, height=350, returned_objects=[])
    elif results:
        st.caption("Map needs valid coordinates for your location and listings. Results are still searchable below.")
    if not results:
        st.info("No matching listings in this radius. Try increasing the distance or changing filters.")
    for item in results:
        with st.container(border=True):
            a,b = st.columns([1,2])
            with a:
                if item["image"] and Path(item["image"]).exists():
                    st.image(item["image"], use_container_width=True)
                else:
                    st.write("📷 Photo not available")
            with b:
                rating, count = average_rating(item["id"])
                st.subheader(item["name"])
                st.caption(f"{item['category']} · {item['area']} · " + (f"{item['distance']:.1f} km away" if item["distance"] is not None else "Distance unavailable"))
                st.write(item["description"] or "No description added.")
                st.write(f"**{rupees(item['price'])} per hour** · ⭐ {rating if rating else 'New'} ({count} reviews)")
                with st.expander("Compare / book this item"):
                    st.write(f"Listed by: {item['owner_name']}")
                    duration = st.number_input("Rental hours", min_value=1, max_value=720, value=2, key=f"book_hours_{item['id']}")
                    total = duration * item["price"]
                    st.write(f"Estimated rent: **{rupees(total)}**")
                    method = st.radio("Payment preference", ["Online payment (demo only)", "Pay directly to owner"], key=f"method_{item['id']}")
                    if st.button("Request booking", key=f"book_{item['id']}"):
                        now = datetime.now()
                        end = now + timedelta(hours=int(duration))
                        method_db = "Online demo" if method.startswith("Online") else "Direct to owner"
                        payment_status = "Not paid - demo only" if method.startswith("Online") else "Pending direct settlement"
                        with connect() as c:
                            c.execute("""INSERT INTO bookings(item_id,renter_phone,hours,total,status,created_at,end_at,payment_method,payment_status)
                                VALUES(?,?,?,?,?,?,?,?,?)""",
                                (item["id"],st.session_state.phone,int(duration),total,"Requested - awaiting owner approval",
                                 now.isoformat(timespec="seconds"),end.isoformat(timespec="seconds"),method_db,payment_status))
                            c.commit()
                        st.success("Booking request sent to the owner. No payment was collected.")
                    if st.button("♡ Save item", key=f"fav_{item['id']}"):
                        with connect() as c:
                            c.execute("INSERT OR IGNORE INTO favorites(item_id,user_phone) VALUES(?,?)", (item["id"],st.session_state.phone))
                            c.commit()
                        st.success("Saved to your favourites.")

# ----------------- GIVE ITEM -----------------
elif st.session_state.page == "give":
    st.title("➕ List your item")
    st.write("Add a clear photo, fair hourly price and approximate pickup area.")
    with st.form("new_item", clear_on_submit=True):
        name = st.text_input("Product name")
        category = st.selectbox("Category", ["Electronics","Books","Sports","Tools","Furniture","Kitchen","Clothing","Other"])
        description = st.text_area("Description, condition and what's included")
        price = st.number_input("Rental price per hour (₹)", min_value=1.0, value=25.0, step=5.0)
        area = st.text_input("Pickup area / town", value=me[3] or "")
        photo = st.file_uploader("Product photo", type=["jpg","jpeg","png"])
        submitted = st.form_submit_button("Publish listing")
    if submitted:
        if not name.strip() or photo is None or not area.strip():
            st.error("Product name, photo and pickup area are required.")
        else:
            lat, lon = geocode_place(area)
            try:
                image_path = save_photo(photo)
                with connect() as c:
                    c.execute("""INSERT INTO items(owner_phone,name,description,category,price_per_hour,image_path,area,latitude,longitude,created_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (st.session_state.phone,name.strip(),description.strip(),category,price,image_path,area.strip(),lat,lon,datetime.now().isoformat(timespec="seconds")))
                    c.commit()
                st.success("Your item is published.")
            except Exception as e:
                st.error(f"Could not publish item: {e}")

# ----------------- MY RENTALS / TIMER / EXTENSION -----------------
elif st.session_state.page == "rentals":
    st.title("⏱️ My rentals")
    with connect() as c:
        rows = c.execute("""SELECT b.id,b.item_id,b.hours,b.total,b.status,b.end_at,b.payment_method,b.payment_status,i.name,i.price_per_hour
            FROM bookings b JOIN items i ON b.item_id=i.id WHERE b.renter_phone=? ORDER BY b.id DESC""",
            (st.session_state.phone,)).fetchall()
    if not rows:
        st.info("You have not requested any rentals yet.")
    for row in rows:
        bid,iid,hours,total,status,end_at,method,paystatus,item_name,rate = row
        end = parse_dt(end_at)
        with st.container(border=True):
            st.subheader(item_name)
            st.write(f"{status} · {hours} hour(s) · {rupees(total)}")
            st.caption(f"{method or 'Payment not selected'} · {paystatus or 'Payment pending'}")
            if end and status not in ("Declined","Returned"):
                remaining = int((end-datetime.now()).total_seconds())
                if remaining > 0:
                    h, rem = divmod(remaining,3600); m,s = divmod(rem,60)
                    st.metric("Time remaining",f"{h:02d}:{m:02d}:{s:02d}")
                    st.caption(f"Scheduled end: {end.strftime('%d %b %Y, %I:%M %p')}")
                else:
                    st.warning("Rental time has ended. Contact the owner to arrange return.")
            if status == "Approved - rental active" and end and end > datetime.now():
                extra = st.number_input("Extra hours requested",1,168,1,key=f"extra_hours_{bid}")
                extra_total = extra*rate
                st.write(f"Additional rent if approved: **{rupees(extra_total)}**")
                if st.button("Request extra time",key=f"extend_{bid}"):
                    with connect() as c:
                        pending = c.execute("SELECT COUNT(*) FROM extensions WHERE booking_id=? AND status='Pending'",(bid,)).fetchone()[0]
                        if pending:
                            st.warning("An extension request is already pending.")
                        else:
                            c.execute("INSERT INTO extensions(booking_id,requested_hours,extra_cost,status,requested_at) VALUES(?,?,?,'Pending',?)",
                                (bid,int(extra),extra_total,datetime.now().isoformat(timespec="seconds")))
                            c.commit()
                    st.success("Extension request sent to the owner.")
            if status.startswith("Approved") and st.button("Mark item returned",key=f"return_{bid}"):
                with connect() as c:
                    c.execute("UPDATE bookings SET status='Returned' WHERE id=?",(bid,))
                    c.commit()
                st.success("Return recorded.")

# ----------------- OWNER DASHBOARD -----------------
elif st.session_state.page == "owner":
    st.title("📊 Owner dashboard")
    with connect() as c:
        listings = c.execute("SELECT id,name,price_per_hour,available FROM items WHERE owner_phone=?",(st.session_state.phone,)).fetchall()
        stats = c.execute("""SELECT COUNT(*),COALESCE(SUM(total),0) FROM bookings b JOIN items i ON b.item_id=i.id
            WHERE i.owner_phone=? AND b.status LIKE 'Approved%'""",(st.session_state.phone,)).fetchone()
        active = c.execute("""SELECT COUNT(*) FROM bookings b JOIN items i ON b.item_id=i.id
            WHERE i.owner_phone=? AND b.status='Approved - rental active'""",(st.session_state.phone,)).fetchone()[0]
        pending = c.execute("""SELECT COUNT(*) FROM bookings b JOIN items i ON b.item_id=i.id
            WHERE i.owner_phone=? AND b.status LIKE 'Requested%'""",(st.session_state.phone,)).fetchone()[0]
    a,b,c1 = st.columns(3)
    a.metric("My listings",len(listings))
    b.metric("Active rentals",active)
    c1.metric("Pending bookings",pending)
    st.metric("Approved rental value (demo)",rupees(stats[1]))
    st.subheader("Listing performance")
    if listings:
        for iid,n,price,avail in listings:
            with st.container(border=True):
                st.write(f"**{n}** · {rupees(price)}/hour")
                with connect() as c:
                    count = c.execute("SELECT COUNT(*) FROM bookings WHERE item_id=?",(iid,)).fetchone()[0]
                st.caption(f"{count} booking request(s) · {'Available' if avail else 'Unavailable'}")
    else:
        st.info("List your first item to see owner analytics.")

# ----------------- REQUESTS & EXTENSIONS -----------------
elif st.session_state.page == "requests":
    st.title("📨 Booking and extension requests")
    st.subheader("Incoming booking requests")
    with connect() as c:
        bookings = c.execute("""SELECT b.id,b.renter_phone,b.hours,b.total,b.status,b.payment_method,b.payment_status,i.name
            FROM bookings b JOIN items i ON b.item_id=i.id WHERE i.owner_phone=? ORDER BY b.id DESC""",
            (st.session_state.phone,)).fetchall()
    if not bookings:
        st.caption("No incoming requests.")
    for b in bookings:
        bid,renter,hours,total,status,method,paystatus,item_name = b
        with st.container(border=True):
            st.write(f"**{item_name}** · renter account: {renter}")
            st.write(f"{hours} hour(s) · {rupees(total)} · {status}")
            st.caption(f"{method} · {paystatus}")
            if status.startswith("Requested"):
                x,y = st.columns(2)
                with x:
                    if st.button("Approve",key=f"approve_{bid}"):
                        with connect() as c:
                            c.execute("UPDATE bookings SET status='Approved - rental active' WHERE id=?",(bid,))
                            c.commit()
                        st.rerun()
                with y:
                    if st.button("Decline",key=f"decline_{bid}"):
                        with connect() as c:
                            c.execute("UPDATE bookings SET status='Declined' WHERE id=?",(bid,))
                            c.commit()
                        st.rerun()
            if method == "Direct to owner" and status.startswith("Approved") and paystatus != "Owner marked received":
                if st.button("Mark direct payment received",key=f"paid_{bid}"):
                    with connect() as c:
                        c.execute("UPDATE bookings SET payment_status='Owner marked received' WHERE id=?",(bid,))
                        c.commit()
                    st.rerun()
    st.divider()
    st.subheader("Extra-time requests")
    with connect() as c:
        exts = c.execute("""SELECT e.id,e.booking_id,e.requested_hours,e.extra_cost,e.status,b.renter_phone,i.name
            FROM extensions e JOIN bookings b ON e.booking_id=b.id JOIN items i ON b.item_id=i.id
            WHERE i.owner_phone=? ORDER BY e.id DESC""",(st.session_state.phone,)).fetchall()
    if not exts:
        st.caption("No extension requests.")
    for e in exts:
        eid,bid,hrs,cost,status,renter,item = e
        with st.container(border=True):
            st.write(f"**{item}** · {hrs} extra hour(s) · {rupees(cost)}")
            st.caption(f"Renter: {renter} · {status}")
            if status == "Pending":
                x,y = st.columns(2)
                with x:
                    if st.button("Approve extension",key=f"extapprove_{eid}"):
                        with connect() as c:
                            endrow = c.execute("SELECT end_at FROM bookings WHERE id=?",(bid,)).fetchone()
                            old_end = parse_dt(endrow[0]) if endrow and endrow[0] else datetime.now()
                            new_end = max(old_end,datetime.now())+timedelta(hours=hrs)
                            c.execute("UPDATE bookings SET end_at=?,hours=hours+?,total=total+? WHERE id=?",
                                (new_end.isoformat(timespec="seconds"),hrs,cost,bid))
                            c.execute("UPDATE extensions SET status='Approved',decided_at=? WHERE id=?",
                                (datetime.now().isoformat(timespec="seconds"),eid))
                            c.commit()
                        st.rerun()
                with y:
                    if st.button("Decline extension",key=f"extdecline_{eid}"):
                        with connect() as c:
                            c.execute("UPDATE extensions SET status='Declined',decided_at=? WHERE id=?",
                                (datetime.now().isoformat(timespec="seconds"),eid))
                            c.commit()
                        st.rerun()

# ----------------- SAVED ITEMS & REVIEWS -----------------
elif st.session_state.page == "saved":
    st.title("♡ Saved items")
    with connect() as c:
        rows = c.execute("""SELECT i.id,i.name,i.category,i.price_per_hour,i.image_path,i.area
            FROM favorites f JOIN items i ON f.item_id=i.id WHERE f.user_phone=? ORDER BY f.id DESC""",
            (st.session_state.phone,)).fetchall()
    if not rows:
        st.info("You have not saved any products.")
    for iid,n,cat,price,img,area in rows:
        with st.container(border=True):
            if img and Path(img).exists():
                st.image(img,width=180)
            st.write(f"**{n}** · {cat} · {rupees(price)}/hour")
            st.caption(area or "Area unavailable")
            st.write("Review this item after a completed rental:")
            rating = st.select_slider("Rating",options=[1,2,3,4,5],value=5,key=f"rating_{iid}")
            comment = st.text_input("Short review",key=f"comment_{iid}")
            if st.button("Submit review",key=f"review_{iid}"):
                with connect() as c:
                    completed = c.execute("SELECT COUNT(*) FROM bookings WHERE item_id=? AND renter_phone=? AND status='Returned'",
                                           (iid,st.session_state.phone)).fetchone()[0]
                    if not completed:
                        st.warning("You can review after marking a rental as returned.")
                    else:
                        c.execute("""INSERT INTO reviews(item_id,reviewer_phone,rating,comment,created_at)
                            VALUES(?,?,?,?,?) ON CONFLICT(item_id,reviewer_phone) DO UPDATE SET
                            rating=excluded.rating,comment=excluded.comment""",
                            (iid,st.session_state.phone,int(rating),comment.strip(),datetime.now().isoformat()))
                        c.commit()
                st.success("Review saved.")

st.sidebar.divider()
st.sidebar.caption("RentEase student prototype")
st.caption("Prototype notice: GPS and map need browser permission and internet. Online payment is a demo placeholder, not a real charge. Use test data only.")
