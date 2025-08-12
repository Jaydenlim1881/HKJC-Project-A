from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup
import pandas as pd
import time
import os
import re
from datetime import datetime
import logging
from tenacity import retry, stop_after_attempt
from utils import get_season_code, get_distance_group

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG = {
    'chromedriver_path': './chromedriver',
    'output_dir': 'data/ml_ready_races',
    'wait_time': 2,
    'max_attempts': 3,
    'columns': [
        'RaceDate', 'Season', 'RaceCourse', 'RaceNo', 'RaceID', 'Distance', 'DistanceGroup', 'GoingType', 'Surface', 'CourseType',
        'ClassType', 'Class', 'ClassML', 'ClassGriffin', 'ClassGroup', 'ClassRestricted', 'ClassYear',
        'ClassCategory', 'HorseNumber', 'HorseID', 'HorseName', 'Jockey', 'Trainer',
        'ActualWeight', 'DeclaredHorseWeight', 'Draw', 'LBW', 'RunningPosition', 'FinishTime',
        'WinOdds', 'Placing', 'RaceGrade'
    ]
}

def initialize():
    os.makedirs(CONFIG['output_dir'], exist_ok=True)
    service = Service(CONFIG['chromedriver_path'])
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    return webdriver.Chrome(service=service, options=options)

def clean_text(text):
    if not text or str(text).strip() in ('', 'N/A', '---', '--'):
        return None
    return re.sub(r'[\xa0\s]+', ' ', str(text)).strip()

def safe_int(value):
    cleaned = re.sub(r'[^\d]', '', str(value))
    return int(cleaned) if cleaned else None

def safe_float(value):
    cleaned = re.sub(r'[^\d.]', '', str(value))
    return float(cleaned) if cleaned else None

def parse_date(raw_date):
    s = clean_text(raw_date) or ''
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', s)
    if not m:
        return None
    day, month, year = m.groups()
    fmt_in = '%d/%m/%Y' if len(year) == 4 else '%d/%m/%y'
    dt = datetime.strptime(f'{day}/{month}/{year}', fmt_in)
    return dt.strftime('%d/%m/%y')   # always DD/MM/YY

def parse_distance(dist_str):
    try:
        dist_text = clean_text(dist_str) or ''
        if 'M' in dist_text.upper():
            return safe_int(re.search(r'(\d+)M', dist_text.upper()).group(1))
        else:
            return safe_int(re.search(r'(\d+)', dist_text).group(1))
    except:
        return None

def parse_weight(weight_str):
    try:
        return safe_int(re.search(r'(\d+)', clean_text(weight_str) or '').group(1))
    except:
        return None

def abbreviate_going(going, surface):
    """Convert going to short form based on surface type (Turf/AWT)."""
    if not going:
        return None
    
    going_upper = going.strip().upper()
    
    # Turf track abbreviations
    turf_mapping = {
        'GOOD TO FIRM': 'GF',
        'GOOD': 'G',
        'GOOD TO YIELDING': 'GY',
        'YIELDING': 'Y',
        'SOFT': 'S',
        'FIRM': 'F',
        'HEAVY': 'H',
        'YIELDING TO SOFT': 'YS'
    }
    
    # AWT track abbreviations
    awt_mapping = {
        'GOOD': 'GD',
        'WET SLOW': 'WS',
        'SEALED': 'SE',
        'WET FAST': 'WF',
        'FAST': 'FT',
        'SLOW': 'SL'
    }
    
    return awt_mapping.get(going_upper, going) if surface == 'AWT' else turf_mapping.get(going_upper, going)

