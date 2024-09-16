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

os.chdir(os.path.dirname(os.path.abspath(__file__)))
os.environ['DISPLAY'] = ':0'

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
        self.font_scale = 1.0

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
            fig_width = 7
            fig_height = 3.5

            if self.appearance_mode == 'Dark':
                text_color = 'white'
            else:
                text_color = 'black'

            fig_height *= 1.2

            fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=100)
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

            fontsize = int(12 * self.font_scale)

            ax.text(idx_highest, highest_high, f'{highest_high:.2f}', color=text_color, fontsize=fontsize,
                    verticalalignment='bottom', horizontalalignment='center')

            ax.text(idx_lowest, lowest_low, f'{lowest_low:.2f}', color=text_color, fontsize=fontsize,
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

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}")
        self.attributes('-fullscreen', True)

        self.screen_size = (screen_width, screen_height)
        width_scale = screen_width / 1920
        height_scale = screen_height / 1080
        font_scale = min(width_scale, height_scale)
        if screen_height <= 600:
            font_scale *= 0.8

        self.appearance_mode = "Dark"
        ctk.set_appearance_mode(self.appearance_mode.lower())
        ctk.set_default_color_theme("blue")

        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.pack(fill="both", expand=True)

        self.sun_icon = ctk.CTkImage(Image.open('./assets/sun.png'), size=(int(24 * font_scale), int(24 * font_scale)))
        self.moon_icon = ctk.CTkImage(Image.open('./assets/moon.png'), size=(int(24 * font_scale), int(24 * font_scale)))

        if self.appearance_mode == "Dark":
            initial_icon = self.sun_icon
            fg_color = "#2B2B2B"
            hover_color = "#3A3A3A"
        else:
            initial_icon = self.moon_icon
            fg_color = "#E0E0E0"
            hover_color = "#D0D0D0"

        self.mode_button = ctk.CTkButton(self.main_frame, text="", width=int(40 * font_scale), height=int(40 * font_scale), corner_radius=20,
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

        if screen_width >= 1920 and screen_height >= 1080:
            for i, ticker in enumerate(self.tickers):
                frame = ctk.CTkFrame(self.main_frame, corner_radius=20)
                frame.grid(row=i // 2, column=i % 2, padx=int(15 * width_scale), pady=int(15 * height_scale), sticky="nsew")
                frame.grid_rowconfigure((0, 1, 2, 3, 4, 5), weight=1)
                frame.grid_columnconfigure(0, weight=1)

                name_font = ctk.CTkFont(family="Helvetica", size=int(24 * font_scale), weight="bold")
                price_font = ctk.CTkFont(family="Helvetica", size=int(36 * font_scale), weight="bold")
                change_font = ctk.CTkFont(family="Helvetica", size=int(24 * font_scale))
                updated_font = ctk.CTkFont(family="Helvetica", size=int(12 * font_scale))

                logo_label = ctk.CTkLabel(frame, text="")
                logo_label.grid(row=0, column=0, pady=(int(5 * height_scale), int(2 * height_scale)))

                name_label = ctk.CTkLabel(frame, text=ticker.symbol,
                                          font=name_font,
                                          anchor='center')
                name_label.grid(row=1, column=0, pady=int(2 * height_scale))

                price_label = ctk.CTkLabel(frame, text="",
                                           font=price_font,
                                           anchor='center')
                price_label.grid(row=2, column=0, pady=int(2 * height_scale))

                change_label = ctk.CTkLabel(frame, text="",
                                            font=change_font,
                                            anchor='center')
                change_label.grid(row=3, column=0, pady=int(2 * height_scale))

                chart_label = ctk.CTkLabel(frame, text="")
                chart_label.grid(row=4, column=0, pady=(int(2 * height_scale), int(5 * height_scale)))

                updated_label = ctk.CTkLabel(frame, text="",
                                             font=updated_font,
                                             anchor='center')
                updated_label.grid(row=5, column=0, pady=(0, int(5 * height_scale)))

                self.frames.append((logo_label, name_label, price_label, change_label, chart_label, updated_label))
        else:
            for i, ticker in enumerate(self.tickers):
                frame = ctk.CTkFrame(self.main_frame, corner_radius=20)
                frame.grid(row=i // 2, column=i % 2, padx=int(15 * width_scale), pady=int(15 * height_scale), sticky="nsew")
                frame.grid_rowconfigure((0, 1, 2), weight=1)
                frame.grid_columnconfigure(0, weight=1)

                name_font = ctk.CTkFont(family="Helvetica", size=int(40 * font_scale), weight="bold")
                price_font = ctk.CTkFont(family="Helvetica", size=int(40 * font_scale), weight="bold")
                change_font = ctk.CTkFont(family="Helvetica", size=int(44 * font_scale))

                header_frame = ctk.CTkFrame(frame, fg_color="transparent")
                header_frame.grid(row=0, column=0, pady=(int(2 * height_scale), int(0 * height_scale)))

                logo_label = ctk.CTkLabel(header_frame, text="")
                logo_label.pack(side="left", padx=int(30 * width_scale))

                name_label = ctk.CTkLabel(header_frame, text=ticker.symbol,
                                          font=name_font,
                                          anchor='center')
                name_label.pack(side="left", padx=int(20 * width_scale), pady=(int(15 * width_scale), 0))

                price_label = ctk.CTkLabel(header_frame, text="",
                                           font=price_font,
                                           anchor='center')
                price_label.pack(side="left", padx=int(20 * width_scale), pady=(int(15 * width_scale), 0))

                change_label = ctk.CTkLabel(frame, text="",
                                            font=change_font,
                                            anchor='center')
                change_label.grid(row=1, column=0, pady=(0, int(1 * height_scale)))

                chart_label = ctk.CTkLabel(frame, text="")
                chart_label.grid(row=2, column=0, pady=(int(1 * height_scale), int(5 * height_scale)))

                self.frames.append((logo_label, name_label, price_label, change_label, chart_label))

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

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width_scale = screen_width / 1920
        height_scale = screen_height / 1080
        font_scale = min(width_scale, height_scale)
        if screen_height <= 600:
            font_scale *= 0.8

        ticker.font_scale = font_scale

        if os.path.exists(ticker.logo_path):
            logo_image = Image.open(ticker.logo_path)
            if screen_width >= 1920 and screen_height >= 1080:
                logo_size = int(64 * font_scale)
            else:
                logo_size = int(80 * font_scale)
            logo_image = logo_image.resize((logo_size, logo_size), Image.Resampling.LANCZOS)
            logo_photo = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(logo_size, logo_size))
            logo_label = frame_elements[0]
            logo_label.configure(image=logo_photo)
            logo_label.image = logo_photo

        if screen_width >= 1920 and screen_height >= 1080:
            logo_label, name_label, price_label, change_label, chart_label, updated_label = frame_elements

            name_font = ctk.CTkFont(family="Helvetica", size=int(24 * font_scale), weight="bold")
            price_font = ctk.CTkFont(family="Helvetica", size=int(36 * font_scale), weight="bold")
            change_font = ctk.CTkFont(family="Helvetica", size=int(24 * font_scale))
            updated_font = ctk.CTkFont(family="Helvetica", size=int(12 * font_scale))

            name_label.configure(font=name_font)
            price_label.configure(font=price_font)
            change_label.configure(font=change_font)
            updated_label.configure(font=updated_font)
        else:
            logo_label, name_label, price_label, change_label, chart_label = frame_elements

            name_font = ctk.CTkFont(family="Helvetica", size=int(90 * font_scale), weight="bold")
            price_font = ctk.CTkFont(family="Helvetica", size=int(90 * font_scale), weight="bold")
            change_font = ctk.CTkFont(family="Helvetica", size=int(56 * font_scale))

            name_label.configure(font=name_font)
            price_label.configure(font=price_font)
            change_label.configure(font=change_font)

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
            if screen_width >= 1920 and screen_height >= 1080:
                chart_width = int(550 * width_scale)
                chart_height = int(275 * height_scale)
            else:
                chart_width = int(600 * width_scale)
                chart_height = int(275 * height_scale)
            chart_image = ticker.candlestick_image.resize((chart_width, chart_height), Image.Resampling.LANCZOS)
            chart_photo = ctk.CTkImage(light_image=chart_image, dark_image=chart_image, size=(chart_width, chart_height))
            chart_label.configure(image=chart_photo)
            chart_label.image = chart_photo

        if screen_width >= 1920 and screen_height >= 1080:
            updated_label.configure(text=f"Last updated: {ticker.last_update.strftime('%H:%M:%S')}",
                                    text_color="gray")


def run_gui():
    app = GUI()
    app.mainloop()


if __name__ == "__main__":
    run_gui()
