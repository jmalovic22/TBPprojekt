import streamlit as st
import psycopg2
import folium
import json
from streamlit_folium import st_folium

# --- KONFIGURACIJA BAZE ---
DB_CONFIG = {
    "host": "127.0.0.1",
    "database": "projekttbp",  # Tvoje ime baze
    "user": "postgres",
    "password": "postgres"
}

# --- 2. FUNKCIJE ZA RAD S BAZOM (UZ CACHE I UTF-8) ---

def provjeri_login(username, password):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    query = "SELECT id, role FROM korisnici WHERE username = %s AND password_hash = %s"
    cur.execute(query, (username, password))
    user = cur.fetchone()
    conn.close()
    return user

#@st.cache_data # Ovo će drastično ubrzati aplikaciju
def dohvati_zupanije():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # ST_Simplify(geom, 0.001) smanjuje broj točaka i ubrzava zoomiranje
    query = "SELECT naziv, ST_AsGeoJSON(ST_Simplify(geom, 0.001)) FROM zupanije"
    #query = "SELECT naziv, ST_AsGeoJSON(geom) FROM zupanije"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()

    features = []
    for naziv, geom_str in rows:
        features.append({
            "type": "Feature",
            "properties": {"naziv": naziv},
            "geometry": json.loads(geom_str)
        })
    return {"type": "FeatureCollection", "features": features}

def dohvati_parkove():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # ST_Simplify(geom, 0.001) smanjuje broj točaka i ubrzava zoomiranje
    query = 'SELECT name, ST_AsGeoJSON(geom) FROM "Parkovi"'
    #query = "SELECT naziv, ST_AsGeoJSON(geom) FROM zupanije"
    cur.execute(query)
    rows = cur.fetchall()
    conn.close()

    features = []
    for naziv, geom_str in rows:
        features.append({
            "type": "Feature",
            "properties": {"naziv": naziv},
            "geometry": json.loads(geom_str)
        })
    return {"type": "FeatureCollection", "features": features}

#@st.cache_data
def dohvati_parkove_za_korisnika(user_id, role):
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()
    
    if role == 'admin':
        # Admin vidi sve: koristimo podupit da izbrojimo sve posjete za svaki park
        query = """
            SELECT 
                p.id, 
                COALESCE(p.name, 'Park') as name, 
                ST_Y(ST_Centroid(p.geom)) as lat, 
                ST_X(ST_Centroid(p.geom)) as lon,
                (SELECT COUNT(*) FROM posjete WHERE park_id = p.id) as ukupno_posjeta
            FROM "Parkovi" p
        """
        cur.execute(query)
    else:
        # Običan korisnik vidi samo svoje (kao i do sada)
        query = """
            SELECT 
                p.id, 
                COALESCE(p.name, 'Park') as name, 
                ST_Y(ST_Centroid(p.geom)) as lat, 
                ST_X(ST_Centroid(p.geom)) as lon,
                v.datum_posjeta
            FROM "Parkovi" p
            LEFT JOIN posjete v ON p.id = v.park_id AND v.user_id = %s
            ORDER BY p.name
        """
        cur.execute(query, (user_id,))
    
    podaci = cur.fetchall()
    conn.close()
    return podaci

def dohvati_admin_statistiku():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    query = """
        SELECT 
            COALESCE(p.name, 'Nepoznati park') as naziv, 
            COUNT(v.id) as broj_posjeta
        FROM "Parkovi" p
        LEFT JOIN posjete v ON p.id = v.park_id
        GROUP BY p.name
        ORDER BY broj_posjeta DESC
    """
    cur.execute(query)
    podaci = cur.fetchall()
    conn.close()
    return podaci

def upisi_posjetu(user_id, park_id, ocjena, biljeska):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    try:
        query = "INSERT INTO posjete (user_id, park_id, ocjena, biljeska) VALUES (%s, %s, %s, %s)"
        cur.execute(query, (user_id, park_id, ocjena, biljeska))
        conn.commit()
        st.success("Posjeta zabilježena!")
    except psycopg2.Error:
        st.error("Greška ili već postoji zapis.")
    finally:
        conn.close()

# --- STREAMLIT APLIKACIJA ---

st.set_page_config(page_title="Geo Evidencija", layout="wide")

if 'selected_park_name' not in st.session_state:
    st.session_state['selected_park_name'] = None

if 'user_id' not in st.session_state:
    st.title("🔐 Prijava")
    col1, col2 = st.columns(2)
    username = col1.text_input("Username")
    password = col2.text_input("Password", type="password")
    
    if st.button("Login"):
        user = provjeri_login(username, password)
        if user:
            st.session_state['user_id'] = user[0]
            st.session_state['role'] = user[1]
            st.session_state['username'] = username
            st.rerun()
        else:
            st.error("Krivi podaci")