def encode_race_class(raw_class):
    if not raw_class:
        return {
            'ClassType': 'unknown',
            'ClassGroup': 0,
            'ClassLevel': 0,
            'ClassRestricted': 0,
            'ClassYear': 0,
            'ClassGriffin': 0,
            'RaceGrade': None
        }
    class_str = (clean_text(raw_class) or '').lower()
    features = {
        'ClassType': 'standard',
        'ClassGroup': 0,
        'ClassLevel': 0,
        'ClassRestricted': 1 if 'restricted' in class_str else 0,
        'ClassYear': 0,
        'ClassGriffin': 1 if 'griffin' in class_str else 0,
        'RaceGrade': None
    }
    try:
        if 'group' in class_str:
            features['ClassType'] = 'group'
            if 'one' in class_str: 
                features['RaceGrade'] = 1
                features['ClassGroup'] = 1
            elif 'two' in class_str: 
                features['RaceGrade'] = 2
                features['ClassGroup'] = 2
            elif 'three' in class_str: 
                features['RaceGrade'] = 3
                features['ClassGroup'] = 3
        elif class_num := re.search(r'class (\d+)', class_str):
            features['ClassLevel'] = safe_int(class_num.group(1))
        elif year_match := re.search(r'(\d+) year', class_str):
            year = safe_int(year_match.group(1))
            features['ClassType'] = 'age'
            features['ClassYear'] = year
            features['ClassLevel'] = 0
        if features['ClassGriffin'] == 1:
            features['ClassLevel'] = 6

        # ✅ Convert to short-form ClassType
        class_type_map = {
            'standard': 'STD',
            'griffin': 'GRF',
            'group': 'GRP',
            'restricted': 'RST',
            'age': 'AGE'
        }
        features['ClassType'] = class_type_map.get(features['ClassType'], features['ClassType'])

    except Exception as e:
        logger.warning(f"Class encoding error: {e}")
    return features

def convert_time_to_seconds(time_str):
    try:
        parts = time_str.split(':')
        if len(parts) == 2:
            return safe_float(parts[0])*60 + safe_float(parts[1])
        return safe_float(time_str)
    except:
        return None

def parse_lbw(lbw_str, finish_pos):
    if finish_pos == 1:
        return "0.01"
    try:
        cleaned = clean_text(lbw_str)
        if cleaned in ('-', None, 'N/A', '---', '--', ''):
            return None
        cleaned = cleaned.upper()
        special_cases = {
            'SAME': '0.01', 'DH': '0.01', 'DHT': '0.01', 'NOSE': '0.05', 'SH': '0.1', 'HD': '0.2',
            'NK': '0.3', 'N': '0.3', 'S.DIST': '50', 'DIST': '99'
        }
        if cleaned in special_cases:
            return special_cases[cleaned]
        if '/' in cleaned:
            parts = cleaned.split('/')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return str(float(parts[0]) / float(parts[1]))
        if '-' in cleaned and '/' in cleaned:
            whole, fraction = cleaned.split('-')
            num, denom = fraction.split('/')
            if whole.isdigit() and num.isdigit() and denom.isdigit():
                return str(float(whole) + (float(num) / float(denom)))
        if re.match(r'^\d*\.?\d+$', cleaned):
            return cleaned
        if cleaned.isdigit():
            return cleaned
        if cleaned.endswith('L') and cleaned[:-1].isdigit():
            return cleaned[:-1]
        return None
    except Exception as e:
        logger.warning(f"LBW parsing error for '{lbw_str}': {e}")
        return None

