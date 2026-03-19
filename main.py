# main.py
"""
Used for launching other scripts in the project, such as the future GUI or the data analysis scripts.
"""

# Import the necessary classes and functions from your calc.py file
from calc import find_csv_file, DataImporter, Analyzer

# ------- Settings / Levers -------
# These are the settings you can tweak to adjust how the analyzer works.

debug = True  # Set to False to reduce console output
calc_settings = {
    'tolerance_mins': 20,              # How many mins off a timestamp can be
    'insulin_effect_time_hrs': 4,      # How long insulin stays active
    'food_to_effect_time_mins': 20,    # Gap between food and insulin effect
    'correction_wait_mins': 60,        # Mins after food to consider a dose a "correction"
    'expected_1_unit_bs_down_by': 2,
    'expected_10_carbs_bs_up_by': 2,
    'clock_dividers': {                # Time of day (hour) to divider for insulin effect calculation
        8: 8, 10: 8, 12: 8, 14: 8, 
        16: 5, 18: 8, 20: 12, 22: 12, 24: 12
    }
}


def main() -> None:
    """
    Main entry point for running CSV import and insulin analysis.
    Controls the settings/levers passed into the Analyzer.
    """
    try:
        csv_file = find_csv_file()
        print(f"Loading CSV file: {csv_file}")

        importer = DataImporter(debug)
        importer.load_data(csv_file)

        

        # Pass your settings dict directly into the analyzer
        analyzer = Analyzer(importer, debug, settings=calc_settings)
        results = analyzer.analyze_insulin_effects()

        # NOTE: TEMPLATE: REWORK THE MATH, Currently not functinoal
        #analyzer.calculate_ideal_ratios() 

        window_averages = analyzer.get_window_averages(results)

        print(f"\nAnalyzed {len(results)} insulin events:")
        for r in results[:5]:  # show first 5 for brevity
            print(r)

        print("\n--- Averages & Predictions by Window ---")
        header = (
    f"{'Window':<8} | {'Events':<6} | {'Current Div':<12} | "
    f"{'Predicted Div':<14} | "
    f"Avg Change (after {calc_settings['insulin_effect_time_hrs']} hrs)"
)
        print(header)
        print("-" * len(header))
        
        for window, data in window_averages.items():
            print(f"{window:<8} | {data['event_count']:<6} | {data['active_divider']:<12} | {data['predicted_divider']:<14} | {data['avg_change']}")


        # -----------------------------
        # TODO / Notes 
        # -----------------------------
        # ⬜ Another function to find median bs per week sorted by hour of the day
        # ⬜ This should also have highest and lowest
        # 🟨 Calculate new numbers based on meal_window
        # ⬜ Discount insulin if <3h between events or combine calculations
        # 🟨 Check carbs eaten without insulin <45 min earlier
        # ✅ Count all snack-carbs after insulin as well
        # ⬜ Sort avg bloodsugar based on time taken between insulin and meal
        # ✅ Check insulin X time AFTER meal; also pre-meal intake

    except Exception as e:
        print(f"Error in main: {e}")

if __name__ == "__main__":
    main()