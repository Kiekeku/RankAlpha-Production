#!/usr/bin/env python3
"""
Utility script to clean up the AI analysis schedule to ensure no duplicate dates per stock.
Run this script to remove any duplicate analysis dates that may have been created.
"""

import json
from pathlib import Path
from datetime import datetime

SCHEDULE_FILE = Path("/data/analysis_schedule/analysis_schedule.json")

def load_schedule():
    """Load the analysis schedule from JSON file."""
    if SCHEDULE_FILE.exists():
        try:
            with open(SCHEDULE_FILE, 'r') as f:
                data = json.load(f)
                # Convert date strings back to date objects
                for stock_key in data:
                    data[stock_key]['analysis_dates'] = [
                        datetime.strptime(date_str, '%Y-%m-%d').date() 
                        for date_str in data[stock_key]['analysis_dates']
                    ]
                return data
        except Exception as e:
            print(f"Error loading schedule: {e}")
            return {}
    return {}

def save_schedule(schedule):
    """Save the analysis schedule to JSON file, ensuring no duplicate dates per stock."""
    try:
        # Convert date objects to strings for JSON serialization
        data = {}
        for stock_key, info in schedule.items():
            # Ensure analysis_dates are unique by converting to set and back
            unique_dates = list(set(info['analysis_dates']))
            unique_dates.sort()
            
            data[stock_key] = {
                'company_name': info['company_name'],
                'symbol': info['symbol'],
                'analysis_dates': [
                    date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else date
                    for date in unique_dates
                ]
            }
        
        SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SCHEDULE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving schedule: {e}")

def clean_schedule():
    """Clean the schedule to ensure no duplicate dates per stock."""
    print(f"Loading schedule from {SCHEDULE_FILE}")
    schedule = load_schedule()
    
    if not schedule:
        print("No schedule found or schedule is empty")
        return
    
    total_removed = 0
    cleaned_stocks = []
    
    for stock_key, info in schedule.items():
        original_count = len(info['analysis_dates'])
        # Remove duplicates while preserving order
        unique_dates = []
        seen = set()
        for date in info['analysis_dates']:
            if date not in seen:
                unique_dates.append(date)
                seen.add(date)
        
        info['analysis_dates'] = unique_dates
        
        if original_count != len(unique_dates):
            removed = original_count - len(unique_dates)
            print(f"  - {info['symbol']} ({info['company_name']}): removed {removed} duplicate dates")
            total_removed += removed
            cleaned_stocks.append(info['symbol'])
    
    if total_removed > 0:
        save_schedule(schedule)
        print(f"\n✓ Schedule cleaned! Removed {total_removed} total duplicate dates across {len(cleaned_stocks)} stocks")
        print(f"  Affected stocks: {', '.join(cleaned_stocks)}")
    else:
        print("✓ Schedule is already clean - no duplicate dates found")
    
    # Print summary
    print(f"\nSchedule Summary:")
    for stock_key, info in schedule.items():
        if info['analysis_dates']:
            next_date = min(d for d in info['analysis_dates'] if d >= datetime.now().date()) if any(d >= datetime.now().date() for d in info['analysis_dates']) else None
            print(f"  - {info['symbol']}: {len(info['analysis_dates'])} scheduled dates" + 
                  (f" (next: {next_date})" if next_date else " (no future dates)"))
    
    return schedule

if __name__ == "__main__":
    print("AI Analysis Schedule Cleaner")
    print("=" * 40)
    clean_schedule()