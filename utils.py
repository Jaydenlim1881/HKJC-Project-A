import re
import unicodedata
import csv
import sqlite3
from datetime import datetime
import inspect

def log(level, *args, **kwargs):
    """Simple logging helper with module-level debug control.

    Uses the caller's ``DEBUG_LEVEL`` variable if present (defaults to
    ``"INFO"``). Levels: ``OFF`` < ``INFO`` < ``DEBUG`` < ``TRACE``.
    """
    levels = {"OFF": 0, "INFO": 1, "DEBUG": 2, "TRACE": 3}
    caller_frame = inspect.currentframe().f_back
    debug_level = caller_frame.f_globals.get("DEBUG_LEVEL", "INFO")
    current_level = levels.get(debug_level, 1)
    msg_level = levels.get(level, 0)
    if msg_level <= current_level:
        print(f"[{level}]", *args, **kwargs)

def sanitize_text(text):
    if not text:
        return ""
    try:
        text = str(text)
        text = re.sub(r'[^\x00-\x7F]+', '', text)
        return text.strip()
    except:
        return ""

def clean_placing(placing_text):
    clean_text = sanitize_text(placing_text)
    digits_only = re.sub(r'[^\d]', '', clean_text)
    return int(digits_only) if digits_only.isdigit() and int(digits_only) > 0 else None

def convert_finish_time(time_str):
    if not time_str:
        return None
    try:
        time_str = time_str.strip().replace(":", ".")
        parts = time_str.split(".")
        if len(parts) == 3:
            mins, secs, hundredths = parts
            return round(int(mins) * 60 + int(secs) + int(hundredths) / 100, 2)
        elif len(parts) == 2:
            secs, hundredths = parts
            return round(int(secs) + int(hundredths) / 100, 2)
        else:
            return None
    except:
        return None

def safe_int(value):
    try:
        return int(value)
    except:
        return None

def safe_float(value):
    try:
        return float(value)
    except:
        return None

def parse_weight(weight_str):
    try:
        return int(weight_str.replace("lb", "").strip())
    except:
        return None

def parse_lbw(lbw_str, placing):
    lbw_str = sanitize_text(lbw_str)
    if placing == 1:
        return 0.0
    try:
        return float(lbw_str)
    except:
        return None

def get_season_code(date_obj):
    if date_obj.month >= 9:
        return f"{date_obj.year%100:02d}/{(date_obj.year+1)%100:02d}"
    else:
        return f"{(date_obj.year-1)%100:02d}/{date_obj.year%100:02d}"

def get_distance_group(race_course, course_type, distance):
    course_type = course_type.upper()
    race_course = race_course.upper()

    if race_course == "ST":
        if course_type == "AWT":
            if distance <= 1000:
                return "Sprint"
            if distance <= 1200:
                return "Short"
            elif distance <= 1400:
                return "Short"
            elif distance <= 1650:
                return "Mid"
            elif distance <= 2000:
                return "Long"
            else:
                return "Endurance"
        else:
            if distance <= 1000:
                return "Sprint"
            elif distance <= 1400:
                return "Short"
            elif distance <= 1800:
                return "Mid"
            elif distance <= 2200:
                return "Long"
            else:
                return "Endurance"
    elif race_course == "HV":
        if distance <= 1000:
            return "Sprint"
        elif distance <= 1200:
            return "Short"
        elif distance <= 1800:
            return "Mid"
        elif distance <= 2200:
            return "Long"
        else:
            return "Endurance"
    return "Unknown"

def get_distance_group_from_row(course_info, distance_str):
    try:
        course_info = sanitize_text(course_info)
        if "AWT" in course_info:
            race_course = "ST"
            course_type = "AWT"
        else:
            parts = course_info.split("/")
            race_course = parts[0].strip() if len(parts) > 0 else "Unknown"
            course_type = parts[2].strip() if len(parts) > 2 else "Turf"
        return get_distance_group(race_course, course_type, int(distance_str))
    except:
        return "Unknown"

# ====== INSERT FIELD SIZE FUNCTIONS HERE ======
# --- Field size lookup -------------------------------------------------------

def _load_race_field_lookup(csv_path: str = "Race_Fieldsize.csv"):
    """Load Race_Fieldsize.csv into a lookup dict."""
    lookup = {}
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                try:
                    key = (
                        row["RaceDate"].strip(),
                        row["RaceCourse"].strip().upper(),
                        int(row["RaceNo"]),
                    )
                    lookup[key] = int(row["FieldSize"])
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return lookup

# Loaded once at module import
_FIELD_SIZE_LOOKUP = _load_race_field_lookup()

