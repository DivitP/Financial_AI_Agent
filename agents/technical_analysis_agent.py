import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import warnings
from typing import Dict, List, Tuple, Optional
import seaborn as sns
from scipy import stats
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error

warnings.filterwarnings('ignore')
plt.style.use('seaborn-v0_8')

class TechnicalAnalysisAgent:
    """
    A comprehensive technical analysis agent for stock analysis and forecasting
    """
    
    def __init__(self, symbol: str, period: str = "1y"):
        """
        Initialize the agent with a stock symbol
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL', 'GOOGL')
            period: Time period for data ('1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max')
        """
        self.symbol = symbol.upper()
        self.period = period
        self.data = None
        self.indicators = {}
        
        self.fetch_data()
        
    def fetch_data(self) -> pd.DataFrame:
        """Fetch stock data from Yahoo Finance"""
        try:
            ticker = yf.Ticker(self.symbol)
            self.data = ticker.history(period=self.period)
            
            if self.data.empty:
                raise ValueError(f"No data found for symbol {self.symbol}")
                
            print(f"Successfully fetched {len(self.data)} days of data for {self.symbol}")
            return self.data
            
        except Exception as e:
            print(f"Error fetching data for {self.symbol}: {str(e)}")
            raise
    
    def calculate_sma(self, window: int = 20) -> pd.Series:
        """Calculate Simple Moving Average"""
        sma = self.data['Close'].rolling(window=window).mean()
        self.indicators[f'SMA_{window}'] = sma
        return sma
    
    def calculate_ema(self, window: int = 20) -> pd.Series:
        """Calculate Exponential Moving Average"""
        ema = self.data['Close'].ewm(span=window).mean()
        self.indicators[f'EMA_{window}'] = ema
        return ema
    
    def calculate_rsi(self, window: int = 14) -> pd.Series:
        """Calculate Relative Strength Index"""
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        self.indicators['RSI'] = rsi
        return rsi
    
    def calculate_macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, pd.Series]:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        ema_fast = self.data['Close'].ewm(span=fast).mean()
        ema_slow = self.data['Close'].ewm(span=slow).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        macd_dict = {
            'MACD': macd_line,
            'Signal': signal_line,
            'Histogram': histogram
        }
        
        self.indicators.update(macd_dict)
        return macd_dict
    
    def calculate_bollinger_bands(self, window: int = 20, std_dev: int = 2) -> Dict[str, pd.Series]:
        """Calculate Bollinger Bands"""
        sma = self.data['Close'].rolling(window=window).mean()
        std = self.data['Close'].rolling(window=window).std()
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        bb_dict = {
            'BB_Upper': upper_band,
            'BB_Middle': sma,
            'BB_Lower': lower_band
        }
        
        self.indicators.update(bb_dict)
        return bb_dict
    
    def calculate_stochastic(self, k_window: int = 14, d_window: int = 3) -> Dict[str, pd.Series]:
        """Calculate Stochastic Oscillator"""
        low_min = self.data['Low'].rolling(window=k_window).min()
        high_max = self.data['High'].rolling(window=k_window).max()
        
        k_percent = ((self.data['Close'] - low_min) / (high_max - low_min)) * 100
        d_percent = k_percent.rolling(window=d_window).mean()
        
        stoch_dict = {
            'Stoch_K': k_percent,
            'Stoch_D': d_percent
        }
        
        self.indicators.update(stoch_dict)
        return stoch_dict
    
    def calculate_atr(self, window: int = 14) -> pd.Series:
        """Calculate Average True Range"""
        high_low = self.data['High'] - self.data['Low']
        high_close_prev = np.abs(self.data['High'] - self.data['Close'].shift())
        low_close_prev = np.abs(self.data['Low'] - self.data['Close'].shift())
        
        true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
        atr = true_range.rolling(window=window).mean()
        
        self.indicators['ATR'] = atr
        return atr
    
    def calculate_volume_indicators(self) -> Dict[str, pd.Series]:
        """Calculate volume-based indicators"""
        obv = (np.sign(self.data['Close'].diff()) * self.data['Volume']).fillna(0).cumsum()
        
        # Volume Moving Average
        vol_sma = self.data['Volume'].rolling(window=20).mean()
        
        vol_dict = {
            'OBV': obv,
            'Volume_SMA': vol_sma
        }
        
        self.indicators.update(vol_dict)
        return vol_dict
    
    def calculate_all_indicators(self):
        """Calculate all technical indicators"""
        print(" Calculating technical indicators...")
        
        self.calculate_sma(20)
        self.calculate_sma(50)
        self.calculate_sma(200)
        self.calculate_ema(12)
        self.calculate_ema(26)
        
        self.calculate_rsi()
        self.calculate_macd()
        self.calculate_stochastic()
        
        self.calculate_bollinger_bands()
        self.calculate_atr()
        
        self.calculate_volume_indicators()
            
    def generate_signals(self) -> Dict[str, str]:
        """Generate trading signals based on technical indicators"""
        signals = {}
        latest_data = self.data.iloc[-1]
        
        # RSI signals
        rsi_current = self.indicators['RSI'].iloc[-1]
        if rsi_current > 70:
            signals['RSI'] = 'SELL - Overbought'
        elif rsi_current < 30:
            signals['RSI'] = 'BUY - Oversold'
        else:
            signals['RSI'] = 'NEUTRAL'
        
        # MACD signals
        macd_current = self.indicators['MACD'].iloc[-1]
        signal_current = self.indicators['Signal'].iloc[-1]
        if macd_current > signal_current:
            signals['MACD'] = 'BUY - Bullish crossover'
        else:
            signals['MACD'] = 'SELL - Bearish crossover'
        
        # Moving Average signals
        price_current = latest_data['Close']
        sma_20 = self.indicators['SMA_20'].iloc[-1]
        sma_50 = self.indicators['SMA_50'].iloc[-1]
        
        if price_current > sma_20 > sma_50:
            signals['MA_Trend'] = 'BUY - Uptrend'
        elif price_current < sma_20 < sma_50:
            signals['MA_Trend'] = 'SELL - Downtrend'
        else:
            signals['MA_Trend'] = 'NEUTRAL'
        
        # Bollinger Bands signals
        bb_upper = self.indicators['BB_Upper'].iloc[-1]
        bb_lower = self.indicators['BB_Lower'].iloc[-1]
        
        if price_current > bb_upper:
            signals['Bollinger'] = 'SELL - Above upper band'
        elif price_current < bb_lower:
            signals['Bollinger'] = 'BUY - Below lower band'
        else:
            signals['Bollinger'] = 'NEUTRAL'
        
        return signals
    
    def simple_forecast(self, days: int = 30) -> Dict[str, float]:
        """simple time series forecasting using linear regression"""
        from sklearn.linear_model import LinearRegression
        
        prices = self.data['Close'].values
        X = np.arange(len(prices)).reshape(-1, 1)
        y = prices
        
        model = LinearRegression()
        model.fit(X, y)
        
        future_X = np.arange(len(prices), len(prices) + days).reshape(-1, 1)
        future_prices = model.predict(future_X)
        
        trend = "Bullish" if model.coef_[0] > 0 else "Bearish"
        
        return {
            'forecast_prices': future_prices,
            'trend': trend,
            'confidence': model.score(X, y),
            'slope': model.coef_[0],
            'days': days
        }
    
    def plot_technical_analysis(self, figsize: Tuple[int, int] = (15, 12)):
        """Create comprehensive technical analysis charts"""
        fig, axes = plt.subplots(4, 1, figsize=figsize, height_ratios=[3, 1, 1, 1])
        fig.suptitle(f'{self.symbol} - Technical Analysis', fontsize=16, fontweight='bold')
        
        # Price and Moving Averages
        ax1 = axes[0]
        ax1.plot(self.data.index, self.data['Close'], label='Close Price', linewidth=2, color='black')
        ax1.plot(self.data.index, self.indicators['SMA_20'], label='SMA 20', alpha=0.7)
        ax1.plot(self.data.index, self.indicators['SMA_50'], label='SMA 50', alpha=0.7)
        ax1.plot(self.data.index, self.indicators['SMA_200'], label='SMA 200', alpha=0.7)
        
        # Bollinger Bands
        ax1.fill_between(self.data.index, self.indicators['BB_Upper'], self.indicators['BB_Lower'], 
                        alpha=0.2, color='gray', label='Bollinger Bands')
        
        ax1.set_title('Price Action with Moving Averages & Bollinger Bands')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # RSI
        ax2 = axes[1]
        ax2.plot(self.data.index, self.indicators['RSI'], color='purple', linewidth=2)
        ax2.axhline(y=70, color='r', linestyle='--', alpha=0.7, label='Overbought')
        ax2.axhline(y=30, color='g', linestyle='--', alpha=0.7, label='Oversold')
        ax2.fill_between(self.data.index, 30, 70, alpha=0.1, color='gray')
        ax2.set_title('RSI (14)')
        ax2.set_ylabel('RSI')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        
        # MACD
        ax3 = axes[2]
        ax3.plot(self.data.index, self.indicators['MACD'], label='MACD', color='blue')
        ax3.plot(self.data.index, self.indicators['Signal'], label='Signal', color='red')
        ax3.bar(self.data.index, self.indicators['Histogram'], alpha=0.3, color='green', label='Histogram')
        ax3.set_title('MACD')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # Volume
        ax4 = axes[3]
        ax4.bar(self.data.index, self.data['Volume'], alpha=0.7, color='orange')
        ax4.plot(self.data.index, self.indicators['Volume_SMA'], color='red', linewidth=2, label='Volume SMA')
        ax4.set_title('Volume')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.xaxis.set_major_locator(mdates.MonthLocator())
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        plt.show()
    
    def plot_forecast(self, forecast_data: Dict, figsize: Tuple[int, int] = (12, 6)):
        """Plot price forecast"""
        fig, ax = plt.subplots(figsize=figsize)
        
        # Plot  & forcast data
        ax.plot(self.data.index, self.data['Close'], label='Historical Prices', color='blue', linewidth=2)
        
        last_date = self.data.index[-1]
        forecast_dates = pd.date_range(start=last_date + timedelta(days=1), 
                                     periods=forecast_data['days'], freq='D')
        
        ax.plot(forecast_dates, forecast_data['forecast_prices'], 
                label=f'Forecast ({forecast_data["trend"]})', 
                color='red', linewidth=2, linestyle='--')
        
        # Add vertical line at forecast start
        ax.axvline(x=last_date, color='gray', linestyle=':', alpha=0.7, label='Forecast Start')
        
        ax.set_title(f'{self.symbol} - Price Forecast (R² = {forecast_data["confidence"]:.3f})')
        ax.set_ylabel('Price ($)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()
    
    def get_analysis_summary(self) -> Dict:
        """Get a comprehensive analysis summary"""
        signals = self.generate_signals()
        forecast = self.simple_forecast()
        
        current_price = self.data['Close'].iloc[-1]
        price_change = self.data['Close'].iloc[-1] - self.data['Close'].iloc[-2]
        price_change_pct = (price_change / self.data['Close'].iloc[-2]) * 100
        
        # Volatility (using ATR)
        volatility = self.indicators['ATR'].iloc[-1]
        avg_volume = self.data['Volume'].mean()
        current_volume = self.data['Volume'].iloc[-1]
        
        summary = {
            'symbol': self.symbol,
            'current_price': current_price,
            'daily_change': price_change,
            'daily_change_pct': price_change_pct,
            'volatility_atr': volatility,
            'volume_ratio': current_volume / avg_volume,
            'signals': signals,
            'forecast_trend': forecast['trend'],
            'forecast_confidence': forecast['confidence'],
            'rsi': self.indicators['RSI'].iloc[-1],
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return summary
    
    def print_analysis_report(self):
        """Print a formatted analysis report"""
        summary = self.get_analysis_summary()
        
        print(f"\n{'='*60}")
        print(f"TECHNICAL ANALYSIS REPORT - {summary['symbol']}")
        print(f"{'='*60}")
        print(f"Analysis Date: {summary['analysis_date']}")
        print(f"Current Price: ${summary['current_price']:.2f}")
        print(f"Daily Change: ${summary['daily_change']:+.2f} ({summary['daily_change_pct']:+.2f}%)")
        print(f"Volatility (ATR): {summary['volatility_atr']:.2f}")
        print(f"Volume Ratio: {summary['volume_ratio']:.2f}x avg")
        print(f"RSI: {summary['rsi']:.1f}")
        
        print(f"\n📊 TRADING SIGNALS:")
        print(f"{'-'*40}")
        for indicator, signal in summary['signals'].items():
            emoji = "🟢" if "BUY" in signal else "🔴" if "SELL" in signal else "🟡"
            print(f"{emoji} {indicator}: {signal}")
        
        print(f"\n🔮 FORECAST:")
        print(f"{'-'*40}")
        trend_emoji = "📈" if summary['forecast_trend'] == "Bullish" else "📉"
        print(f"{trend_emoji} Trend: {summary['forecast_trend']}")
        print(f"🎯 Confidence: {summary['forecast_confidence']:.1%}")

def main():
    """Main function for technical analysis agent"""
    print("Technical Analysis Agent")
    print("=" * 50)
    
    symbol = input("Enter stock symbol (e.g., AAPL): ").strip().upper() or "AAPL"
    period = input("Enter period (1y, 6mo, 3mo, etc.) [default: 1y]: ").strip() or "1y"
    
    try:
        agent = TechnicalAnalysisAgent(symbol, period)
        agent.calculate_all_indicators()
        agent.print_analysis_report()
        forecast = agent.simple_forecast(days=30)
        
        # Create visualizations
        print(f"\n Generating charts for {symbol}...")
        agent.plot_technical_analysis()
        agent.plot_forecast(forecast)
        
        print(f"\nAnalysis complete for {symbol}!")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        print("Please check the symbol and try again.")

if __name__ == "__main__":
    main()