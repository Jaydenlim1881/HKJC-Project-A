
import re
import unicodedata
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

def estimate_turn_count(race_course, course_type, distance):
    if race_course == "ST":
        if distance <= 1200:
            return 0
        elif distance <= 1600:
            return 1
        elif distance <= 2200:
            return 2
        else:
            return 3
    elif race_course == "HV":
        if distance <= 1200:
            return 1
        elif distance <= 1650:
            return 2
        elif distance <= 2200:
            return 3
        else:
            return 4
    return 0

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