def get_field_size(race_date: str, race_course: str, race_no) -> int | None:
    """Return field size for given race identifiers."""
    if race_date is None or race_course is None or race_no is None:
        return None
    race_course = race_course.strip().upper()
    try:
        race_no_int = int(race_no)
    except Exception:
        return None

    key = (race_date, race_course, race_no_int)
    field_size = _FIELD_SIZE_LOOKUP.get(key)
    if field_size is not None:
        return field_size

    # Fallback to database lookup
    try:
        conn = sqlite3.connect("hkjc_horses_dynamic.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT FieldSize FROM horse_running_position WHERE RaceDate=? AND RaceCourse=? AND RaceNo=? LIMIT 1",
            (race_date.replace("/", "-"), race_course, str(race_no_int)),
        )
        if row := cur.fetchone():
            return int(row[0])
    except Exception:
        pass
    return None

def backfill_field_sizes():
    """Backfill NULL FieldSize values in database."""
    conn = sqlite3.connect("hkjc_horses_dynamic.db")
    cur = conn.cursor()
    
    # Get races with NULL FieldSize
    cur.execute("""
        SELECT DISTINCT RaceDate, RaceCourse, RaceNo 
        FROM horse_running_position 
        WHERE FieldSize IS NULL
    """)
    
    updated = 0
    for race_date, race_course, race_no in cur.fetchall():
        field_size = get_field_size(race_date, race_course, race_no)
        if field_size:
            cur.execute("""
                UPDATE horse_running_position
                SET FieldSize = ?
                WHERE RaceDate = ? AND RaceCourse = ? AND RaceNo = ?
                AND FieldSize IS NULL
            """, (field_size, race_date, race_course, race_no))
            updated += cur.rowcount
    
    conn.commit()
    conn.close()
    log("INFO", f"Backfilled {updated} NULL FieldSize values")

# --- Turn geometry (CountTurn) helpers ---------------------------------------

def _norm_course(course: str) -> str:
    """Normalize race course to canonical short code: 'ST' or 'HV'."""
    t = (course or "").strip().upper()
    if t in {"ST", "SHA TIN"} or "SHA TIN" in t:
        return "ST"
    if t in {"HV", "HAPPY VALLEY"} or "HAPPY VALLEY" in t:
        return "HV"
    return t  # leave unknowns as-is

def _norm_surface(surface: str) -> str:
    """Normalize surface to canonical: 'TURF' or 'AWT'."""
    t = (surface or "").strip().upper()
    if t in {"TURF", "T"}:
        return "TURF"
    if t in {"AWT", "ALL WEATHER", "ALL-WEATHER", "ALL WEATHER TRACK", "DIRT"}:
        return "AWT"
    return t  # leave unknowns as-is

# Exact mapping per your specification
_TURN_COUNT_MAP = {
    ("ST", "TURF"): {
        1000: 0.0,
        1200: 1.0, 1400: 1.0, 1600: 1.0, 1800: 1.0,
        2000: 2.0, 2200: 2.0, 2400: 2.0,
    },
    ("ST", "AWT"): {
        1200: 1.0,
        1650: 2.0, 1800: 2.0, 2000: 2.0,
        2400: 3.0,
    },
    ("HV", "TURF"): {
        1000: 1.0,
        1200: 1.5,
        1650: 2.5, 1800: 2.5,
        2200: 3.5, 2400: 3.5,
    },
}

def get_turn_count(race_course: str, surface: str, distance: int | str):
    """Return CountTurn as float; None if unmapped."""
    try:
        d = int(str(distance).strip())
    except Exception:
        return None
    c = _norm_course(race_course)
    s = _norm_surface(surface)
    if c == "HV":
        s = "TURF"
    m = _TURN_COUNT_MAP.get((c, s))
    if not m:
        return None
    return m.get(d)

def is_straight(turn_count):
    return turn_count == 0.0

def is_fractional_turn(turn_count):
    return (turn_count is not None) and (float(turn_count) % 1.0 != 0.0)

def is_one_turn_exact(turn_count):
    return turn_count == 1.0

def get_draw_group(draw_number, field_size=None):
    """
    Map barrier draw to fixed groups (field_size ignored intentionally):
      Inside   = 1–3
      InnerMid = 4–6
      OuterMid = 7–9
      Wide     = 10–12
      Outer    = 13+
    Returns one of: "Inside", "InnerMid", "OuterMid", "Wide", "Outer" or None.
    """
    # Accept strings like " 9 " and handle None/"-" etc.
    if draw_number is None:
        return None
    try:
        d = int(str(draw_number).strip())
    except (ValueError, TypeError):
        return None

    if 1 <= d <= 3:
        return "Inside"
    if 4 <= d <= 6:
        return "InnerMid"
    if 7 <= d <= 9:
        return "OuterMid"
    if 10 <= d <= 12:
        return "Wide"
    if d >= 13:
        return "Outer"
    return None

def get_jump_type(previous_class, current_class):
    try:
        prev = int(previous_class)
        curr = int(current_class)
        if curr < prev:
            return "UP"
        elif curr > prev:
            return "DOWN"
        else:
            return "SAME"
    except:
        return "UNKNOWN"

