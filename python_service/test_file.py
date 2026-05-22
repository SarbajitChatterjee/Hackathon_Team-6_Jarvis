from FFM_backtesting import run_backtest
import pandas as pd
import numpy as np

dates = pd.date_range('2023-01-01', periods=200, freq='B')
vals = np.sin(np.linspace(0,10,200))*5 + 100
df = pd.DataFrame({'Open':vals,'High':vals+1,'Low':vals-1,'Close':vals,'Volume':np.random.randint(100000,200000,200)}, index=dates)
print(run_backtest(df, fast_ma=10, slow_ma=30, initial_cash=10000.0))