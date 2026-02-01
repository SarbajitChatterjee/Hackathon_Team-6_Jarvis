import pandas_datareader.data as web
from datetime import datetime
import pandas as pd

print("Checking Fama-French Data Availability...")
print("=" * 60)

try:
    # Try to fetch the most recent data
    end_date = datetime.now()
    start_date = datetime(2023, 1, 1)
    
    print(f"Attempting to fetch from {start_date.date()} to {end_date.date()}...")
    
    ff_factors = web.DataReader(
        'F-F_Research_Data_Factors', 
        'famafrench', 
        start_date, 
        end_date
    )[0]
    
    print(f"\n✅ Successfully fetched Fama-French factors!")
    print(f"Total months available: {len(ff_factors)}")
    print(f"\nDate range:")
    print(f"  First available: {ff_factors.index.min().to_timestamp()}")
    print(f"  Last available:  {ff_factors.index.max().to_timestamp()}")
    
    print(f"\nLast 5 months of data:")
    print(ff_factors.tail())
    
    # Check specific date
    your_data_end = pd.Timestamp("2024-03-01")
    ff_last_date = ff_factors.index.max().to_timestamp()
    
    print(f"\n📅 Your data ends on: {your_data_end.date()}")
    print(f"📅 FF data ends on:   {ff_last_date.date()}")
    
    if your_data_end > ff_last_date:
        months_diff = (your_data_end.year - ff_last_date.year) * 12 + (your_data_end.month - ff_last_date.month)
        print(f"⚠️  Your data extends {months_diff} months beyond available FF factors")
        print(f"   You can only use data up to {ff_last_date.date()}")
        print(f"   Solution: The updated code will automatically trim your data to this date")
    else:
        print(f"✅ FF factors are available for your entire data range")
    
except Exception as e:
    print(f"\n❌ Error fetching Fama-French data: {e}")
    import traceback
    traceback.print_exc()