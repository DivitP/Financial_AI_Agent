import os
import requests
import pandas as pd
import numpy as np
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import warnings
from typing import Dict, List, Tuple, Optional
import io
from sklearn.linear_model import LinearRegression
from dotenv import load_dotenv

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

load_dotenv()

warnings.filterwarnings('ignore')
plt.style.use('default')

class UltraFastTechnicalAnalysisAgent:
    """
    Ultra-optimized technical analysis agent using FMP API for maximum speed
    """
    
    def __init__(self, symbol: str, period: str = "1mo"):
        """
        Initialize the agent with a stock symbol
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'GOOGL')
            period: Time period for data (default 1mo for maximum speed)
        """
        self.symbol = symbol.upper()
        self.period = period
        self.data = None
        self.indicators = {}
        self.fmp_api_key = os.getenv("FMP_API_KEY")
        
        if not self.fmp_api_key:
            raise ValueError("FMP_API_KEY not found in environment variables")
            
        self.fetch_data()
        
    def fetch_data(self) -> pd.DataFrame:
        """Fetch stock data using FMP API with ultra-fast execution"""
        try:
            print(f"Fetching data for {self.symbol} using FMP API...")
            
            # Determine number of days based on period
            days_map = {
                "5d": 5,
                "1mo": 30,
                "2mo": 60,
                "3mo": 90
            }
            days = days_map.get(self.period, 30)
            
            # FMP historical price endpoint
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{self.symbol}"
            params = {
                "apikey": self.fmp_api_key,
                "timeseries": min(days, 30)  # Limit to 30 for speed
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                raise ValueError(f"FMP API error: {response.status_code}")
            
            data = response.json()
            
            if not data or 'historical' not in data or not data['historical']:
                raise ValueError(f"No historical data found for {self.symbol}")
            
            # Convert to DataFrame
            historical = data['historical']
            df = pd.DataFrame(historical)
            
            # Convert date column and set as index
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            
            # Rename columns to match yfinance format
            df = df.rename(columns={
                'open': 'Open',
                'high': 'High', 
                'low': 'Low',
                'close': 'Close',
                'volume': 'Volume'
            })
            
            # Select required columns
            self.data = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
            
            # Limit to 30 data points max for ultra-speed
            if len(self.data) > 30:
                self.data = self.data.tail(30)
                
            print(f"Fetched {len(self.data)} days of data for {self.symbol}")
            return self.data
            
        except Exception as e:
            print(f"Error fetching data for {self.symbol}: {str(e)}")
            raise
    
    def calculate_essential_indicators(self):
        """Calculate only the most essential indicators with vectorized operations"""
        print("Calculating essential indicators...")
        
        # Get close prices as numpy array for speed
        close_prices = self.data['Close'].values
        n = len(close_prices)
        
        if n < 5:
            print("Insufficient data for indicators")
            return
        
        # Simple Moving Averages (vectorized)
        sma_20_window = min(20, n)
        sma_50_window = min(50, n)
        
        # Use pandas rolling for consistency but with minimal windows
        self.indicators['SMA_20'] = self.data['Close'].rolling(window=sma_20_window, min_periods=1).mean()
        self.indicators['SMA_50'] = self.data['Close'].rolling(window=sma_50_window, min_periods=1).mean()
        
        # Ultra-fast RSI calculation with numpy
        rsi_window = min(14, n)
        if n > rsi_window:
            delta = np.diff(close_prices)
            
            # Vectorized gain/loss calculation
            gains = np.where(delta > 0, delta, 0)
            losses = np.where(delta < 0, -delta, 0)
            
            # Simple average instead of rolling for speed
            avg_gain = np.mean(gains[-rsi_window:])
            avg_loss = np.mean(losses[-rsi_window:])
            
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi_value = 100 - (100 / (1 + rs))
            else:
                rsi_value = 100 if avg_gain > 0 else 50
            
            # Create RSI series (simplified - just fill with calculated value)
            self.indicators['RSI'] = pd.Series([rsi_value] * n, index=self.data.index)
        else:
            self.indicators['RSI'] = pd.Series([50] * n, index=self.data.index)
        
        # Ultra-fast MACD (simplified)
        if n >= 12:
            # Simple EMAs using pandas for speed
            ema_12 = self.data['Close'].ewm(span=12, min_periods=1).mean()
            ema_26 = self.data['Close'].ewm(span=26, min_periods=1).mean()
            
            self.indicators['MACD'] = ema_12 - ema_26
            self.indicators['Signal'] = self.indicators['MACD'].ewm(span=9, min_periods=1).mean()
            self.indicators['Histogram'] = self.indicators['MACD'] - self.indicators['Signal']
        else:
            # Not enough data - create neutral indicators
            neutral_series = pd.Series([0] * n, index=self.data.index)
            self.indicators['MACD'] = neutral_series
            self.indicators['Signal'] = neutral_series
            self.indicators['Histogram'] = neutral_series
        
        # Volume indicator (simple average)
        vol_window = min(10, n)
        self.indicators['Volume_SMA'] = self.data['Volume'].rolling(window=vol_window, min_periods=1).mean()
        
        print("Indicators calculated successfully!")
            
    def generate_signals(self) -> Dict[str, str]:
        """Generate trading signals with ultra-fast execution"""
        signals = {}
        
        try:
            # RSI signals
            rsi_current = self.indicators['RSI'].iloc[-1]
            if pd.isna(rsi_current):
                signals['RSI'] = 'NEUTRAL - No data'
            elif rsi_current > 70:
                signals['RSI'] = 'SELL - Overbought'
            elif rsi_current < 30:
                signals['RSI'] = 'BUY - Oversold'
            else:
                signals['RSI'] = 'NEUTRAL'
        except:
            signals['RSI'] = 'ERROR'
        
        try:
            # MACD signals
            macd_current = self.indicators['MACD'].iloc[-1]
            signal_current = self.indicators['Signal'].iloc[-1]
            if pd.isna(macd_current) or pd.isna(signal_current):
                signals['MACD'] = 'NEUTRAL - No data'
            elif macd_current > signal_current:
                signals['MACD'] = 'BUY - Bullish'
            else:
                signals['MACD'] = 'SELL - Bearish'
        except:
            signals['MACD'] = 'ERROR'
        
        try:
            # Moving Average signals
            price_current = self.data['Close'].iloc[-1]
            sma_20 = self.indicators['SMA_20'].iloc[-1]
            sma_50 = self.indicators['SMA_50'].iloc[-1]
            
            if pd.isna(sma_20) or pd.isna(sma_50):
                signals['MA_Trend'] = 'NEUTRAL - No data'
            elif price_current > sma_20 > sma_50:
                signals['MA_Trend'] = 'BUY - Uptrend'
            elif price_current < sma_20 < sma_50:
                signals['MA_Trend'] = 'SELL - Downtrend'
            else:
                signals['MA_Trend'] = 'NEUTRAL'
        except:
            signals['MA_Trend'] = 'ERROR'
        
        return signals
    
    def simple_forecast(self, days: int = 10) -> Dict[str, float]:
        """Ultra-simple forecasting with minimal computation"""
        try:
            prices = self.data['Close'].dropna().values
            if len(prices) < 3:
                return {'trend': 'Unknown', 'confidence': 0.0, 'forecast_prices': [], 'days': days}
            
            # Use only numpy for speed
            X = np.arange(len(prices)).reshape(-1, 1)
            y = prices
            
            # Simple linear regression using numpy operations
            X_mean = np.mean(X)
            y_mean = np.mean(y)
            
            numerator = np.sum((X.flatten() - X_mean) * (y - y_mean))
            denominator = np.sum((X.flatten() - X_mean) ** 2)
            
            if denominator == 0:
                slope = 0
                intercept = y_mean
                r_squared = 0
            else:
                slope = numerator / denominator
                intercept = y_mean - slope * X_mean
                
                # Calculate R-squared
                y_pred = slope * X.flatten() + intercept
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = np.sum((y - y_mean) ** 2)
                r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            # Generate forecast
            future_X = np.arange(len(prices), len(prices) + days)
            future_prices = slope * future_X + intercept
            
            trend = "Bullish" if slope > 0 else "Bearish"
            confidence = max(0, min(1, r_squared))
            
            return {
                'forecast_prices': future_prices,
                'trend': trend,
                'confidence': confidence,
                'slope': slope,
                'days': days
            }
        except Exception as e:
            print(f"Forecast error: {e}")
            return {'trend': 'Unknown', 'confidence': 0.0, 'forecast_prices': [], 'days': days}
    
    def generate_fast_technical_chart(self, figsize: Tuple[int, int] = (10, 5)) -> bytes:
        """Generate ultra-minimal technical chart for maximum speed"""
        try:
            print("Generating technical chart...")
            fig, axes = plt.subplots(2, 1, figsize=figsize, height_ratios=[2, 1])
            fig.suptitle(f'{self.symbol} - Quick Analysis', fontsize=12)
            
            # Price and Moving Averages only
            ax1 = axes[0]
            ax1.plot(self.data.index, self.data['Close'], label='Close', linewidth=2, color='black')
            
            if 'SMA_20' in self.indicators:
                ax1.plot(self.data.index, self.indicators['SMA_20'], label='SMA 20', alpha=0.7, color='blue')
            
            ax1.set_title('Price & SMA 20')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # RSI only
            ax2 = axes[1]
            if 'RSI' in self.indicators:
                ax2.plot(self.data.index, self.indicators['RSI'], color='purple', linewidth=2)
                ax2.axhline(y=70, color='r', linestyle='--', alpha=0.5)
                ax2.axhline(y=30, color='g', linestyle='--', alpha=0.5)
                ax2.set_ylim(0, 100)
            ax2.set_title('RSI')
            ax2.grid(True, alpha=0.3)
            
            # Minimal date formatting
            for ax in axes:
                ax.tick_params(axis='x', rotation=45, labelsize=8)
            
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=50)  # Very low DPI
            plt.close(fig)
            buf.seek(0)
            print("Technical chart generated successfully!")
            return buf.getvalue()
            
        except Exception as e:
            print(f"Chart generation error: {e}")
            return b''
    
    def generate_fast_forecast_chart(self, forecast_data: Dict, figsize: Tuple[int, int] = (8, 4)) -> bytes:
        """Generate ultra-minimal forecast chart with fixed array comparison"""
        try:
            print("Generating forecast chart...")
            # Check if forecast_data exists and has forecast_prices
            forecast_prices = forecast_data.get('forecast_prices', [])
            
            # Convert to list/array and check length properly
            if forecast_prices is None:
                return b''
                
            # Convert to numpy array for consistent handling
            import numpy as np
            if not isinstance(forecast_prices, np.ndarray):
                forecast_prices = np.array(forecast_prices)
                
            # Check if we have any forecast data
            if len(forecast_prices) == 0:
                return b''
                
            fig, ax = plt.subplots(figsize=figsize)
            
            # Plot historical data
            ax.plot(self.data.index, self.data['Close'], label='Historical', color='blue', linewidth=2)
            
            # Plot forecast
            last_date = self.data.index[-1]
            forecast_dates = pd.date_range(start=last_date + timedelta(days=1), 
                                        periods=len(forecast_prices), freq='D')
            
            ax.plot(forecast_dates, forecast_prices, 
                    label=f'Forecast ({forecast_data.get("trend", "Unknown")})', 
                    color='red', linewidth=2, linestyle='--')
            
            ax.axvline(x=last_date, color='gray', linestyle=':', alpha=0.7)
            
            # Safe access to confidence with default
            confidence = forecast_data.get('confidence', 0.0)
            ax.set_title(f'{self.symbol} - Forecast (R² = {confidence:.2f})')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plt.xticks(rotation=45, fontsize=8)
            plt.tight_layout()
            
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=50)
            plt.close(fig)
            buf.seek(0)
            print("Forecast chart generated successfully!")
            return buf.getvalue()
            
        except Exception as e:
            print(f"Forecast chart error: {e}")
            return b''
    
    def get_analysis_summary(self) -> Dict:
        """Get analysis summary with ultra-fast execution"""
        try:
            signals = self.generate_signals()
        except Exception as e:
            print(f"Signal generation failed: {e}")
            signals = {'Error': 'Unable to generate signals'}
        
        try:
            forecast = self.simple_forecast(days=10)  # Reduced days for speed
        except Exception as e:
            print(f"Forecast failed: {e}")
            forecast = {'trend': 'Unknown', 'confidence': 0.0}
        
        # Basic price info with error handling
        try:
            current_price = float(self.data['Close'].iloc[-1])
        except:
            current_price = 0.0
            
        try:
            if len(self.data) > 1:
                price_change = float(self.data['Close'].iloc[-1] - self.data['Close'].iloc[-2])
                price_change_pct = (price_change / self.data['Close'].iloc[-2]) * 100 if self.data['Close'].iloc[-2] != 0 else 0.0
            else:
                price_change = 0.0
                price_change_pct = 0.0
        except:
            price_change = 0.0
            price_change_pct = 0.0
        
        try:
            avg_volume = float(self.data['Volume'].mean())
            current_volume = float(self.data['Volume'].iloc[-1])
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        except:
            volume_ratio = 1.0
        
        try:
            rsi_value = float(self.indicators.get('RSI', pd.Series([50.0])).iloc[-1])
        except:
            rsi_value = 50.0
        
        summary = {
            'symbol': self.symbol,
            'current_price': current_price,
            'daily_change': price_change,
            'daily_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'signals': signals,
            'forecast_trend': forecast.get('trend', 'Unknown'),
            'forecast_confidence': forecast.get('confidence', 0.0),
            'rsi': rsi_value,
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return summary

def run_ultra_fast_analysis(ticker: str) -> Dict:
    """Run ultra-fast analysis with comprehensive error handling"""
    try:
        print(f"Step 1: Starting ultra-fast analysis for {ticker}...")
        
        # Initialize agent
        agent = UltraFastTechnicalAnalysisAgent(ticker, period="1mo")
        print("Step 2: Agent initialized successfully")
        
        # Calculate indicators
        agent.calculate_essential_indicators()
        print("Step 3: Indicators calculated")
        
        # Get summary
        summary = agent.get_analysis_summary()
        print("Step 4: Summary generated")
        
        # Generate forecast
        forecast_data = agent.simple_forecast(days=10)
        print("Step 5: Forecast calculated")
        
        # Generate charts with detailed error handling
        tech_image = None
        forecast_image = None
        
        print("Step 6: Starting tech chart generation")
        try:
            tech_png = agent.generate_fast_technical_chart()
            if tech_png:
                import base64
                tech_image = base64.b64encode(tech_png).decode("utf-8")
                print("Step 7: Tech chart generated successfully")
            else:
                print("Step 7: Tech chart generation returned empty data")
        except Exception as e:
            print(f"Step 7 FAILED: Tech chart error: {e}")
        
        print("Step 8: Starting forecast chart generation")
        try:
            forecast_png = agent.generate_fast_forecast_chart(forecast_data)
            if forecast_png:
                import base64
                forecast_image = base64.b64encode(forecast_png).decode("utf-8")
                print("Step 9: Forecast chart generated successfully")
            else:
                print("Step 9: Forecast chart generation returned empty data")
        except Exception as e:
            print(f"Step 9 FAILED: Forecast chart error: {e}")
        
        print("Step 10: Creating text report")
        # Create text report
        lines = [
            f"ULTRA-FAST TECHNICAL ANALYSIS (FMP API) - {summary['symbol']}",
            f"Current Price: ${summary['current_price']:.2f}",
            f"Daily Change: ${summary['daily_change']:+.2f} ({summary['daily_change_pct']:+.2f}%)",
            f"Volume Ratio: {summary.get('volume_ratio', 1.0):.2f}x",
            f"RSI: {summary['rsi']:.1f}",
            "",
            "Trading Signals:",
        ]
        
        for k, v in summary["signals"].items():
            lines.append(f"- {k}: {v}")
        
        lines.extend([
            "",
            "Forecast:",
            f"- Trend: {summary['forecast_trend']}",
            f"- Confidence: {summary['forecast_confidence']:.1%}",
            f"Analysis Date: {summary['analysis_date']}"
        ])
        
        tech_text = "\n".join(lines)
        print("Step 11: Analysis completed successfully!")
        
        return {
            'text': tech_text,
            'tech_image': tech_image,
            'forecast_image': forecast_image,
            'status': 'success'
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"Ultra-fast analysis failed: {error_msg}")
        
        return {
            'text': f"Technical analysis failed for {ticker}: {error_msg}",
            'tech_image': None,
            'forecast_image': None,
            'status': 'error'
        }

if __name__ == "__main__":
    import time
    ticker = input("Enter ticker (e.g., AAPL): ").strip().upper() or "AAPL"
    
    start_time = time.time()
    result = run_ultra_fast_analysis(ticker)
    end_time = time.time()
    
    print(f"\n{result['text']}")
    print(f"\nTech Image: {bool(result.get('tech_image'))}")
    print(f"Forecast Image: {bool(result.get('forecast_image'))}")
    print(f"Execution time: {end_time - start_time:.2f} seconds")