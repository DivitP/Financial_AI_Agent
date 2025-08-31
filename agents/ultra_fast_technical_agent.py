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
import base64

# Try to import ARIMA and GARCH, fallback if not available
try:
    from statsmodels.tsa.arima.model import ARIMA
    ARIMA_AVAILABLE = True
except ImportError:
    ARIMA_AVAILABLE = False
    print("ARIMA not available - install statsmodels")

try:
    from arch import arch_model
    GARCH_AVAILABLE = True
except ImportError:
    GARCH_AVAILABLE = False
    print("GARCH not available - install arch")

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
    
    def __init__(self, symbol: str, period: str = "2mo"):
        """
        Initialize the agent with a stock symbol
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'GOOGL')
            period: Time period for data (default 2mo for better models)
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
            days = days_map.get(self.period, 60)
            
            # FMP historical price endpoint
            url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{self.symbol}"
            params = {
                "apikey": self.fmp_api_key,
                "timeseries": days
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
            
            print(f"Fetched {len(self.data)} days of data for {self.symbol}")
            return self.data
            
        except Exception as e:
            print(f"Error fetching data for {self.symbol}: {str(e)}")
            raise
    
    def calculate_essential_indicators(self):
        """Calculate essential indicators including Bollinger Bands"""
        print("Calculating essential indicators...")
        
        # Get close prices as numpy array for speed
        close_prices = self.data['Close'].values
        n = len(close_prices)
        
        if n < 5:
            print("Insufficient data for indicators")
            return
        
        # Simple Moving Averages
        sma_20_window = min(20, n)
        sma_50_window = min(50, n)
        
        self.indicators['SMA_20'] = self.data['Close'].rolling(window=sma_20_window, min_periods=1).mean()
        self.indicators['SMA_50'] = self.data['Close'].rolling(window=sma_50_window, min_periods=1).mean()
        
        # Bollinger Bands (enhanced calculation)
        bb_window = min(20, n)
        if n >= bb_window:
            rolling_mean = self.data['Close'].rolling(window=bb_window).mean()
            rolling_std = self.data['Close'].rolling(window=bb_window).std()
            self.indicators['Bollinger_Middle'] = rolling_mean
            self.indicators['Bollinger_Upper'] = rolling_mean + (rolling_std * 2)
            self.indicators['Bollinger_Lower'] = rolling_mean - (rolling_std * 2)
            
            # Bollinger Band position indicator (0 = lower band, 1 = upper band)
            self.indicators['BB_Position'] = (self.data['Close'] - self.indicators['Bollinger_Lower']) / (self.indicators['Bollinger_Upper'] - self.indicators['Bollinger_Lower'])
        else:
            # Default Bollinger Bands for insufficient data
            self.indicators['Bollinger_Middle'] = self.data['Close']
            self.indicators['Bollinger_Upper'] = self.data['Close'] * 1.02
            self.indicators['Bollinger_Lower'] = self.data['Close'] * 0.98
            self.indicators['BB_Position'] = pd.Series([0.5] * n, index=self.data.index)

        # Ultra-fast RSI calculation
        rsi_window = min(14, n)
        if n > rsi_window:
            delta = np.diff(close_prices)
            gains = np.where(delta > 0, delta, 0)
            losses = np.where(delta < 0, -delta, 0)
            
            avg_gain = np.mean(gains[-rsi_window:])
            avg_loss = np.mean(losses[-rsi_window:])
            
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi_value = 100 - (100 / (1 + rs))
            else:
                rsi_value = 100 if avg_gain > 0 else 50
            
            self.indicators['RSI'] = pd.Series([rsi_value] * n, index=self.data.index)
        else:
            self.indicators['RSI'] = pd.Series([50] * n, index=self.data.index)
        
        # MACD calculation
        if n >= 12:
            ema_12 = self.data['Close'].ewm(span=12, min_periods=1).mean()
            ema_26 = self.data['Close'].ewm(span=26, min_periods=1).mean()
            
            self.indicators['MACD'] = ema_12 - ema_26
            self.indicators['Signal'] = self.indicators['MACD'].ewm(span=9, min_periods=1).mean()
            self.indicators['Histogram'] = self.indicators['MACD'] - self.indicators['Signal']
        else:
            neutral_series = pd.Series([0] * n, index=self.data.index)
            self.indicators['MACD'] = neutral_series
            self.indicators['Signal'] = neutral_series
            self.indicators['Histogram'] = neutral_series
        
        # Volume indicator
        vol_window = min(10, n)
        self.indicators['Volume_SMA'] = self.data['Volume'].rolling(window=vol_window, min_periods=1).mean()
        
        print("Indicators calculated successfully!")

    def generate_signals(self) -> Dict[str, str]:
        """Generate trading signals"""
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
        
        try:
            # Bollinger Bands signals
            bb_position = self.indicators['BB_Position'].iloc[-1]
            if pd.isna(bb_position):
                signals['Bollinger'] = 'NEUTRAL - No data'
            elif bb_position > 0.8:
                signals['Bollinger'] = 'SELL - Near upper band'
            elif bb_position < 0.2:
                signals['Bollinger'] = 'BUY - Near lower band'
            else:
                signals['Bollinger'] = 'NEUTRAL - Middle range'
        except:
            signals['Bollinger'] = 'ERROR'
        
        return signals

    def enhanced_arima_forecast(self, days: int = 10) -> Dict:
        """Enhanced ARIMA forecasting with confidence intervals"""
        if not ARIMA_AVAILABLE:
            return self.simple_forecast(days)
            
        try:
            prices = self.data['Close'].dropna()
            if len(prices) < 30:
                return self.simple_forecast(days)

            # Fit ARIMA model
            model = ARIMA(prices, order=(1, 1, 1))
            model_fit = model.fit()

            # Forecast with confidence intervals
            forecast_result = model_fit.get_forecast(steps=days)
            forecast_prices = forecast_result.predicted_mean.values
            confidence_intervals = forecast_result.conf_int()
            
            # Determine trend
            trend = "Bullish" if forecast_prices[-1] > prices.iloc[-1] else "Bearish"
            
            # Calculate confidence
            confidence = max(0.1, min(0.95, 1.0 / (1.0 + np.std(forecast_prices))))

            return {
                'forecast_prices': forecast_prices.tolist(),
                'confidence_lower': confidence_intervals.iloc[:, 0].values.tolist(),
                'confidence_upper': confidence_intervals.iloc[:, 1].values.tolist(),
                'trend': trend,
                'confidence': confidence,
                'days': days,
                'model_aic': float(model_fit.aic)
            }
        except Exception as e:
            print(f"ARIMA forecast error: {e}")
            return self.simple_forecast(days)

    def enhanced_garch_forecast(self, days: int = 10) -> Dict:
        """Enhanced GARCH volatility forecasting"""
        if not GARCH_AVAILABLE:
            return {'forecast_volatility': [], 'days': days}
            
        try:
            # Calculate returns for volatility analysis
            returns = 100 * self.data['Close'].pct_change().dropna()
            if len(returns) < 30:
                return {'forecast_volatility': [], 'days': days}

            # Fit GARCH(1,1) model
            model = arch_model(returns, vol='Garch', p=1, q=1)
            model_fit = model.fit(disp='off')
            
            # Forecast future volatility
            forecast_result = model_fit.forecast(horizon=days)
            forecast_variance = forecast_result.variance.iloc[-1].values
            forecast_volatility = np.sqrt(forecast_variance).tolist()
            
            # Calculate current volatility for comparison
            current_volatility = returns.rolling(window=20).std().iloc[-1]

            return {
                'forecast_volatility': forecast_volatility,
                'current_volatility': float(current_volatility),
                'avg_volatility': float(returns.std()),
                'days': days,
                'model_loglikelihood': float(model_fit.loglikelihood)
            }
        except Exception as e:
            print(f"GARCH forecast error: {e}")
            return {'forecast_volatility': [], 'days': days}

    def simple_forecast(self, days: int = 10) -> Dict:
        """Simple linear regression forecast (fallback)"""
        try:
            prices = self.data['Close'].dropna().values
            if len(prices) < 3:
                return {'trend': 'Unknown', 'confidence': 0.0, 'forecast_prices': [], 'days': days}
            
            X = np.arange(len(prices)).reshape(-1, 1)
            y = prices
            
            # Simple linear regression
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
                'forecast_prices': future_prices.tolist(),
                'trend': trend,
                'confidence': confidence,
                'days': days
            }
        except Exception as e:
            print(f"Simple forecast error: {e}")
            return {'trend': 'Unknown', 'confidence': 0.0, 'forecast_prices': [], 'days': days}

    def generate_fast_technical_chart(self, figsize: Tuple[int, int] = (12, 8)) -> bytes:
        """Generate comprehensive technical indicators chart"""
        try:
            print("Generating technical indicators chart...")
            fig, axes = plt.subplots(3, 1, figsize=figsize, height_ratios=[3, 1, 1])
            fig.suptitle(f'{self.symbol} - Technical Indicators Overview', fontsize=14)
            
            # Price and Moving Averages
            ax1 = axes[0]
            ax1.plot(self.data.index, self.data['Close'], label='Close Price', linewidth=2, color='black')
            
            if 'SMA_20' in self.indicators:
                ax1.plot(self.data.index, self.indicators['SMA_20'], 
                        label='SMA 20', alpha=0.8, color='blue', linewidth=1.5)
            if 'SMA_50' in self.indicators:
                ax1.plot(self.data.index, self.indicators['SMA_50'], 
                        label='SMA 50', alpha=0.8, color='orange', linewidth=1.5)
            
            ax1.set_title('Price with Moving Averages')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # RSI
            ax2 = axes[1]
            if 'RSI' in self.indicators:
                ax2.plot(self.data.index, self.indicators['RSI'], color='purple', linewidth=2)
                ax2.axhline(y=70, color='r', linestyle='--', alpha=0.7, label='Overbought')
                ax2.axhline(y=30, color='g', linestyle='--', alpha=0.7, label='Oversold')
                ax2.axhline(y=50, color='gray', linestyle=':', alpha=0.5)
                ax2.set_ylim(0, 100)
                ax2.legend(loc='upper right')
            ax2.set_title('RSI (14-period)')
            ax2.grid(True, alpha=0.3)
            
            # MACD
            ax3 = axes[2]
            if 'MACD' in self.indicators:
                ax3.plot(self.data.index, self.indicators['MACD'], 
                        label='MACD', color='blue', linewidth=2)
                ax3.plot(self.data.index, self.indicators['Signal'], 
                        label='Signal', color='red', linewidth=1.5)
                ax3.bar(self.data.index, self.indicators['Histogram'], 
                       label='Histogram', alpha=0.6, color='gray')
                ax3.axhline(y=0, color='black', linewidth=0.5)
                ax3.legend(loc='upper right')
            ax3.set_title('MACD')
            ax3.grid(True, alpha=0.3)
            
            # Format dates
            for ax in axes:
                ax.tick_params(axis='x', rotation=45, labelsize=9)
            
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
            plt.close(fig)
            buf.seek(0)
            print("Technical indicators chart generated successfully!")
            return buf.getvalue()
            
        except Exception as e:
            print(f"Technical chart generation error: {e}")
            return b''

    def generate_bollinger_chart(self, figsize: Tuple[int, int] = (12, 6)) -> bytes:
        """Generate dedicated Bollinger Bands chart"""
        try:
            print("Generating Bollinger Bands chart...")
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, height_ratios=[3, 1])
            fig.suptitle(f'{self.symbol} - Bollinger Bands Analysis', fontsize=14)
            
            # Main price chart with Bollinger Bands
            ax1.plot(self.data.index, self.data['Close'], label='Close Price', linewidth=2, color='black')
            
            if 'Bollinger_Middle' in self.indicators:
                ax1.plot(self.data.index, self.indicators['Bollinger_Middle'], 
                        label='BB Middle (20 SMA)', color='blue', linewidth=1.5)
                ax1.plot(self.data.index, self.indicators['Bollinger_Upper'], 
                        label='BB Upper (+2σ)', color='red', linewidth=1, alpha=0.8)
                ax1.plot(self.data.index, self.indicators['Bollinger_Lower'], 
                        label='BB Lower (-2σ)', color='green', linewidth=1, alpha=0.8)
                
                # Fill between bands for visual clarity
                ax1.fill_between(self.data.index, 
                               self.indicators['Bollinger_Upper'], 
                               self.indicators['Bollinger_Lower'], 
                               alpha=0.1, color='gray')
            
            ax1.set_title('Price with Bollinger Bands')
            ax1.legend(loc='upper left')
            ax1.grid(True, alpha=0.3)
            
            # Bollinger Band position indicator
            if 'BB_Position' in self.indicators:
                ax2.plot(self.data.index, self.indicators['BB_Position'], 
                        color='purple', linewidth=2, label='BB Position')
                ax2.axhline(y=1, color='r', linestyle='--', alpha=0.5, label='Upper Band')
                ax2.axhline(y=0, color='g', linestyle='--', alpha=0.5, label='Lower Band')
                ax2.axhline(y=0.5, color='b', linestyle=':', alpha=0.5, label='Middle')
                ax2.set_ylim(-0.1, 1.1)
                ax2.set_title('Bollinger Band Position (0=Lower Band, 1=Upper Band)')
                ax2.legend(loc='upper right')
                ax2.grid(True, alpha=0.3)
            
            # Format dates
            for ax in [ax1, ax2]:
                ax.tick_params(axis='x', rotation=45, labelsize=9)
            
            plt.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
            plt.close(fig)
            buf.seek(0)
            print("Bollinger Bands chart generated successfully!")
            return buf.getvalue()
            
        except Exception as e:
            print(f"Bollinger chart generation error: {e}")
            return b''

    def generate_arima_forecast_chart(self, arima_data: Dict, figsize: Tuple[int, int] = (12, 6)) -> bytes:
        """Generate dedicated ARIMA forecast chart"""
        try:
            print("Generating ARIMA forecast chart...")
            forecast_prices = arima_data.get('forecast_prices', [])
            
            if not forecast_prices:
                return b''
                
            forecast_prices = np.array(forecast_prices)
            if len(forecast_prices) == 0:
                return b''
                
            fig, ax = plt.subplots(figsize=figsize)
            
            # Plot historical data (last 30 days for clarity)
            historical_data = self.data.tail(30) if len(self.data) > 30 else self.data
            ax.plot(historical_data.index, historical_data['Close'], 
                   label='Historical Prices', color='blue', linewidth=2)
            
            # Plot ARIMA forecast
            last_date = self.data.index[-1]
            forecast_days = arima_data.get('days', len(forecast_prices))
            forecast_dates = pd.date_range(start=last_date + timedelta(days=1), 
                                        periods=len(forecast_prices), freq='D')
            
            ax.plot(forecast_dates, forecast_prices, 
                    label=f'ARIMA Forecast ({arima_data.get("trend", "Unknown")})', 
                    color='red', linewidth=2, linestyle='--', marker='o', markersize=4)
            
            # Add confidence bands if available
            if 'confidence_upper' in arima_data and 'confidence_lower' in arima_data:
                confidence_upper = arima_data['confidence_upper']
                confidence_lower = arima_data['confidence_lower']
                if confidence_upper and confidence_lower:
                    ax.fill_between(forecast_dates, 
                                  confidence_lower, 
                                  confidence_upper, 
                                  alpha=0.2, color='red', label='95% Confidence Interval')
            
            # Vertical line to separate historical from forecast
            ax.axvline(x=last_date, color='gray', linestyle=':', alpha=0.7, label='Forecast Start')
            
            # Add model info
            aic_value = arima_data.get('model_aic', 'N/A')
            ax.set_title(f'{self.symbol} - ARIMA(1,1,1) Forecast (AIC: {aic_value})')
            ax.set_ylabel('Price ($)')
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            plt.xticks(rotation=45, fontsize=9)
            plt.tight_layout()
            
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
            plt.close(fig)
            buf.seek(0)
            print("ARIMA forecast chart generated successfully!")
            return buf.getvalue()
            
        except Exception as e:
            print(f"ARIMA chart generation error: {e}")
            return b''

    def generate_garch_chart(self, garch_data: Dict, figsize: Tuple[int, int] = (12, 6)) -> bytes:
        """Generate enhanced GARCH volatility forecast chart"""
        try:
            print("Generating GARCH volatility chart...")
            forecast_volatility = garch_data.get('forecast_volatility', [])
            
            if not forecast_volatility:
                return b''

            # Calculate historical volatility
            returns = self.data['Close'].pct_change().dropna() * 100
            historical_volatility = returns.rolling(window=min(20, len(returns))).std()
            
            # Get dates for the forecast
            last_date = self.data.index[-1]
            forecast_days = garch_data.get('days', len(forecast_volatility))
            forecast_dates = pd.date_range(start=last_date + timedelta(days=1),
                                           periods=len(forecast_volatility), freq='D')

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, height_ratios=[2, 1])
            fig.suptitle(f'{self.symbol} - GARCH(1,1) Volatility Analysis', fontsize=14)

            # Top plot: Volatility forecast
            ax1.plot(historical_volatility.index, historical_volatility, 
                    label='Historical Volatility (20-day)', color='blue', linewidth=2)
            ax1.plot(forecast_dates, forecast_volatility,
                    label=f'GARCH Forecast ({forecast_days} days)', 
                    color='red', linewidth=2, linestyle='--', marker='o', markersize=3)
            
            # Add average volatility line
            avg_vol = historical_volatility.mean()
            ax1.axhline(y=avg_vol, color='gray', linestyle=':', alpha=0.7, 
                       label=f'Average Vol ({avg_vol:.2f}%)')
            
            # Vertical line separator
            ax1.axvline(x=last_date, color='gray', linestyle=':', alpha=0.7)
            
            ax1.set_title('Volatility Forecast (% Standard Deviation)')
            ax1.set_ylabel('Volatility (%)')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # Bottom plot: Daily returns context
            ax2.plot(returns.index, returns, color='darkgreen', alpha=0.7, linewidth=1)
            ax2.axhline(y=0, color='black', linewidth=0.5)
            ax2.set_title('Daily Returns Context')
            ax2.set_ylabel('Return (%)')
            ax2.grid(True, alpha=0.3)
            
            # Format dates
            for ax in [ax1, ax2]:
                ax.tick_params(axis='x', rotation=45, labelsize=9)
            
            plt.tight_layout()

            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=80)
            plt.close(fig)
            buf.seek(0)
            print("GARCH volatility chart generated successfully!")
            return buf.getvalue()

        except Exception as e:
            print(f"GARCH chart generation error: {e}")
            return b''
    
    def get_analysis_summary(self) -> Dict:
        """Get comprehensive analysis summary with all models"""
        try:
            signals = self.generate_signals()
        except Exception as e:
            print(f"Signal generation failed: {e}")
            signals = {'Error': 'Unable to generate signals'}
        
        try:
            arima_forecast = self.enhanced_arima_forecast(days=10)
        except Exception as e:
            print(f"ARIMA forecast failed: {e}")
            arima_forecast = {'trend': 'Unknown', 'confidence': 0.0}
            
        try:
            garch_forecast = self.enhanced_garch_forecast(days=10)
        except Exception as e:
            print(f"GARCH forecast failed: {e}")
            garch_forecast = {'forecast_volatility': [], 'current_volatility': 0.0}
        
        # Basic price info with error handling
        try:
            current_price = float(self.data['Close'].iloc[-1])
            if len(self.data) > 1:
                price_change = float(self.data['Close'].iloc[-1] - self.data['Close'].iloc[-2])
                price_change_pct = (price_change / self.data['Close'].iloc[-2]) * 100 if self.data['Close'].iloc[-2] != 0 else 0.0
            else:
                price_change = 0.0
                price_change_pct = 0.0
        except:
            current_price = 0.0
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
            
        try:
            bb_position = float(self.indicators.get('BB_Position', pd.Series([0.5])).iloc[-1])
        except:
            bb_position = 0.5
        
        summary = {
            'symbol': self.symbol,
            'current_price': current_price,
            'daily_change': price_change,
            'daily_change_pct': price_change_pct,
            'volume_ratio': volume_ratio,
            'signals': signals,
            'arima_forecast': arima_forecast,
            'garch_forecast': garch_forecast,
            'rsi': rsi_value,
            'bb_position': bb_position,
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return summary

def run_enhanced_analysis(ticker: str) -> Dict:
    """Run enhanced analysis with ARIMA, GARCH, and Bollinger Bands"""
    try:
        print(f"Starting enhanced technical analysis for {ticker}...")
        
        # Initialize agent
        agent = UltraFastTechnicalAnalysisAgent(ticker, period="2mo")
        print("Agent initialized successfully")
        
        # Calculate indicators
        agent.calculate_essential_indicators()
        print("Indicators calculated")
        
        # Get comprehensive summary
        summary = agent.get_analysis_summary()
        print("Summary generated")
        
        # Generate all charts
        tech_image = None
        bollinger_image = None
        arima_image = None
        garch_image = None
        
        print("Generating technical indicators chart...")
        try:
            tech_png = agent.generate_fast_technical_chart()
            if tech_png:
                tech_image = base64.b64encode(tech_png).decode("utf-8")
                print("Technical indicators chart generated")
        except Exception as e:
            print(f"Technical chart error: {e}")
        
        print("Generating Bollinger Bands chart...")
        try:
            bollinger_png = agent.generate_bollinger_chart()
            if bollinger_png:
                bollinger_image = base64.b64encode(bollinger_png).decode("utf-8")
                print("Bollinger Bands chart generated")
        except Exception as e:
            print(f"Bollinger chart error: {e}")
        
        print("Generating ARIMA forecast chart...")
        try:
            arima_data = summary['arima_forecast']
            arima_png = agent.generate_arima_forecast_chart(arima_data)
            if arima_png:
                arima_image = base64.b64encode(arima_png).decode("utf-8")
                print("ARIMA forecast chart generated")
        except Exception as e:
            print(f"ARIMA chart error: {e}")
        
        print("Generating GARCH volatility chart...")
        try:
            garch_data = summary['garch_forecast']
            garch_png = agent.generate_garch_chart(garch_data)
            if garch_png:
                garch_image = base64.b64encode(garch_png).decode("utf-8")
                print("GARCH volatility chart generated")
        except Exception as e:
            print(f"GARCH chart error: {e}")
        
        print("Creating comprehensive text report...")
        # Create enhanced text report
        arima_forecast = summary['arima_forecast']
        garch_forecast = summary['garch_forecast']
        
        lines = [
            f"ENHANCED TECHNICAL ANALYSIS - {summary['symbol']}",
            f"Current Price: ${summary['current_price']:.2f}",
            f"Daily Change: ${summary['daily_change']:+.2f} ({summary['daily_change_pct']:+.2f}%)",
            f"Volume Ratio: {summary.get('volume_ratio', 1.0):.2f}x",
            f"RSI: {summary['rsi']:.1f}",
            f"Bollinger Position: {summary['bb_position']:.2f} (0=Lower, 1=Upper)",
            "",
            "Trading Signals:",
        ]
        
        for k, v in summary["signals"].items():
            lines.append(f"- {k}: {v}")
        
        lines.extend([
            "",
            "ARIMA Time Series Forecast:",
            f"- Trend: {arima_forecast.get('trend', 'Unknown')}",
            f"- Confidence: {arima_forecast.get('confidence', 0.0):.1%}",
            f"- Model AIC: {arima_forecast.get('model_aic', 'N/A')}",
        ])
        
        if arima_forecast.get('forecast_prices'):
            forecast_prices = arima_forecast['forecast_prices']
            lines.append(f"- Price Target (10d): ${forecast_prices[-1]:.2f}")
        
        lines.extend([
            "",
            "GARCH Volatility Forecast:",
            f"- Current Volatility: {garch_forecast.get('current_volatility', 0.0):.2f}%",
            f"- Average Volatility: {garch_forecast.get('avg_volatility', 0.0):.2f}%",
        ])
        
        if garch_forecast.get('forecast_volatility'):
            vol_forecast = garch_forecast['forecast_volatility']
            lines.append(f"- Expected Volatility (10d): {vol_forecast[-1]:.2f}%")
        
        lines.extend([
            "",
            f"Analysis Date: {summary['analysis_date']}",
            "Models: ARIMA(1,1,1), GARCH(1,1), Bollinger Bands (20-period, 2σ)"
        ])
        
        tech_text = "\n".join(lines)
        print("Enhanced analysis completed successfully!")
        
        return {
            'text': tech_text,
            'tech_image': tech_image,
            'bollinger_image': bollinger_image,
            'arima_image': arima_image,
            'garch_image': garch_image,
            'status': 'success'
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"Enhanced analysis failed: {error_msg}")
        
        return {
            'text': f"Enhanced technical analysis failed for {ticker}: {error_msg}",
            'tech_image': None,
            'bollinger_image': None,
            'arima_image': None,
            'garch_image': None,
            'status': 'error'
        }

# Legacy function for backward compatibility
def run_ultra_fast_analysis(ticker: str) -> Dict:
    """Legacy function - redirects to enhanced analysis"""
    return run_enhanced_analysis(ticker)

if __name__ == "__main__":
    import time
    ticker = input("Enter ticker (e.g., AAPL): ").strip().upper() or "AAPL"
    
    start_time = time.time()
    result = run_enhanced_analysis(ticker)
    end_time = time.time()
    
    print(f"\n{result['text']}")
    print(f"\nTechnical Chart: {bool(result.get('tech_image'))}")
    print(f"Bollinger Bands Chart: {bool(result.get('bollinger_image'))}")
    print(f"ARIMA Forecast Chart: {bool(result.get('arima_image'))}")
    print(f"GARCH Volatility Chart: {bool(result.get('garch_image'))}")
    print(f"Execution time: {end_time - start_time:.2f} seconds")