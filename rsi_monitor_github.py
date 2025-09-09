import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime
import pytz
import logging

# Configuración de logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Para GitHub Actions logs
        logging.FileHandler('rsi_monitor.log')  # Archivo de log opcional
    ]
)

class RSIMonitor:
    def __init__(self, bot_token, chat_id):
        """
        Inicializa el monitor RSI para GitHub Actions
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def calculate_rsi(self, prices, period=14):
        """
        Calcula el RSI (Relative Strength Index)
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def get_stock_data(self, symbol, period="3mo"):
        """
        Obtiene datos históricos de la acción
        """
        try:
            stock = yf.Ticker(symbol)
            data = stock.history(period=period)
            
            if data.empty:
                logging.warning(f"No se encontraron datos para {symbol}")
                return None
                
            return data
        except Exception as e:
            logging.error(f"Error obteniendo datos para {symbol}: {e}")
            return None
    
    def send_telegram_message(self, message):
        """
        Envía mensaje por Telegram
        """
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(self.telegram_url, data=payload, timeout=10)
            
            if response.status_code == 200:
                logging.info("✅ Mensaje enviado correctamente por Telegram")
                return True
            else:
                logging.error(f"❌ Error enviando mensaje: {response.status_code}")
                return False
                
        except Exception as e:
            logging.error(f"❌ Error enviando mensaje por Telegram: {e}")
            return False
    
    def is_market_hours(self):
        """
        Verifica si estamos en horario de mercado (más permisivo para GitHub Actions)
        """
        try:
            ny_tz = pytz.timezone('America/New_York')
            now_ny = datetime.now(ny_tz)
            
            # Verificar día de la semana
            weekday = now_ny.weekday()
            if weekday >= 5:  # Weekend
                logging.info(f"🔒 Fin de semana - Mercado cerrado")
                return False
            
            # Horario extendido para GitHub Actions (9:00 AM - 4:30 PM ET)
            # Esto da margen para diferencias de cron timing
            if 9 <= now_ny.hour < 16 or (now_ny.hour == 16 and now_ny.minute <= 30):
                logging.info(f"📈 Horario de mercado - Hora NY: {now_ny.strftime('%H:%M:%S')}")
                return True
            else:
                logging.info(f"🔒 Fuera de horario - Hora NY: {now_ny.strftime('%H:%M:%S')}")
                return False
                
        except Exception as e:
            logging.error(f"Error verificando horario: {e}")
            return True  # En caso de error, ejecutar anyway
    
    def check_rsi_alert(self, symbol, rsi_threshold=30):
        """
        Verifica RSI y envía alerta si es necesario
        """
        data = self.get_stock_data(symbol)
        
        if data is None:
            return {
                'symbol': symbol,
                'success': False,
                'error': 'No se pudieron obtener datos'
            }
        
        try:
            rsi = self.calculate_rsi(data['Close'])
            current_price = data['Close'].iloc[-1]
            
            result = {
                'symbol': symbol,
                'rsi': round(rsi, 2),
                'price': round(current_price, 2),
                'success': True,
                'alert_sent': False
            }
            
            # Si RSI está por debajo del umbral, enviar alerta
            if rsi < rsi_threshold:
                message = f"""
🚨 <b>ALERTA RSI - SOBREVENTA</b> 🚨

📊 <b>Acción:</b> {symbol}
📈 <b>RSI (14):</b> {round(rsi, 2)}
💰 <b>Precio:</b> ${round(current_price, 2)}
⏰ <b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

⚠️ RSI por debajo de {rsi_threshold} - Posible sobreventa
🤖 <i>Enviado desde GitHub Actions</i>
                """.strip()
                
                if self.send_telegram_message(message):
                    result['alert_sent'] = True
                    logging.info(f"🚨 Alerta enviada para {symbol} - RSI: {round(rsi, 2)}")
            else:
                logging.info(f"✅ {symbol}: RSI={round(rsi, 2)} (OK)")
            
            return result
            
        except Exception as e:
            logging.error(f"❌ Error calculando RSI para {symbol}: {e}")
            return {
                'symbol': symbol,
                'success': False,
                'error': str(e)
            }
    
    def run_single_check(self, stock_list, rsi_threshold=30):
        """
        Ejecuta una sola verificación (ideal para GitHub Actions)
        """
        # Verificar si estamos en horario de mercado
        if not self.is_market_hours():
            logging.info("⏭️ Ejecución omitida - Fuera del horario de mercado")
            return
        
        logging.info(f"🚀 Iniciando verificación RSI de {len(stock_list)} acciones")
        logging.info(f"📊 Umbral RSI: {rsi_threshold}")
        
        results = []
        alerts_count = 0
        
        for symbol in stock_list:
            logging.info(f"🔍 Verificando {symbol}...")
            result = self.check_rsi_alert(symbol, rsi_threshold)
            results.append(result)
            
            if result.get('alert_sent', False):
                alerts_count += 1
        
        # Resumen
        successful = len([r for r in results if r['success']])
        logging.info(f"📋 Resumen: {successful}/{len(stock_list)} exitosos, {alerts_count} alertas enviadas")
        
        # Enviar resumen si hay alertas o es la primera ejecución del día
        if alerts_count > 0:
            summary_message = f"""
📊 <b>Resumen RSI Monitor</b>

✅ <b>Acciones verificadas:</b> {successful}/{len(stock_list)}
🚨 <b>Alertas enviadas:</b> {alerts_count}
⏰ <b>Hora:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

🤖 <i>Ejecutado automáticamente desde GitHub Actions</i>
            """.strip()
            
            self.send_telegram_message(summary_message)

def main():
    # Configuración desde variables de entorno
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    
    # Verificar configuración
    if not BOT_TOKEN or not CHAT_ID:
        logging.error("❌ Variables de entorno no configuradas:")
        logging.error("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son requeridas")
        exit(1)
    
    # Lista de acciones a monitorear
    STOCK_LIST = [
        "AAPL",   # Apple
        "MSFT",   # Microsoft
        "GOOGL",  # Alphabet
        "AMZN",   # Amazon
        "TSLA",   # Tesla
        "NVDA",   # NVIDIA
        "META",   # Meta
        "NFLX",   # Netflix
        "AMD",    # AMD
        "INTC",   # Intel
        "SPY",    # S&P 500 ETF
        "QQQ"     # NASDAQ ETF
    ]
    
    RSI_THRESHOLD = 30
    
    # Crear instancia del monitor
    monitor = RSIMonitor(BOT_TOKEN, CHAT_ID)
    
    try:
        # Ejecutar una sola verificación
        monitor.run_single_check(STOCK_LIST, RSI_THRESHOLD)
        logging.info("✅ Ejecución completada exitosamente")
        
    except Exception as e:
        logging.error(f"💥 Error fatal: {e}")
        # Enviar notificación de error
        error_message = f"""
❌ <b>Error en RSI Monitor</b>

🐛 <b>Error:</b> {str(e)}
⏰ <b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

🤖 <i>GitHub Actions reportó un fallo</i>
        """.strip()
        
        monitor.send_telegram_message(error_message)
        exit(1)

if __name__ == "__main__":
    main()