@retry(stop=stop_after_attempt(CONFIG['max_attempts']))
def scrape_race(driver, race_date, course, race_num):
    url = f"https://racing.hkjc.com/racing/information/English/Racing/LocalResults.aspx?RaceDate={race_date}&Racecourse={course}&RaceNo={race_num}"
    try:
        driver.get(url)
        time.sleep(CONFIG['wait_time'])
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        if "No result" in soup.text:
            logger.info(f"No results for {course} R{race_num}")
            return None

        # Parse race header: e.g., "RACE 1 (828)"
        race_header_td = soup.find('td', colspan="16")
        race_id_value = None
        if race_header_td:
            match = re.search(r'\((\d+)\)', race_header_td.get_text())
            if match:
                race_id_value = match.group(1)

        # Going
        going_td = soup.find_all('td', colspan="14")
        going_value = clean_text(going_td[0].get_text()) if len(going_td) >= 1 else None

        # Surface and CourseType
        surface_td = going_td[1] if len(going_td) >= 2 else None
        surface_text = clean_text(surface_td.get_text()) if surface_td else None
        Turf_surface_value = None
        Turf_type_value = None

        if surface_text:
            if 'ALL WEATHER TRACK' in surface_text.upper():
                Turf_surface_value = 'AWT'
                Turf_type_value = 'AWT'
            elif '-' in surface_text:
                parts = surface_text.split('-')
                Turf_surface_value = 'TURF'
                Turf_type_value = clean_text(parts[1])

        # CourseType abbreviations
        course_type_abbreviations = {
            '"A" Course': 'A',
            '"A+2" Course': 'A+2',
            '"A+3" Course': 'A+3',
            '"B" Course': 'B',
            '"B+2" Course': 'B+2',
            '"C" Course': 'C',
            '"C+3" Course': 'C+3',
            'ALL WEATHER TRACK': 'AWT'
        }
        abbreviated_course_type = course_type_abbreviations.get(Turf_type_value, Turf_type_value)

        race_date = parse_date(soup.find('span', class_='f_fl f_fs13'))
        race_course = 'ST' if course == 'ST' else 'HV'
        course_type = abbreviated_course_type
        distance = parse_distance(soup.find('td', style=re.compile('width')))
        season = get_season_code(datetime.strptime(race_date, "%d/%m/%y")) if race_date else None
        distance_group = get_distance_group(race_course, course_type, distance) if distance is not None else None

        metadata = {
            'RaceDate': race_date,
            'Season': season,
            'RaceCourse': race_course,
            'RaceNo': race_num,
            'RaceID': race_id_value,
            'Distance': distance,
            'DistanceGroup': distance_group,
            'GoingType': abbreviate_going(going_value, Turf_surface_value),  # Updated line
            'Surface': Turf_surface_value,
            'CourseType': course_type
        }

        class_td = soup.find('td', style=re.compile('width'))
        class_features = encode_race_class(class_td.get_text() if class_td else None)

        # ✅ Force ClassType to 'GRF' if it's a Griffin race
        if class_features.get("ClassGriffin", 0) == 1:
            class_features["ClassType"] = "GRF"

        # ✅ Force ClassType to 'RST' if it's a Restricted race and not Griffin
        elif class_features.get("ClassRestricted", 0) == 1:
            class_features["ClassType"] = "RST"

        # ✅ Fix ClassLevel + Binary Flags for Group races
        if class_features["ClassType"] == "GRP":
            class_features["ClassLevel"] = class_features.get("ClassGroup", 0)
            class_features["ClassGroup"] = 1  # force binary flag

        # ✅ Fix ClassLevel + Binary Flags for Age races
        elif class_features["ClassType"] == "AGE":
            class_features["ClassLevel"] = class_features.get("ClassYear", 0)
            class_features["ClassYear"] = 1  # force binary flag

        # ✅ Reconstruct ClassCategory
        class_features["ClassCategory"] = f"{class_features['ClassType']}_{class_features['ClassLevel']}"

        # ✅ Finalize both human-readable "Class" and ML-friendly "ClassML"
        if class_features["ClassType"] == "GRP":
            class_features["Class"] = f"G{class_features['ClassLevel']}"
            class_features["ClassML"] = class_features['ClassLevel']
        elif class_features["ClassType"] == "AGE":
            class_features["Class"] = f"{class_features['ClassLevel']}YO"
            class_features["ClassML"] = class_features['ClassLevel']
        elif class_features["ClassType"] == "GRF":
            class_features["Class"] = "GRIFFIN"
            class_features["ClassML"] = 6
        elif class_features["ClassType"] == "RST":
            class_features["Class"] = f"{class_features['ClassLevel']}R"
            class_features["ClassML"] = class_features['ClassLevel']
        else:  # STD
            class_features["Class"] = str(class_features['ClassLevel'])
            class_features["ClassML"] = class_features['ClassLevel']

        results = []
        for row in soup.select('table.f_tac tr'):
            cols = row.find_all('td')
            if len(cols) < 12:
                continue
            horse_num_text = clean_text(cols[1].get_text())
            if not horse_num_text or not str(horse_num_text).isdigit():
                continue
            try:
                finish_pos = safe_int(clean_text(cols[0].get_text()))
                horse_info = cols[2].find('a', class_='local')
                horse_id = None
                if horse_info and 'href' in horse_info.attrs:
                    if match := re.search(r'HorseId=([^&]+)', horse_info['href']):
                        horse_id = match.group(1)
                horse_data = {
                    **metadata,
                    **class_features,
                    'ClassML': class_features["ClassML"],
                    'Placing': finish_pos,
                    'HorseNumber': safe_int(horse_num_text),
                    'HorseID': horse_id,
                    'HorseName': clean_text(horse_info.get_text() if horse_info else None),
                    'Jockey': clean_text(cols[3].get_text()),
                    'Trainer': clean_text(cols[4].get_text()),
                    'ActualWeight': parse_weight(cols[5].get_text()),
                    'DeclaredHorseWeight': parse_weight(cols[6].get_text()),
                    'Draw': safe_int(clean_text(cols[7].get_text())),
                    'LBW': parse_lbw(cols[8].get_text(), finish_pos),
                    'RunningPosition': clean_text(cols[9].get_text(' ').split(' ', 1)[-1]) if len(cols) > 9 else None,
                    'FinishTime': convert_time_to_seconds(cols[10].get_text() if len(cols) > 10 else None),
                    'WinOdds': safe_float(clean_text(cols[11].get_text() if len(cols) > 11 else None))
                }
                results.append(horse_data)
            except Exception as e:
                logger.warning(f"Horse processing error in {course} R{race_num}: {e}")
                continue
        return results
    except Exception as e:
        logger.error(f"Race scraping error {course} R{race_num}: {e}")
        raise

