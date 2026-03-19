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

    # --------------------------------------------------
    # --- Analasys Helper Functions ---
    # --------------------------------------------------
    def _get_carbs_in_window(self, ins_time):
        """Finds first meal time and total carbs within the effect window."""
        start_window = ins_time - timedelta(minutes=self.tolerance_mins)
        end_window = ins_time + timedelta(hours=self.insulin_effect_time_hrs)
        
        meal_time = None
        total_carbs = 0.0

        for c_time in sorted(self.d_carbs.keys()):
            if start_window <= c_time <= end_window:
                if meal_time is None:
                    meal_time = c_time
                total_carbs += self.d_carbs[c_time]
        
        return meal_time, total_carbs

    def _get_glucose_metrics(self, start_ref_time):
        """Calculates start BS, end BS, and the total change."""
        bs_at_start, _ = find_closest(start_ref_time, self.d_glucose_history, self.tolerance_mins)
        
        end_ref_time = start_ref_time + timedelta(hours=self.insulin_effect_time_hrs)
        end_bs, _ = find_closest(end_ref_time, self.d_glucose_history, self.tolerance_mins)
        
        change = round(end_bs - bs_at_start, 1) if (bs_at_start is not None and end_bs is not None) else None
        return bs_at_start, end_bs, change

    # --------------------------------------------------
    # --- Core Analaysis Functions ----
    # --------------------------------------------------
    def analyze_insulin_effects(self) -> list:
        """Main loop to process all short-acting insulin events."""
        for ins_time in sorted(self.d_short_insulin.keys()):
            # 1. Gather Data Points
            units = self.d_short_insulin[ins_time]
            meal_bin = snap_to_hour(ins_time)
            meal_time, total_carbs = self._get_carbs_in_window(ins_time)

            # 2. Determine Start Reference (Shift if food was taken before insulin)
            start_ref_time = meal_time if (meal_time and meal_time < ins_time) else ins_time
            
            # 3. Calculate Glucose Change
            bs_start, bs_end, change = self._get_glucose_metrics(start_ref_time)

            # 4. Determine Event Type
            wait_mins = (meal_time - ins_time).total_seconds() / 60 if meal_time else None
            is_correction = (total_carbs == 0) or (wait_mins is not None and wait_mins > self.correction_wait_mins)

            # 5. Get Active Divider
            hour_key = int(meal_bin.split(':')[0])
            current_divider = self.clock_dividers.get(hour_key, 10)

            # 6. Build Entry
            self.l_analyzed_events.append({
                "timestamp": ins_time.strftime('%Y-%m-%d %H:%M'),
                "event_start": start_ref_time.strftime('%H:%M'),
                "meal_window": meal_bin,
                "type": "Correction" if is_correction else "Meal",
                "units": units,
                "carbs": total_carbs,
                "divider_used": current_divider,
                "bs_at_start": bs_start,
                "end_bs": bs_end,
                "change": change
            })

        return self.l_analyzed_events
    

    def get_window_averages(self, analyzed_events) -> dict:
        if not analyzed_events:
            analyzed_events = self.l_analyzed_events

        stats = {}
        for event in self.l_analyzed_events:
            window = event['meal_window']
            if window not in stats:
                stats[window] = {"units": [], "carbs": [], "change": [], "predicted_div": [], "count": 0}
            
            if event['units'] is not None: stats[window]["units"].append(event['units'])
            if event['carbs'] is not None: stats[window]["carbs"].append(event['carbs'])
            if event['change'] is not None: stats[window]["change"].append(event['change'])
            # Only add predicted dividers that are valid numbers
            if event.get('predicted_divider'): stats[window]["predicted_div"].append(event['predicted_divider'])
            
            stats[window]["count"] += 1

        averages = {}
        for window in sorted(stats.keys()):
            w_data = stats[window]
            hour_key = int(window.split(':')[0])
            
            averages[window] = {
                "avg_change": round(sum(w_data["change"]) / len(w_data["change"]), 1) if w_data["change"] else 0,
                "active_divider": self.clock_dividers.get(hour_key, "N/A"),
                "predicted_divider": round(sum(w_data["predicted_div"]) / len(w_data["predicted_div"]), 1) if w_data["predicted_div"] else "N/A",
                "event_count": w_data["count"]
            }
        return averages

    def calculate_ideal_ratios(self) -> list:
        """
        Analyzes the results to predict what the insulin dose and 
        carb divider should have been to result in 0 blood sugar change.
        """
        # Pull levers
        sens = self.expected_1_unit_bs_down_by 

        for event in self.l_analyzed_events:
            # We can only calculate this if we have a valid BS change and carbs
            if event['change'] is None or event['carbs'] == 0:
                event['ideal_units'] = None
                event['predicted_divider'] = None
                continue

            # 1. How many units were 'wrong'? 
            # If BS went up by 4 and 1 unit drops it by 2, you were 'under' by 2 units.
            unit_error = event['change'] / sens
            
            # 2. What would the perfect dose have been?
            ideal_units = event['units'] + unit_error
            event['ideal_units'] = round(ideal_units, 2)

            # 3. What divider would have resulted in that perfect dose?
            # Ratio = Carbs / Units
            if ideal_units > 0:
                predicted_divider = event['carbs'] / ideal_units
                event['predicted_divider'] = round(predicted_divider, 1)
            else:
                event['predicted_divider'] = 0 # Insulin was effectively useless or BS dropped regardless

        return self.l_analyzed_events