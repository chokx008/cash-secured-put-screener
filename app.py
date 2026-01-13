import streamlit as st
import yfinance as yf
import pandas as pd

from datetime import datetime, timedelta

def get_stock_data(ticker_symbol):
    """
    Fetches current price, RSI, Next Earnings Date, 50MA, and 52-Week Range.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Fetch 1 year of data for 52-week range
        history = ticker.history(period="1y")
        
        if history.empty:
            return None, None, None, None, None, None
            
        current_price = history['Close'].iloc[-1]
        
        # RSI Calculation (14-day)
        delta = history['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        
        # Handle division by zero
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]

        # 50-Day Moving Average
        ma_50 = history['Close'].rolling(window=50).mean().iloc[-1]
        
        # 52-Week High/Low
        high_52w = history['Close'].max()
        low_52w = history['Close'].min()

        # Fetch Next Earnings Date
        next_earnings = None
        try:
            cal = ticker.calendar
            if cal and 'Earnings Date' in cal:
                dates = cal['Earnings Date']
                if dates:
                    next_earnings = dates[0]
            elif hasattr(cal, 'iloc'): 
                 pass
        except Exception:
            pass 
        
        return current_price, current_rsi, next_earnings, ma_50, high_52w, low_52w
        
    except Exception as e:
        st.error(f"Error fetching data for {ticker_symbol}: {e}")
        return None, None, None, None, None, None

def get_option_chain(ticker_symbol, target_date=None):
    """
    Fetches the put option chain for a specific expiry date.
    If target_date is None, fetches the next available expiry.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        expirations = ticker.options
        
        if not expirations:
            return None, None
            
        # Ensure we look for future dates just in case
        valid_dates = []
        today = datetime.now()
        
        for date_str in expirations:
            exp_date = datetime.strptime(date_str, "%Y-%m-%d")
            if exp_date > today:
                valid_dates.append(date_str)
                
        if not valid_dates:
            return None, None
            
        # Select expiry
        if target_date:
            if target_date in valid_dates:
                selected_date = target_date
            else:
                # Target date not available for this ticker
                return None, None
        else:
            # Default to next available
            selected_date = valid_dates[0]
        
        chain = ticker.option_chain(selected_date)
        puts = chain.puts
        return puts, selected_date
        
    except Exception as e:
        st.error(f"Error fetching options for {ticker_symbol}: {e}")
        return None, None

def calculate_metrics(row, current_price, days_to_expiry):
    """
    Calculates Annualized Return and Downside Cushion.
    """
    strike = row['strike']
    bid = row['bid']
    
    # Basic validation
    if strike <= 0 or current_price <= 0:
        return None
        
    # Annualized Return Calculation
    # Formula: ((Bid / Strike) * (365 / DTE)) * 100
    if days_to_expiry <= 0:
        days_to_expiry = 1 # Avoid division by zero, treat as 1 day left
        
    raw_return = bid / strike
    annualized_return = raw_return * (365 / days_to_expiry) * 100
    
    # Downside Cushion
    # Formula: (Current - Strike) / Current
    downside_cushion = (current_price - strike) / current_price * 100
    
    return annualized_return, downside_cushion