import csv

def export_race_data_to_csv(all_runners, output_path):
    """Export race data to CSV using standardized headers."""
    if not all_runners:
        print("[WARN] No race data to export.")
        return

    headers = CONFIG['columns']

    try:
        with open(output_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in all_runners:
                writer.writerow(row)
        print(f"[✅] Race data exported to: {os.path.abspath(output_path)}")
    except Exception as e:
        print(f"[ERROR] Failed to write CSV: {e}")

def main():
    driver = initialize()
    all_data = []
    try:
        for date in [datetime(2025, 5, 4)]:  # Update dates if needed
            date_str = date.strftime('%Y/%m/%d')
            date_file_str = date.strftime('%Y_%m_%d')
            display_date = date.strftime('%d/%m/%y')  # NEW: for display/logs/DB/CSV
            for course in ['ST', 'HV']:
                for race_num in range(1, 12):
                    try:
                        if race_data := scrape_race(driver, date_str, course, race_num):
                            all_data.extend(race_data)
                            logger.info(f"✅ {display_date} {course} R{race_num}: {len(race_data)} runners")
                    except Exception as e:
                        logger.error(f"⚠️ Failed {course} R{race_num} after retries: {e}")
                        continue
        if all_data:
            df = pd.DataFrame(all_data)
            # Remove rows where finish_pos is empty or missing
            df = df[df['Placing'].notna() & (df['Placing'].astype(str).str.strip() != "")]
            for col in CONFIG['columns']:
                if col not in df.columns:
                    df[col] = None
            df.loc[df['Placing'] == 1, 'LBW'] = "0.01"
            # Ensure RaceDate is DD/MM/YY (TEXT)
            if 'RaceDate' in df.columns:
                df['RaceDate'] = df['RaceDate'].apply(parse_date).astype(str)
            df = df[CONFIG['columns']]
            csv_path = f"{CONFIG['output_dir']}/races_{date_file_str}.csv"
            df.to_csv(csv_path, index=False)
            logger.info(f"\n✅ Saved {len(df)} records to {csv_path}")
            print("Sample data:\n", df.head(3))
        else:
            logger.warning("⚠️ No data collected")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
