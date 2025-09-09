import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RSIMonitor:
    def __init__(self, bot_token, chat_id):
        """
        Inicializa el monitor RSI
        
        Args:
            bot_token (str): Token del bot de Telegram
            chat_id (str): ID del chat donde enviar las notificaciones
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def calculate_rsi(self, prices, period=14):
        """
        Calcula el RSI (Relative Strength Index)
        
        Args:
            prices (pd.Series): Serie de precios
            period (int): Período para el cálculo del RSI (default: 14)
            
        Returns:
            float: Valor del RSI
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
        
        Args:
            symbol (str): Símbolo de la acción
            period (str): Período de datos (default: "3mo")
            
        Returns:
            pd.DataFrame: Datos históricos o None si hay error
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
        
        Args:
            message (str): Mensaje a enviar
            
        Returns:
            bool: True si se envió correctamente, False en caso contrario
        """
        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(self.telegram_url, data=payload, timeout=10)
            
            if response.status_code == 200:
                logging.info("Mensaje enviado correctamente por Telegram")
                return True
            else:
                logging.error(f"Error enviando mensaje: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"Error enviando mensaje por Telegram: {e}")
            return False
    
    def check_rsi_alert(self, symbol, rsi_threshold=30):
        """
        Verifica si el RSI está por debajo del umbral y envía alerta
        
        Args:
            symbol (str): Símbolo de la acción
            rsi_threshold (float): Umbral del RSI para la alerta
            
        Returns:
            dict: Información sobre el resultado del chequeo
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
💰 <b>Precio actual:</b> ${round(current_price, 2)}
⏰ <b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

⚠️ El RSI está por debajo de {rsi_threshold}, indicando posible sobreventa.
                """.strip()
                
                if self.send_telegram_message(message):
                    result['alert_sent'] = True
                    logging.info(f"Alerta enviada para {symbol} - RSI: {round(rsi, 2)}")
            
            return result
            
        except Exception as e:
            logging.error(f"Error calculando RSI para {symbol}: {e}")
            return {
                'symbol': symbol,
                'success': False,
                'error': str(e)
            }
    
    def monitor_stocks(self, stock_list, rsi_threshold=30, check_interval=1800):
        """
        Monitorea una lista de acciones solo durante el horario de mercado
        
        Args:
            stock_list (list): Lista de símbolos de acciones
            rsi_threshold (float): Umbral del RSI para alertas
            check_interval (int): Intervalo entre chequeos en segundos (default: 1800 = 30 min)
        """
        logging.info(f"🚀 Iniciando monitoreo inteligente de {len(stock_list)} acciones")
        logging.info(f"📊 Umbral RSI: {rsi_threshold}")
        logging.info(f"⏱️  Intervalo: {check_interval//60} minutos")
        logging.info(f"🕘 Solo durante horario de mercado: 9:30 AM - 4:00 PM ET (Lunes-Viernes)")
        
        while True:
            try:
                # Verificar si el mercado está abierto
                if not self.is_market_open():
                    next_open = self.get_next_market_open()
                    ny_tz = pytz.timezone('America/New_York')
                    now_ny = datetime.now(ny_tz)
                    
                    wait_time = (next_open - now_ny).total_seconds()
                    wait_hours = wait_time // 3600
                    wait_minutes = (wait_time % 3600) // 60
                    
                    logging.info(f"💤 Mercado cerrado. Próxima apertura: {next_open.strftime('%A %d/%m/%Y a las %H:%M ET')}")
                    logging.info(f"⏳ Esperando {int(wait_hours)}h {int(wait_minutes)}m...")
                    
                    # Enviar notificación de estado si es la primera vez
                    status_message = f"""
🌙 <b>Monitor RSI - Mercado Cerrado</b>

📅 <b>Próxima apertura:</b> {next_open.strftime('%A %d/%m/%Y')}
🕘 <b>Hora:</b> 9:30 AM ET
⏳ <b>Tiempo restante:</b> {int(wait_hours)}h {int(wait_minutes)}m

💤 El monitor se pausará hasta la apertura del mercado.
                    """.strip()
                    
                    self.send_telegram_message(status_message)
                    
                    # Esperar hasta la apertura (verificar cada hora por si acaso)
                    sleep_time = min(wait_time, 3600)  # Máximo 1 hora
                    time.sleep(int(sleep_time))
                    continue
                
                # El mercado está abierto, proceder con el monitoreo
                logging.info("📈 --- Iniciando ronda de chequeos ---")
                results = []
                
                for symbol in stock_list:
                    logging.info(f"🔍 Verificando {symbol}...")
                    result = self.check_rsi_alert(symbol, rsi_threshold)
                    results.append(result)
                    
                    # Pausa entre consultas para evitar rate limiting
                    time.sleep(3)
                
                # Resumen de la ronda
                successful = len([r for r in results if r['success']])
                alerts_sent = len([r for r in results if r.get('alert_sent', False)])
                
                logging.info(f"✅ Ronda completada: {successful}/{len(stock_list)} exitosos, {alerts_sent} alertas enviadas")
                
                # Verificar si el mercado sigue abierto antes de esperar
                if self.is_market_open():
                    logging.info(f"⏰ Esperando {check_interval//60} minutos hasta el próximo chequeo...")
                    time.sleep(check_interval)
                else:
                    logging.info("🔒 Mercado se cerró durante la ejecución")
                
            except KeyboardInterrupt:
                logging.info("❌ Monitoreo detenido por el usuario")
                break
            except Exception as e:
                logging.error(f"💥 Error en el monitoreo: {e}")
                time.sleep(300)  # Esperar 5 minutos antes de reintentar

def main():
    # Configuración
    BOT_TOKEN = "TU_BOT_TOKEN_AQUI"  # Reemplaza con tu token
    CHAT_ID = "TU_CHAT_ID_AQUI"      # Reemplaza con tu chat ID
    
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
        "INTC"    # Intel
    ]
    
    # Parámetros de monitoreo
    RSI_THRESHOLD = 30      # Umbral para alerta de sobreventa
    CHECK_INTERVAL = 1800   # Chequear cada 30 minutos (1800 segundos)
    
    # Crear instancia del monitor
    monitor = RSIMonitor(BOT_TOKEN, CHAT_ID)
    
    # Verificar configuración
    if not BOT_TOKEN or not CHAT_ID:
        logging.error("❌ Variables de entorno no configuradas:")
        logging.error("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son requeridas")
        return
    
    # Enviar mensaje de inicio
    start_message = f"""
🚀 <b>Monitor RSI Iniciado</b>

📋 <b>Acciones monitoreadas:</b> {len(STOCK_LIST)}
📊 <b>Umbral RSI:</b> {RSI_THRESHOLD}
⏱️ <b>Intervalo:</b> {CHECK_INTERVAL//60} minutos

Recibirás alertas cuando el RSI(14) esté por debajo de {RSI_THRESHOLD}.
    """.strip()
    
    monitor.send_telegram_message(start_message)
    
    # Iniciar monitoreo
    try:
        monitor.monitor_stocks(STOCK_LIST, RSI_THRESHOLD, CHECK_INTERVAL)
    except Exception as e:
        logging.error(f"Error fatal: {e}")

if __name__ == "__main__":
    main()