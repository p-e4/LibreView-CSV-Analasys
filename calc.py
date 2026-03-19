# calc.py
"""
Contains functions for performing calculations on the data, such as calculating
bloodsugar to carb ratios, insulin sensitivity factors, and other relevant metrics
for diabetes management.
"""

# -- Imports --
import csv
from datetime import datetime, timedelta
import os
from glob import glob

# --------------------------------------------------
# --- Helper Functions ---
# --------------------------------------------------

def snap_to_hour(dt_obj) -> str:
    """
    Snap a datetime object to the nearest 2-hour window.
    """
    bins = [8, 10, 12, 14, 16, 18, 20, 22, 24]
    time_decimal = dt_obj.hour + (dt_obj.minute / 60.0)
    closest_hour = min(bins, key=lambda x: abs(x - time_decimal))
    return f"{closest_hour:02d}:00"


def find_closest(target_time, data_dict, tolerance_mins=20) -> tuple:
    """
    Find the closest timestamp in a dictionary to a target time within a tolerance.
    """
    if not data_dict:
        return None, None
    closest_time = min(data_dict.keys(), key=lambda x: abs(x - target_time))
    diff_mins = abs((closest_time - target_time).total_seconds() / 60)
    if diff_mins <= tolerance_mins:  
        return data_dict[closest_time], diff_mins
    return None, None

# --------------------------------------------------
# --- CSV Loader ---
# --------------------------------------------------

def find_csv_file() -> str:
    """
    Automatically detect a CSV file in the 'data' folder relative to this script file.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(script_dir, 'data')

    if not os.path.exists(data_folder):
        raise FileNotFoundError(f"No 'data' folder found at {data_folder}")

    csv_files = glob(os.path.join(data_folder, '*.csv'))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in folder '{data_folder}'")

    return csv_files[0]

# --------------------------------------------------
# --- Data Importer ---
# --------------------------------------------------

class DataImporter:
    """
    Handles importing CSV data into structured dictionaries.
    Tracks carbs, glucose, and insulin events.
    """

    def __init__(self, debug=True) -> None:
        self.debug = debug
        self.d_long_insulin = {}
        self.d_short_insulin = {}
        self.d_carbs = {}
        self.d_glucose_history = {}
        self.d_glucose_scan = {}

    def load_data(self, file_path) -> None:
        date_format = '%d-%m-%Y %H:%M'

        try:
            with open(file_path, mode='r', encoding='utf-8') as f:
                next(f)  # Skip metadata header
                reader = csv.DictReader(f)

                if self.debug:
                    print(f"Detected Columns: {reader.fieldnames}\n{'-'*30}")

                for row in reader:
                    raw_time = row['Device Timestamp']
                    if not raw_time:
                        continue
                    time_obj = datetime.strptime(raw_time, date_format)

                    if row['Long-Acting Insulin Value (units)']:
                        self.d_long_insulin[time_obj] = float(row['Long-Acting Insulin Value (units)'])
                    if row['Rapid-Acting Insulin (units)']:
                        self.d_short_insulin[time_obj] = float(row['Rapid-Acting Insulin (units)'])
                    if row['Carbohydrates (grams)']:
                        self.d_carbs[time_obj] = float(row['Carbohydrates (grams)'])
                    if row['Historic Glucose mmol/L']:
                        self.d_glucose_history[time_obj] = float(row['Historic Glucose mmol/L'])
                    if row['Scan Glucose mmol/L']:
                        self.d_glucose_scan[time_obj] = float(row['Scan Glucose mmol/L'])

            if self.debug:
                print(f"Imported {len(self.d_glucose_history)} history points and {len(self.d_carbs)} carb entries.")

        except FileNotFoundError:
            print(f"File not found: {file_path}")
        except Exception as e:
            print(f"Error loading CSV: {e}")

# --------------------------------------------------
# --- Analyzer ---
# --------------------------------------------------

class Analyzer:
    """
    Analyzes insulin, carb, and glucose data based on configurable settings.
    """

    def __init__(self, data_importer, debug=True, settings=None) -> None:
        self.debug = debug
        self.d_short_insulin = data_importer.d_short_insulin
        self.d_long_insulin = data_importer.d_long_insulin
        self.d_carbs = data_importer.d_carbs
        self.d_glucose_history = data_importer.d_glucose_history
        self.l_analyzed_events = []

        # Default settings mapped from the injected dictionary
        self.settings = settings or {}
        
        self.tolerance_mins = self.settings.get('tolerance_mins', 20)
        self.insulin_effect_time_hrs = self.settings.get('insulin_effect_time_hrs', 4)
        self.food_to_effect_time_mins = self.settings.get('food_to_effect_time_mins', 20)
        self.correction_wait_mins = self.settings.get('correction_wait_mins', 60)
        
        self.expected_1_unit_bs_down_by = self.settings.get('expected_1_unit_bs_down_by', 2)
        self.expected_10_carbs_bs_up_by = self.settings.get('expected_10_carbs_bs_up_by', 2) 

        self.clock_dividers = self.settings.get('clock_dividers', {
            8: 8, 10: 8, 12: 8, 14: 8, 16: 5, 18: 8, 20: 12, 22: 12, 24: 12
        })

    def analyze_insulin_effects(self) -> list:
        # Pull levers from class attributes
        insulin_effect_time = self.insulin_effect_time_hrs
        food_to_effect_time = self.food_to_effect_time_mins
        tolerance = self.tolerance_mins

        for ins_time in sorted(self.d_short_insulin.keys()):
            units = self.d_short_insulin[ins_time]
            meal_bin = snap_to_hour(ins_time)
            start_window = ins_time - timedelta(minutes=food_to_effect_time)
            end_window = ins_time + timedelta(hours=insulin_effect_time - (food_to_effect_time / 60))
            meal_time = None
            total_carbs = 0.0

            for c_time in sorted(self.d_carbs.keys()):
                if start_window <= c_time <= end_window:
                    if meal_time is None:
                        meal_time = c_time
                    total_carbs += self.d_carbs[c_time]

            wait_mins = (meal_time - ins_time).total_seconds() / 60 if meal_time else None
            is_correction = (total_carbs == 0) or (wait_mins is not None and wait_mins > self.correction_wait_mins)

            # Pass tolerance lever to find_closest
            bs_at_start, _ = find_closest(ins_time, self.d_glucose_history, tolerance_mins=tolerance)
            end_bs, _ = find_closest(ins_time + timedelta(hours=insulin_effect_time), self.d_glucose_history, tolerance_mins=tolerance)
            
            change = round(end_bs - bs_at_start, 1) if (bs_at_start is not None and end_bs is not None) else None

            entry = {
                "timestamp": ins_time.strftime('%Y-%m-%d %H:%M'),
                "meal_window": meal_bin,
                "type": "Correction" if is_correction else "Meal",
                "units": units,
                "carbs": total_carbs,
                "bs_at_start": bs_at_start,
                "end_bs": end_bs,
                "change": change
            }

            self.l_analyzed_events.append(entry)

        return self.l_analyzed_events