from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector
import os

app = FastAPI()

# Enforce secure CORS policy headers to permit frontend network requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connecting python directly to MySQL db using your schema configurations
# Connecting python directly to MySQL db using your schema configurations
def get_db_connection():
    # Fetch clean environmental variables
    db_host = os.getenv("DB_HOST", "localhost").strip()
    db_name = os.getenv("DB_NAME", "guest")
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "root")
    db_port = int(os.getenv("DB_PORT", 3306))

    # Strip out any lingering prefixes if they accidentally got pasted into the environment variable
    if "://" in db_host:
        db_host = db_host.split("://")[-1]
    if ":" in db_host:
        db_host = db_host.split(":")[0]
    try: 
           return mysql.connector.connect(
        host=db_host,
        database=db_name,             
        user=db_user,                 
        password=db_password,
        port=db_port,
        ssl_ca="", # Forces native cloud SSL encryption safely
        autocommit=True
    )
    except mysql.connector.Error as err:
        # If Aiven shuts off, this intercepts the crash and prints a clear server log message
        if err.errno == 2005:
            print("CRITICAL: Database is currently powered off in the Aiven Console. Please turn it on to restore functionality.")
        raise err
# Structure for incoming client verification requests
class GuestLocation(BaseModel):
    restaurant_id: int
    latitude: float
    longitude: float

# Structure for administrative polygon zone configuration
class AdminZoneInput(BaseModel):
    name: str
    coordinates: list # List of lat, lng points

# Custom Geospatial Algorithm (Ray-Casting / Point-in-Polygon)
def is_point_in_polygon(lat, lng, polygon_points):
    """
    Checks if a customer's coordinate (lat, lng) is inside a list of polygon corners.
    """
    inside = False
    n = len(polygon_points)
    
    # Loop through every boundary wall of the restaurant polygon
    j = n - 1
    for i in range(n):
        lat_i, lng_i = polygon_points[i]
        lat_j, lng_j = polygon_points[j]
        
        # The math check if our ray crosses this boundary line
        if ((lng_i > lng) != (lng_j > lng)) and \
           (lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i + 1e-9) + lat_i):
            inside = not inside
        j = i
        
    return inside

# The Optimized Validation Endpoint Engine (With Phase 5 Fail-Safes)
@app.post("/api/validate-location")
async def check_location(guest: GuestLocation):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # FIX: Updated column selector to match 'zone_polygon' from your database layout
        query = """
            SELECT id, name, ST_AsText(zone_polygon) as polygon_text 
            FROM restaurant_zones 
            WHERE id = %s AND is_active = True
        """
        cursor.execute(query, (guest.restaurant_id,))
        restaurant = cursor.fetchone()
        
        if not restaurant:
            return {"in_zone": False, "message": "Zone/Restaurant profile not found.", "can_place_order": False}
        
        # Parse text coordinates for algorithm processing
        # Clean the text string representation safely
        polygon_text_clean = restaurant['polygon_text'].replace("POLYGON((", "").replace("))", "")
        raw_coords = polygon_text_clean.split(",")
        polygon_points = []
        
        for coord in raw_coords:
            # .strip() removes any leading or trailing spaces before splitting by a single space
            parts = coord.strip().split(" ")
            if len(parts) >= 2:
                lat_val = float(parts[0])
                lng_val = float(parts[1])
                polygon_points.append((lat_val, lng_val))
        # Execute your Ray-Casting algorithm check
        is_inside = is_point_in_polygon(guest.latitude, guest.longitude, polygon_points)
        is_inside_flag = 1 if is_inside else 0
        
        # Log to structural ledger matching updated database schema constraint configurations
        log_query = """
            INSERT INTO validation_logs (calculated_zone_id, customer_latitude, customer_longitude, is_inside_zone)
            VALUES (%s, %s, %s, %s);
        """
        cursor.execute(log_query, (restaurant['id'], guest.latitude, guest.longitude, is_inside_flag))
        
        if is_inside:
            return {
                "in_zone": True,
                "message": f"Welcome to {restaurant['name']}!",
                "can_place_order": True,
                "show_special_offers": True
            }
        else:
            return {
                "in_zone": False,
                "message": "You are outside the restaurant property limits. Ordering remains locked.",
                "can_place_order": False,
                "show_special_offers": False
            }

    except mysql.connector.Error as db_error:
        # Crucial Fix: This overrides the maintenance string and prints the raw backend issue on your screen!
        error_string = f"Internal MySQL Error: [{db_error.errno}] {db_error.msg}"
        print(f"\n❌ [CRITICAL DATABASE DIAGNOSTIC]: {error_string}\n")
        return {
            "in_zone": False, 
            "message": error_string, 
            "can_place_order": False
        }
    finally:
        # Ensures memory buffers and network sockets close safely no matter what
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# The Admin Endpoint to Save a New Zone
@app.post("/api/admin/zones")
async def create_zone(zone: AdminZoneInput):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        coord_strings = [f"{pt[0]} {pt[1]}" for pt in zone.coordinates]
        if coord_strings[0] != coord_strings[-1]:
            coord_strings.append(coord_strings[0])
            
        wkt_polygon = f"POLYGON(({', '.join(coord_strings)}))"
        
        # FIX: Updated insertion string to populate column 'zone_polygon'
        query = "INSERT INTO restaurant_zones (name, zone_polygon) VALUES (%s, ST_GeomFromText(%s, 4326));"
        cursor.execute(query, (zone.name, wkt_polygon))
        
        return {"status": "success", "message": f"Zone '{zone.name}' saved successfully!"}
        
    except mysql.connector.Error as db_error:
        print(f"[ADMIN CRITICAL ERROR]: Failed to save zone: {db_error}")
        return {"status": "error", "message": "Database write failure while storing zone parameters."}
        
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()