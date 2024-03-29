import alpaca_trade_api as tradeapi
import pandas as pd
import numpy as np
import statistics
import time
import config
import requests
from ta.trend import MACD
from datetime import datetime, timedelta
from pytz import timezone

api = tradeapi.REST(config.KEY_ID, config.SECRET_KEY, config.URL)

max_stock_price = 4.00
min_stock_price = 0
max_batch_size = 200
time_window = 30
# max_rating_fraction = 0.01


def get_all_ratings():
    print('Filtering assets and calculating ratings...')
    assets = api.list_assets()
    assets = [asset for asset in assets if asset.tradable]
    ratings = pd.DataFrame(columns=['symbol', 'rating', 'price'])
    index = 0
    while index < len(assets):
        symbol_batch = [
            asset.symbol for asset in assets[index:index+max_batch_size]
        ]
        bar_data = api.get_barset(
            symbols=symbol_batch,
            timeframe='day',
            limit=time_window
        )
        for symbol in symbol_batch:
            bars = bar_data[symbol]
            if len(bars) == time_window:
                latest_price = bars[-1].c
                day_prcnt_chng = bars[-1].c/bars[-2].c - 1
                if (
                    latest_price <= max_stock_price and
                    latest_price >= min_stock_price and
                    day_prcnt_chng <= -0.025
                ):
                    c_prices = np.array([bar.c for bar in bars])
                    c_prices_s = pd.Series(c_prices)
                    macd_obj = MACD(
                        close=c_prices_s,
                        window_fast=12,
                        window_slow=26,
                        window_sign=9
                    )
                    macd_vals = macd_obj.macd().values[25:]
                    trend_up = macd_vals[-1] >= macd_vals[-2] >= macd_vals[-3] >= macd_vals[-4] >= macd_vals[-5] > 0
                    macd_chng = macd_vals[-1] - macd_vals[-2]
                    rating = -1
                    if trend_up:
                        macd_stdev = statistics.stdev(macd_vals)
                        rating = (macd_chng / macd_stdev) * \
                            ((-1*day_prcnt_chng)+1)
                    if rating > 0:
                        ratings = ratings.append({
                            'symbol': symbol,
                            'rating': rating,
                            'price': latest_price
                        }, ignore_index=True)
        index += max_batch_size
    ratings = ratings.sort_values('rating', ascending=False)
    ratings = ratings.reset_index(drop=True)
    ratings = ratings[:5]
    print('Found {} stocks, with total rating: {}'.format(
        ratings.shape[0], ratings['rating'].sum()))
    return ratings


def get_shares_to_buy(ratings_df, portfolio):
    print('Calculating shares to buy...')
    total_rating = ratings_df['rating'].sum()
    shares = {}
    for _, row in ratings_df.iterrows():
        num_shares = int(row['rating'] / total_rating *
                         portfolio / row['price'])
        if num_shares == 0:
            continue
        shares[row['symbol']] = num_shares
    return shares


def run():
    tick_count = 0
    while True:
        try:
            clock = api.get_clock()
        except:
            print('rate limit hit! sleeping for 30 seconds ...')
            time.sleep(30)
            continue
        positions = api.list_positions()
        if clock.is_open:
            time_until_close = clock.next_close - clock.timestamp
            if time_until_close.seconds <= 120 and len(positions) == 0:
                print('Buying positions ...')
                portfolio_cash = float(api.get_account().cash)
                stock_ratings = get_all_ratings()
                shares_to_buy = get_shares_to_buy(
                    stock_ratings, portfolio_cash)
                for symbol in shares_to_buy:
                    api.submit_order(
                        symbol=symbol,
                        qty=shares_to_buy[symbol],
                        side='buy',
                        type='market',
                        time_in_force='day'
                    )
                print('Positions bought.')
                while clock.is_open == True:
                    clock = api.get_clock()
                    time.sleep(5)
                    print('Waiting for market to close ...')
            elif tick_count % 400 == 0:
                print('Waiting to buy...')
        else:
            if tick_count % 1200 == 0:
                print("Waiting for market open ...\n(now: {}, next open: {})".format(
                    clock.timestamp.round('1s'), clock.next_open))
        time.sleep(5)
        tick_count += 1


def log_shares(shares, ratings):
    total_price = 0
    for share in shares:
        price = ratings.loc[ratings['symbol'] == share, 'price'].values[0]
        print('{} stocks of {} posed to be bought at ${} for ${}'.format(
            shares[share],
            share,
            round(price, 2),
            round(price*shares[share], 2)
        ))
        total_price += price*shares[share]
    print('${} to be spent from ${}'.format(
        round(total_price, 2), float(api.get_account().cash)))


if __name__ == '__main__':
    run()
