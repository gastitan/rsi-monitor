import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime
import pytz
import logging

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('value_investment_monitor.log')
    ]
)

class ValueInvestmentMonitor:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def calculate_rsi(self, prices, period=14):
        """Calcula RSI"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """Calcula MACD"""
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        return {
            'macd': macd_line.iloc[-1],
            'signal': signal_line.iloc[-1],
            'histogram': histogram.iloc[-1],
            'crossover': macd_line.iloc[-1] > signal_line.iloc[-1]
        }
    
    def calculate_support_resistance(self, data, lookback=20):
        """Identifica niveles de soporte y resistencia"""
        highs = data['High'].rolling(window=lookback, center=True).max()
        lows = data['Low'].rolling(window=lookback, center=True).min()
        
        current_price = data['Close'].iloc[-1]
        recent_high = data['High'].tail(lookback).max()
        recent_low = data['Low'].tail(lookback).min()
        
        # Distancia desde máximos/mínimos recientes
        distance_from_high = ((current_price - recent_high) / recent_high) * 100
        distance_from_low = ((current_price - recent_low) / recent_low) * 100
        
        return {
            'recent_high': recent_high,
            'recent_low': recent_low,
            'distance_from_high': distance_from_high,
            'distance_from_low': distance_from_low,
            'near_support': distance_from_low < 5  # Dentro del 5% del soporte
        }
    
    def get_stock_analysis(self, symbol):
        """Análisis completo de la acción"""
        try:
            stock = yf.Ticker(symbol)
            
            # Datos históricos (6 meses para mejor análisis)
            data = stock.history(period="6mo")
            if data.empty:
                return None
            
            # Información básica
            info = stock.info
            market_cap = info.get('marketCap', 0)
            sector = info.get('sector', 'Unknown')
            
            # Solo empresas grandes (market cap > $10B)
            if market_cap < 10_000_000_000:
                return None
            
            current_price = data['Close'].iloc[-1]
            
            # Indicadores técnicos
            rsi = self.calculate_rsi(data['Close'])
            macd_data = self.calculate_macd(data['Close'])
            support_resistance = self.calculate_support_resistance(data)
            
            # Volatilidad (desviación estándar de retornos diarios)
            returns = data['Close'].pct_change().dropna()
            volatility = returns.std() * np.sqrt(252) * 100  # Anualizada
            
            # Performance reciente
            perf_1m = ((current_price - data['Close'].iloc[-21]) / data['Close'].iloc[-21]) * 100
            perf_3m = ((current_price - data['Close'].iloc[-63]) / data['Close'].iloc[-63]) * 100
            
            # Volumen promedio vs actual
            avg_volume = data['Volume'].tail(20).mean()
            current_volume = data['Volume'].iloc[-1]
            volume_ratio = current_volume / avg_volume
            
            return {
                'symbol': symbol,
                'company_name': info.get('longName', symbol),
                'sector': sector,
                'market_cap': market_cap,
                'current_price': current_price,
                'rsi': rsi,
                'macd': macd_data,
                'support_resistance': support_resistance,
                'volatility': volatility,
                'performance': {
                    '1m': perf_1m,
                    '3m': perf_3m
                },
                'volume_ratio': volume_ratio,
                'success': True
            }
            
        except Exception as e:
            logging.error(f"Error analizando {symbol}: {e}")
            return {'symbol': symbol, 'success': False, 'error': str(e)}
    
    def classify_opportunity(self, analysis):
        """Clasifica la oportunidad de inversión"""
        if not analysis or not analysis['success']:
            return None
        
        rsi = analysis['rsi']
        macd = analysis['macd']
        performance_3m = analysis['performance']['3m']
        near_support = analysis['support_resistance']['near_support']
        
        score = 0
        reasons = []
        
        # RSI scoring
        if rsi < 25:
            score += 3
            reasons.append(f"RSI extremadamente bajo ({rsi:.1f})")
        elif rsi < 30:
            score += 2
            reasons.append(f"RSI en sobreventa ({rsi:.1f})")
        elif rsi < 40:
            score += 1
            reasons.append(f"RSI moderadamente bajo ({rsi:.1f})")
        
        # MACD scoring
        if macd['crossover'] and macd['histogram'] > 0:
            score += 2
            reasons.append("MACD cruzando alcista")
        elif macd['crossover']:
            score += 1
            reasons.append("MACD iniciando giro alcista")
        
        # Performance scoring (buscamos caídas para acumular)
        if performance_3m < -20:
            score += 2
            reasons.append(f"Caída significativa 3M ({performance_3m:.1f}%)")
        elif performance_3m < -10:
            score += 1
            reasons.append(f"Corrección moderada 3M ({performance_3m:.1f}%)")
        
        # Soporte técnico
        if near_support:
            score += 1
            reasons.append("Cerca de nivel de soporte")
        
        # Clasificación
        if score >= 5:
            return {'level': '🟢 EXCELENTE', 'score': score, 'reasons': reasons}
        elif score >= 3:
            return {'level': '🟡 BUENA', 'score': score, 'reasons': reasons}
        elif score >= 1:
            return {'level': '🔵 MODERADA', 'score': score, 'reasons': reasons}
        else:
            return None
    
    def send_telegram_message(self, message):
        """Envía mensaje por Telegram"""
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(self.telegram_url, data=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Error enviando mensaje: {e}")
            return False
    
    def is_market_hours(self):
        """Verificar horario de mercado"""
        try:
            ny_tz = pytz.timezone('America/New_York')
            now_ny = datetime.now(ny_tz)
            weekday = now_ny.weekday()
            
            if weekday >= 5:
                return False
            
            return 9 <= now_ny.hour < 16 or (now_ny.hour == 16 and now_ny.minute <= 30)
        except:
            return True
    
    def run_analysis(self, stock_list):
        """Ejecutar análisis completo"""
        if not self.is_market_hours():
            logging.info("⏭️ Fuera del horario de mercado")
            return
        
        logging.info(f"🔍 Analizando {len(stock_list)} empresas grandes...")
        
        opportunities = []
        
        for symbol in stock_list:
            logging.info(f"📊 Analizando {symbol}...")
            analysis = self.get_stock_analysis(symbol)
            
            if analysis and analysis['success']:
                opportunity = self.classify_opportunity(analysis)
                if opportunity:
                    opportunities.append({
                        'analysis': analysis,
                        'opportunity': opportunity
                    })
        
        # Ordenar por score (mejores primero)
        opportunities.sort(key=lambda x: x['opportunity']['score'], reverse=True)
        
        if opportunities:
            self.send_opportunity_alert(opportunities[:5])  # Top 5
        
        logging.info(f"✅ Análisis completado: {len(opportunities)} oportunidades encontradas")
    
    def send_opportunity_alert(self, opportunities):
        """Enviar alerta de oportunidades"""
        message = "💎 <b>OPORTUNIDADES DE ACUMULACIÓN</b>\n\n"
        
        for i, opp in enumerate(opportunities, 1):
            analysis = opp['analysis']
            opportunity = opp['opportunity']
            
            message += f"<b>{i}. {analysis['symbol']}</b> - {opportunity['level']}\n"
            message += f"🏢 {analysis['company_name'][:30]}...\n" if len(analysis['company_name']) > 30 else f"🏢 {analysis['company_name']}\n"
            message += f"💰 ${analysis['current_price']:.2f} | 📊 RSI: {analysis['rsi']:.1f}\n"
            message += f"📈 3M: {analysis['performance']['3m']:.1f}% | 🎯 Score: {opportunity['score']}\n"
            
            # Razones principales (máximo 2)
            main_reasons = opportunity['reasons'][:2]
            message += f"🔍 {', '.join(main_reasons)}\n\n"
        
        message += f"⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        message += "🤖 <i>Análisis automatizado - No es consejo financiero</i>"
        
        self.send_telegram_message(message)

def main():
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    
    if not BOT_TOKEN or not CHAT_ID:
        logging.error("❌ Variables de entorno no configuradas")
        exit(1)
    
    # S&P 100 - Empresas más grandes y líquidas
    LARGE_CAP_STOCKS = [
        # Tecnología
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "NFLX", "CRM", "ORCL",
        # Salud
        "UNH", "JNJ", "PFE", "ABT", "TMO", "DHR", "BMY", "ABBV", "MRK", "LLY",
        # Financiero  
        "BRK-A", "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "SCHW", "BLK",
        # Consumo
        "PG", "KO", "PEP", "WMT", "HD", "MCD", "NKE", "SBUX", "TGT", "COST",
        # Industrial
        "BA", "CAT", "GE", "MMM", "HON", "UPS", "LMT", "RTX", "DE", "UNP",
        # Energía
        "XOM", "CVX", "COP", "EOG", "SLB", "PXD", "VLO", "MPC", "PSX", "OXY"
    ]
    
    monitor = ValueInvestmentMonitor(BOT_TOKEN, CHAT_ID)
    
    try:
        monitor.run_analysis(LARGE_CAP_STOCKS)
        logging.info("✅ Análisis de value investing completado")
    except Exception as e:
        logging.error(f"💥 Error fatal: {e}")
        exit(1)

if __name__ == "__main__":
    main()