import requests
import customtkinter as ctk
from PIL import Image
import logging
from ratelimit import limits, sleep_and_retry
from datetime import datetime
import os
import io
import matplotlib
import matplotlib.pyplot as plt
import json

matplotlib.use('Agg')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CALLS = 1200
RATE_LIMIT = 60


class API:
    def __init__(self, name, base_url, price_endpoint, change_endpoint, kline_endpoint):
        self.name = name
        self.base_url = base_url
        self.price_endpoint = price_endpoint
        self.change_endpoint = change_endpoint
        self.kline_endpoint = kline_endpoint

    def get_price_url(self, coin_id):
        return f"{self.base_url}{self.price_endpoint}?symbol={coin_id}"

    def get_change_url(self, coin_id):
        return f"{self.base_url}{self.change_endpoint}?symbol={coin_id}"

    def get_kline_url(self, coin_id, interval, limit):
        return f"{self.base_url}{self.kline_endpoint}?symbol={coin_id}&interval={interval}&limit={limit}"


APIs = [
    API("Binance", "https://api.binance.com/api/v3/",
        "ticker/price", "ticker/24hr", "klines"),
]


class Ticker:
    def __init__(self, symbol, binance_symbol):
        self.symbol = symbol
        self.binance_symbol = binance_symbol
        self.price = 0
        self.price_change = 0
        self.change_24h = 0
        self.last_update = None
        self.logo_path = f"./assets/{symbol.lower()}.png"
        self.current_api = APIs[0]
        self.candlestick_image = None
        self.appearance_mode = 'Dark'

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
            self.price_change = float(change_data['priceChange'])

            self.last_update = datetime.now()
            self.save_to_cache()

            self.fetch_candlestick_data()
        except requests.RequestException as e:
            logging.warning(f"Network error updating {self.symbol}: {e}")
            self.load_from_cache()
        except Exception as e:
            logging.error(f"Unexpected error updating {self.symbol}: {e}")
            self.load_from_cache()

    def fetch_candlestick_data(self):
        try:
            kline_url = self.current_api.get_kline_url(self.binance_symbol, '1m', 20)
            kline_response = requests.get(kline_url, timeout=10)
            kline_response.raise_for_status()
            kline_data = kline_response.json()

            data = []
            for k in kline_data:
                timestamp = datetime.fromtimestamp(k[0]/1000)
                open_price = float(k[1])
                high_price = float(k[2])
                low_price = float(k[3])
                close_price = float(k[4])
                data.append([timestamp, open_price, high_price, low_price, close_price])

            self.plot_candlestick_chart(data)
        except Exception as e:
            logging.error(f"Error fetching candlestick data for {self.symbol}: {e}")

    def plot_candlestick_chart(self, data):
        try:
            fig, ax = plt.subplots(figsize=(7, 3.5), dpi=100)
            fig.patch.set_alpha(0.0)
            ax.set_facecolor('none')

            red_color = '#b22222'
            green_color = '#008000'

            high_values = [val[2] for val in data]
            low_values = [val[3] for val in data]
            highest_high = max(high_values)
            lowest_low = min(low_values)
            idx_highest = high_values.index(highest_high)
            idx_lowest = low_values.index(lowest_low)

            for idx, val in enumerate(data):
                color = green_color if val[4] >= val[1] else red_color
                ax.plot([idx, idx], [val[2], val[3]], color=color, linewidth=1)
                rect = plt.Rectangle((idx - 0.4, min(val[1], val[4])),
                                     0.8, abs(val[4] - val[1]),
                                     color=color)
                ax.add_patch(rect)

            text_color = 'white' if self.appearance_mode == 'Dark' else 'black'

            ax.text(idx_highest, highest_high, f'{highest_high:.2f}', color=text_color, fontsize=8,
                    verticalalignment='bottom', horizontalalignment='center')

            ax.text(idx_lowest, lowest_low, f'{lowest_low:.2f}', color=text_color, fontsize=8,
                    verticalalignment='top', horizontalalignment='center')

            ax.axis('off')
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0, transparent=True)
            buf.seek(0)
            self.candlestick_image = Image.open(buf)
            plt.close(fig)
        except Exception as e:
            logging.error(f"Error plotting candlestick chart for {self.symbol}: {e}")

    def save_to_cache(self):
        cache_data = {
            'price': self.price,
            'price_change': self.price_change,
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
            self.price_change = cache_data.get('price_change', 0)
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

        self.appearance_mode = "Dark"
        ctk.set_appearance_mode(self.appearance_mode.lower())
        ctk.set_default_color_theme("blue")

        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True)

        self.sun_icon = ctk.CTkImage(Image.open('./assets/sun.png'), size=(24, 24))
        self.moon_icon = ctk.CTkImage(Image.open('./assets/moon.png'), size=(24, 24))

        if self.appearance_mode == "Dark":
            initial_icon = self.sun_icon
            fg_color = "#2B2B2B"
            hover_color = "#3A3A3A"
        else:
            initial_icon = self.moon_icon
            fg_color = "#E0E0E0"
            hover_color = "#D0D0D0"

        self.mode_button = ctk.CTkButton(self.main_frame, text="", width=40, height=40, corner_radius=20,
                                         command=self.toggle_mode, image=initial_icon,
                                         fg_color=fg_color, hover_color=hover_color)
        self.mode_button.place(relx=0.5, rely=0.5, anchor="center")

        self.main_frame.grid_rowconfigure((0, 1), weight=1)
        self.main_frame.grid_columnconfigure((0, 1), weight=1)

        self.tickers = [
            Ticker("BTC", "BTCUSDT"),
            Ticker("ETH", "ETHUSDT"),
            Ticker("SOL", "SOLUSDT"),
            Ticker("XRP", "XRPUSDT")
        ]

        self.frames = []
        for i, ticker in enumerate(self.tickers):
            frame = ctk.CTkFrame(self.main_frame, corner_radius=20)
            frame.grid(row=i // 2, column=i % 2, padx=30, pady=30, sticky="nsew")
            frame.grid_rowconfigure((0, 1, 2, 3, 4, 5), weight=1)
            frame.grid_columnconfigure(0, weight=1)

            logo_label = ctk.CTkLabel(frame, text="")
            logo_label.grid(row=0, column=0, pady=(10, 5))

            name_label = ctk.CTkLabel(frame, text=ticker.symbol,
                                      font=ctk.CTkFont(family="Helvetica", size=32, weight="bold"),
                                      anchor='center')
            name_label.grid(row=1, column=0, pady=5)

            price_label = ctk.CTkLabel(frame, text="",
                                       font=ctk.CTkFont(family="Helvetica", size=48, weight="bold"),
                                       anchor='center')
            price_label.grid(row=2, column=0, pady=5)

            change_label = ctk.CTkLabel(frame, text="",
                                        font=ctk.CTkFont(family="Helvetica", size=32),
                                        anchor='center')
            change_label.grid(row=3, column=0, pady=5)

            chart_label = ctk.CTkLabel(frame, text="")
            chart_label.grid(row=4, column=0, pady=(5, 10))

            updated_label = ctk.CTkLabel(frame, text="",
                                         font=ctk.CTkFont(family="Helvetica", size=14),
                                         anchor='center')
            updated_label.grid(row=5, column=0, pady=(0, 10))

            self.frames.append((logo_label, name_label, price_label, change_label, chart_label, updated_label))

        self.update_prices()

    def toggle_mode(self):
        self.appearance_mode = "Light" if self.appearance_mode == "Dark" else "Dark"
        ctk.set_appearance_mode(self.appearance_mode.lower())
        self.update_mode_button_icon()

    def update_mode_button_icon(self):
        if self.appearance_mode == "Dark":
            self.mode_button.configure(image=self.sun_icon)
            self.mode_button.configure(fg_color="#2B2B2B", hover_color="#3A3A3A")
        else:
            self.mode_button.configure(image=self.moon_icon)
            self.mode_button.configure(fg_color="#E0E0E0", hover_color="#D0D0D0")

    @sleep_and_retry
    @limits(calls=CALLS, period=RATE_LIMIT)
    def update_prices(self):
        for ticker, frame_elements in zip(self.tickers, self.frames):
            ticker.appearance_mode = self.appearance_mode
            ticker.update()
            self.update_ticker_display(ticker, frame_elements)

        self.after(10000, self.update_prices)

    def update_ticker_display(self, ticker, frame_elements):
        logo_label, name_label, price_label, change_label, chart_label, updated_label = frame_elements

        try:
            if os.path.exists(ticker.logo_path):
                logo_image = Image.open(ticker.logo_path)
                logo_image = logo_image.resize((64, 64), Image.LANCZOS)
                logo_photo = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(64, 64))
                logo_label.configure(image=logo_photo)
                logo_label.image = logo_photo

            precision = 7 - len(str(int(ticker.price)))
            precision = max(2, precision)
            formatted_price = f"${ticker.price:,.{precision}f}"
            price_label.configure(text=formatted_price)

            arrow = "▲" if ticker.change_24h > 0 else "▼"
            color = "#41D128" if ticker.change_24h > 0 else "#EB4034"
            sign = "+" if ticker.price_change > 0 else "-"
            dollar_change = abs(ticker.price_change)
            change_label.configure(
                text=f"{arrow} {abs(ticker.change_24h):.2f}% ({sign}${dollar_change:.2f})",
                text_color=color
            )

            if ticker.candlestick_image:
                chart_image = ticker.candlestick_image.resize((550, 275), Image.LANCZOS)  # Increased size
                chart_photo = ctk.CTkImage(light_image=chart_image, dark_image=chart_image, size=(550, 275))
                chart_label.configure(image=chart_photo)
                chart_label.image = chart_photo

            updated_label.configure(text=f"Last updated: {ticker.last_update.strftime('%H:%M:%S')}",
                                    text_color="gray")
        except Exception as e:
            logging.error(f"Unexpected error updating display for {ticker.symbol}: {e}")


def run_gui():
    app = GUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