def main():
    st.set_page_config(page_title="Cash Secured Put Screener", layout="wide")
    st.title("Cash Secured Put Screener 📉")

    st.sidebar.header("Settings")
    tickers_input = st.sidebar.text_input("Enter Tickers (comma separated)", "GOOG, AMZN, TSLA, AAPL, MSFT")
    target_return = st.sidebar.number_input("Target Annualized Return %", min_value=0.0, value=19.0, step=0.1)

 

    # --- Refactored Main Flow for UI ---
    
    ticker_list = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    
    # State management for expirations
    if 'expiry_dates' not in st.session_state:
        st.session_state['expiry_dates'] = []
    
    if st.sidebar.button("Fetch Expirations (from first ticker)"):
        if ticker_list:
            try:
                ft = yf.Ticker(ticker_list[0])
                opts = ft.options
                # Filter future
                st.session_state['expiry_dates'] = [d for d in opts if datetime.strptime(d, "%Y-%m-%d") > datetime.now()]
                if not st.session_state['expiry_dates']:
                    st.warning("No future expirations found.")
            except Exception as e:
                st.error(f"Error fetching expirations: {e}")
        else:
            st.warning("Please enter a ticker first.")
            
    selected_expiry = None
    if st.session_state['expiry_dates']:
        selected_expiry = st.sidebar.selectbox("Select Expiry Date", st.session_state['expiry_dates'])

    if st.sidebar.button("Screen Options"):
        results = []
        
        if not ticker_list:
            st.error("Please enter at least one ticker.")
            return

        status_text = st.empty()
        progress_bar = st.progress(0)
        
        for i, ticker in enumerate(ticker_list):
            status_text.text(f"Processing {ticker}...")
            
            # 1. Get Stock Data
            current_price, rsi, next_earnings, ma_50, high_52w, low_52w = get_stock_data(ticker)
            if not current_price:
                st.warning(f"Could not fetch data for {ticker}")
                progress_bar.progress((i + 1) / len(ticker_list))
                continue
                
            # 2. Get Option Chain (Pass selected_expiry)
            puts, expiry_date = get_option_chain(ticker, target_date=selected_expiry)
            
            # Logic: If specific date requested but not found, get_option_chain returns None
            if puts is None or puts.empty:
                if selected_expiry: 
                    st.warning(f"No options found for {ticker} on {selected_expiry}")
                else:
                    st.warning(f"No option chain found for {ticker}")
                progress_bar.progress((i + 1) / len(ticker_list))
                continue
                
            # 3. Filter OTM Puts
            puts = puts[puts['strike'] < current_price]
            if puts.empty:
                st.warning(f"No OTM puts found for {ticker}")
                progress_bar.progress((i + 1) / len(ticker_list))
                continue
                
            # 4. Calculate Metrics
            expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
            days_to_expiry = (expiry_dt - datetime.now()).days
            
            metrics = puts.apply(lambda row: calculate_metrics(row, current_price, days_to_expiry), axis=1, result_type='expand')
            
            if metrics.empty:
                continue

            metrics.columns = ['annualized_return', 'downside_cushion']
            puts = pd.concat([puts, metrics], axis=1)
            
            # 5. Selection Logic: Safest strike that meets Target Return
            # "Safest" means lowest return (furthest OTM) that is still >= Target.
            # If nothing meets Target, pick the Highest return available (closest we can get).
            
            candidates = puts[puts['annualized_return'] >= target_return]
            
            if not candidates.empty:
                # Pick the one with the lowest return in this group (Safest/Furthest OTM)
                best_idx = candidates['annualized_return'].idxmin()
            else:
                # No options meet the target. Pick the one with the highest return (closest to target)
                best_idx = puts['annualized_return'].idxmax()
                
            best_put = puts.loc[best_idx]
            
            # --- Extract New Metrics ---
            iv_raw = best_put.get('impliedVolatility', 0)
            iv_display = f"{iv_raw * 100:.1f}%" if iv_raw else "N/A"
            
            vol = int(best_put.get('volume', 0)) if not pd.isna(best_put.get('volume')) else 0
            oi = int(best_put.get('openInterest', 0)) if not pd.isna(best_put.get('openInterest')) else 0
            liquidity_display = f"Vol: {vol} / OI: {oi}"
            
            # Trend Calculation
            if ma_50:
                trend_pct = (current_price - ma_50) / ma_50 * 100
                trend_display = f"{'+' if trend_pct > 0 else ''}{trend_pct:.1f}%"
            else:
                trend_display = "N/A"

            # Earnings Risk Check
            earnings_display = "N/A"
            if next_earnings:
                 if isinstance(next_earnings, datetime):
                     ne_date = next_earnings.date()
                 elif hasattr(next_earnings, 'date'):
                     ne_date = next_earnings.date()
                 else:
                     ne_date = next_earnings 
                 
                 exp_date_obj = expiry_dt.date()
                 date_str = ne_date.strftime("%b %d")
                 
                 if ne_date <= exp_date_obj:
                     earnings_display = f"⚠️ {date_str}"
                 else:
                     earnings_display = date_str
            
            results.append({
                "Ticker": ticker,
                "Current Price": round(current_price, 2),
                "Strike Price": best_put['strike'],
                "Premium": best_put['bid'],
                "Expiry Date": expiry_date,
                "IV": iv_display,
                "Liquidity": liquidity_display,
                "Next Earnings": earnings_display,
                "Trend vs 50MA": trend_display,
                "52W High": round(high_52w, 2) if high_52w else None,
                "52W Low": round(low_52w, 2) if low_52w else None,
                "Downside Cushion %": round(best_put['downside_cushion'], 2),
                "Annualized Return %": round(best_put['annualized_return'], 2),
                "RSI (14)": round(rsi, 2) if rsi is not None else None
            })
            
            progress_bar.progress((i + 1) / len(ticker_list))
            
        status_text.text("Screening Complete!")
        
        if results:
            df = pd.DataFrame(results)
            
            # --- Sorting Logic ---
            try:
                df = df.sort_values(by=["Annualized Return %", "RSI (14)"], ascending=[False, True])
            except Exception as e:
                st.warning(f"Could not sort results: {e}")

            st.success(f"Found {len(results)} potential trades.")
            
            # Style the DataFrame
            # Column Order
            cols_order = [
                "Ticker", "Strike Price", "Premium", "52W Low", "Current Price", 
                "52W High", "IV", "Liquidity", "Trend vs 50MA", 
                "Downside Cushion %", "Annualized Return %", "RSI (14)"
            ]
            
            # Filter/Reorder df
            # Ensure all columns exist to avoid KeyErrors
            final_df = df[cols_order].copy()

            # Function to color Trend column
            def color_trend(val):
                if isinstance(val, str):
                    if val.startswith('+'):
                        return 'color: green'
                    elif val.startswith('-'):
                        return 'color: red'
                return ''

            # Apply Styles
            # 1. Map Trend Colors
            # 2. Set text-align center for all cells
            # 3. Format numbers
            st.dataframe(
                final_df.style
                .map(color_trend, subset=['Trend vs 50MA'])
                .set_properties(**{'text-align': 'center', 'vertical-align': 'middle'})
                .set_table_styles([
                    dict(selector='th', props=[('text-align', 'center'), ('vertical-align', 'middle')]),
                    dict(selector='td', props=[('text-align', 'center'), ('vertical-align', 'middle')])
                ])
                .format({
                    "Current Price": "${:.2f}",
                    "Strike Price": "${:.2f}",
                    "Premium": "${:.2f}",
                    "52W High": "${:.2f}",
                    "52W Low": "${:.2f}",
                    "Annualized Return %": "{:.2f}%",
                    "Downside Cushion %": "{:.2f}%",
                    "RSI (14)": "{:.2f}"
                })
            )
        else:
            st.warning("No options found matching criteria.")

if __name__ == "__main__":
    main()
