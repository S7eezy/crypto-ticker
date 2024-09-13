import requests
import customtkinter as ctk
from PIL import Image
import logging
from ratelimit import limits, sleep_and_retry
import json
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CALLS = 1200
RATE_LIMIT = 60


class API:
    def __init__(self, name, base_url, price_endpoint, change_endpoint):
        self.name = name
        self.base_url = base_url
        self.price_endpoint = price_endpoint
        self.change_endpoint = change_endpoint

    def get_price_url(self, coin_id):
        return f"{self.base_url}{self.price_endpoint}?symbol={coin_id}"

    def get_change_url(self, coin_id):
        return f"{self.base_url}{self.change_endpoint}?symbol={coin_id}"


APIs = [
    API("Binance", "https://api.binance.com/api/v3/",
        "ticker/price", "ticker/24hr"),
]


class Ticker:
    def __init__(self, symbol, binance_symbol):
        self.symbol = symbol
        self.binance_symbol = binance_symbol
        self.price = 0
        self.change_24h = 0
        self.last_update = None
        self.logo_path = f"./assets/{symbol.lower()}.png"
        self.current_api = APIs[0]

    @sleep_and_retry
    @limits(calls=CALLS, period=RATE_LIMIT)
    def update(self):
        try:
            price_url = self.current_api.get_price_url(self.binance_symbol)
            price_response = requests.get(price_url, timeout=10)
            price_response.raise_for_status()
            price_data = price_response.json()
            self.price = float(price_data['price'])

            change_url = self.current_api.get_change_url(self.binance_symbol)
            change_response = requests.get(change_url, timeout=10)
            change_response.raise_for_status()
            change_data = change_response.json()
            self.change_24h = float(change_data['priceChangePercent'])

            self.last_update = datetime.now()
            self.save_to_cache()
        except requests.RequestException as e:
            logging.warning(f"Network error updating {self.symbol}: {e}")
            self.load_from_cache()
        except Exception as e:
            logging.error(f"Unexpected error updating {self.symbol}: {e}")
            self.load_from_cache()

    def save_to_cache(self):
        cache_data = {
            'price': self.price,
            'change_24h': self.change_24h,
            'last_update': self.last_update.isoformat(),
            'api': self.current_api.name
        }
        with open(f"{self.symbol}_cache.json", 'w') as f:
            json.dump(cache_data, f)

    def load_from_cache(self):
        try:
            with open(f"{self.symbol}_cache.json", 'r') as f:
                cache_data = json.load(f)
            self.price = cache_data['price']
            self.change_24h = cache_data['change_24h']
            self.last_update = datetime.fromisoformat(cache_data['last_update'])
            self.current_api = next(api for api in APIs if api.name == cache_data['api'])
            logging.info(f"Loaded cached data for {self.symbol}")
        except FileNotFoundError:
            logging.warning(f"No cache file found for {self.symbol}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding cache file for {self.symbol}")


class GUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Crypto Price Display")
        self.geometry("1920x1080")
        self.attributes('-fullscreen', True)

        self.grid_rowconfigure((0, 1), weight=1)
        self.grid_columnconfigure((0, 1), weight=1)

        self.tickers = [
            Ticker("BTC", "BTCUSDT"),
            Ticker("ETH", "ETHUSDT"),
            Ticker("SOL", "SOLUSDT"),
            Ticker("XRP", "XRPUSDT")
        ]

        self.frames = []
        for i, ticker in enumerate(self.tickers):
            frame = ctk.CTkFrame(self, corner_radius=10)
            frame.grid(row=i // 2, column=i % 2, padx=20, pady=20, sticky="nsew")
            frame.grid_rowconfigure((0, 1, 2, 3, 4), weight=1)
            frame.grid_columnconfigure(0, weight=1)

            logo_label = ctk.CTkLabel(frame, text="")
            logo_label.grid(row=0, column=0, pady=(20, 10))

            name_label = ctk.CTkLabel(frame, text=ticker.symbol,
                                      font=ctk.CTkFont(family="Arial Rounded MT Bold", size=48, weight="bold"))
            name_label.grid(row=1, column=0, pady=5)

            price_label = ctk.CTkLabel(frame, text="",
                                       font=ctk.CTkFont(family="Arial Rounded MT Bold", size=72))
            price_label.grid(row=2, column=0, pady=5)

            change_label = ctk.CTkLabel(frame, text="",
                                        font=ctk.CTkFont(family="Arial Rounded MT Bold", size=48))
            change_label.grid(row=3, column=0, pady=5)

            api_label = ctk.CTkLabel(frame, text="",
                                     font=ctk.CTkFont(family="Arial", size=18))
            api_label.grid(row=4, column=0, pady=5)

            self.frames.append((logo_label, name_label, price_label, change_label, api_label))

        self.update_prices()

    @sleep_and_retry
    @limits(calls=CALLS, period=RATE_LIMIT)
    def update_prices(self):
        for ticker, (logo_label, name_label, price_label, change_label, api_label) in zip(self.tickers, self.frames):
            ticker.update()

            try:
                if os.path.exists(ticker.logo_path):
                    logo_image = Image.open(ticker.logo_path)
                    logo_image = logo_image.resize((128, 128))
                    logo_photo = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(128, 128))
                    logo_label.configure(image=logo_photo)
                    logo_label.image = logo_photo

                precision = 7 - len(str(ticker.price).split('.')[0])
                price_label.configure(text=f"{ticker.price:.{precision}f}")

                arrow = "▲" if ticker.change_24h > 0 else "▼"
                color = "green" if ticker.change_24h > 0 else "red"
                change_label.configure(text=f"{arrow} {abs(ticker.change_24h):.2f}%", text_color=color)

                api_label.configure(
                    text=f"API: {ticker.current_api.name}\nLast update: {ticker.last_update.strftime('%H:%M:%S')}")
            except Exception as e:
                logging.error(f"Unexpected error updating display for {ticker.symbol}: {e}")

        self.after(10000, self.update_prices)


def run_gui():
    app = GUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
