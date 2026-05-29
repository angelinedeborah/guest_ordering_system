from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import mysql.connector

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Connecting python directly to  MySQL db
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        database="guest_ordering_system",
        user="root",                 
        password="root",   
        autocommit=True
    )

#  Structure for incoming requests
class GuestLocation(BaseModel):
    restaurant_id: int
    latitude: float
    longitude: float

class AdminZoneInput(BaseModel):
    name: str
    coordinates: list # List of lat, lng points

#  Custom Geospatial Algorithm (Ray-Casting / Point-in-Polygon)
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
        
        # The math check if our ray cross this boundary line
        if ((lng_i > lng) != (lng_j > lng)) and \
           (lat < (lat_j - lat_i) * (lng - lng_i) / (lng_j - lng_i + 1e-9) + lat_i):
            inside = not inside
        j = i
        
    return inside

# 4. The Validation Endpoint Engine
@app.post("/api/validate-location")
async def check_location(guest: GuestLocation):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Fetch the raw boundary coordinates from MySQL instead of using spatial functions
    # ST_AsText converts the map data into plain readable numbers for Python
    cursor.execute("SELECT id, name, ST_AsText(zone_polygon) as polygon_text FROM restaurant_zones WHERE id = %s AND is_active = True", (guest.restaurant_id,))
    restaurant = cursor.fetchone()
    
    if not restaurant:
        cursor.close()
        conn.close()
        return {"in_zone": False, "message": "Restaurant not found.", "can_place_order": False}
    
    # Clean up the text data from MySQL to extract an array of pure numbers
    raw_coords = restaurant['polygon_text'].replace("POLYGON((", "").replace("))", "").split(",")
    polygon_points = []
    for coord in raw_coords:
        parts = coord.strip().split(" ")
        polygon_points.append((float(parts[0]), float(parts[1]))) # (Latitude, Longitude)
        
    # RUN YOUR CUSTOM ALGORITHM HERE!
    is_inside = is_point_in_polygon(guest.latitude, guest.longitude, polygon_points)
    
    # --- AUDIT LOGGING ---
    log_query = """
        INSERT INTO validation_logs (restaurant_id, customer_latitude, customer_longitude, is_inside_zone)
        VALUES (%s, %s, %s, %s);
    """
    cursor.execute(log_query, (guest.restaurant_id, guest.latitude, guest.longitude, is_inside))
    
    cursor.close()
    conn.close()
    
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
            "message": "You are outside the restaurant property limits. You can view the menu, but ordering is locked.",
            "can_place_order": False,
            "show_special_offers": False
        }

# 5. The Admin Endpoint to Save a New Zone
@app.post("/api/admin/zones")
async def create_zone(zone: AdminZoneInput):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    coord_strings = [f"{pt[0]} {pt[1]}" for pt in zone.coordinates]
    if coord_strings[0] != coord_strings[-1]:
        coord_strings.append(coord_strings[0])
        
    wkt_polygon = f"POLYGON(({', '.join(coord_strings)}))"
    
    query = "INSERT INTO restaurant_zones (name, zone_polygon) VALUES (%s, ST_GeomFromText(%s, 4326));"
    cursor.execute(query, (zone.name, wkt_polygon))
    cursor.close()
    conn.close()
    return {"status": "success", "message": f"Zone '{zone.name}' saved successfully!"}