else:
    st.sidebar.title(f"Korisnik: {st.session_state['username']}")
    if st.sidebar.button("Logout"):
        del st.session_state['user_id']
        st.rerun()

    # --- GLAVNA MAPA ---
    st.title("🇭🇷 Karta Županija i Parkova")

    # 1. Postavi praznu mapu (CartoDB positron je dobar za isticanje granica)
    m = folium.Map(location=[44.5, 16.0], zoom_start=7, tiles="CartoDB positron")

    # 2. DOHVATI I NACRTAJ ŽUPANIJE (LAYER 1)
    zupanije_geojson = dohvati_zupanije()
    
    if zupanije_geojson["features"]:
        folium.GeoJson(
            zupanije_geojson,
            name="Županije",
            style_function=lambda x: {
                'fillColor': 'white',      # Unutrašnjost županije
                'color': "#1001DF",        # Boja granice (tamno siva)
                'weight': 2,               # Debljina linije granice
                'fillOpacity': 0.4         # Blaga prozirnost
            },
            # Ovo dodaje tooltip: kad pređeš mišem piše ime županije
            tooltip=folium.GeoJsonTooltip(fields=['naziv'], labels=False)
        ).add_to(m)

    parkovi_geojson = dohvati_parkove()
    
    # 3. DOHVATI I NACRTAJ parkove (LAYER 2)
    if parkovi_geojson["features"]:
        folium.GeoJson(
            parkovi_geojson,
            name="Parkovi",
            style_function=lambda x: {
                'fillColor': 'orange',      # Unutrašnjost županije
                'color': "#00000026",        # Boja granice (tamno siva)
                'weight': 2,               # Debljina linije granice
                'fillOpacity': 0.4         # Blaga prozirnost
            },
            # Ovo dodaje tooltip: kad pređeš mišem piše ime županije
            tooltip=folium.GeoJsonTooltip(fields=['naziv'], labels=False)
        ).add_to(m)

    # 4. DOHVATI I NACRTAJ PARKOVE (LAYER 3 - IZNAD ŽUPANIJA)
    # Dohvaćamo podatke šaljući i ulogu (role)
    parkovi = dohvati_parkove_za_korisnika(st.session_state['user_id'], st.session_state['role'])
    ne_posjeceni_parkovi = []

    for park in parkovi:
        p_id, p_ime, lat, lon, info_vrijednost = park # info_vrijednost je ili broj posjeta (admin) ili datum (user)
        
        if st.session_state['role'] == 'admin':
            # --- LOGIKA ZA ADMINA ---
            broj_posjeta = info_vrijednost # U admin upitu, 5. stupac je COUNT
            
            if broj_posjeta > 0:
                boja_marker = "blue"
                ikona_tip = "users" # Ikona grupe ljudi za admina
                status_txt = f"Ukupno posjeta u sustavu: <b>{broj_posjeta}</b>"
            else:
                boja_marker = "red"
                ikona_tip = "times"
                status_txt = "Nitko još nije posjetio ovaj park."
        else:
            # --- LOGIKA ZA KORISNIKA ---
            datum = info_vrijednost # U user upitu, 5. stupac je datum_posjeta
            if datum:
                boja_marker = "green"
                ikona_tip = "check"
                status_txt = f"Posjetili ste: {datum}"
            else:
                boja_marker = "red"
                ikona_tip = "times"
                status_txt = "Niste još posjetili ovaj park."
                ne_posjeceni_parkovi.append((p_ime, p_id))

        folium.Marker(
            [lat, lon],
            popup=folium.Popup(f"<h5>{p_ime}</h5>{status_txt}", max_width=300),
            icon=folium.Icon(color=boja_marker, icon=ikona_tip, prefix='fa'),
            tooltip=p_ime
        ).add_to(m)

    st_folium(m, width=1000, height=600)

    # --- ADMIN VS USER LOGIKA ---
    st.divider()
    
    if st.session_state['role'] == 'admin':
        st.subheader("📊 Admin Statistika")
        statistika = dohvati_admin_statistiku()
        chart_data = {"Park": [r[0] for r in statistika], "Posjeta": [r[1] for r in statistika]}
        st.bar_chart(data=chart_data, x="Park", y="Posjeta")
    else:
        st.subheader("📝 Unesi posjetu")
        if ne_posjeceni_parkovi:
            col1, col2 = st.columns(2)
            with col1:
                odabrani_park = st.selectbox("Park:", ne_posjeceni_parkovi, format_func=lambda x: x[0])
            with col2:
                ocjena = st.slider("Ocjena", 1, 5, 5)
                biljeska = st.text_area("Bilješka")
            
            if st.button("Spremi"):
                upisi_posjetu(st.session_state['user_id'], odabrani_park[1], ocjena, biljeska)
                st.rerun()
        else:
            st.success("Sve posjećeno!")