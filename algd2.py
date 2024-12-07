import datetime as dt
import time
import logging
from optibook.synchronous_client import Exchange

logging.getLogger('client').setLevel('ERROR')

STOCK_A_ID = 'PHILIPS_A'
STOCK_B_ID = 'PHILIPS_B'

POSITION_LIMIT = 200
HEDGE_LIMIT = 40
HEDGE_GRACE_PERIOD = 3.0
UPDATE_LIMIT_PER_SEC = 25

class CompetitiveTrader:
    def __init__(self, exchange):
        self.exchange = exchange
        self.last_update_timestamp = time.time()
        self.updates_in_last_second = 0
        self.hedge_violation_start = None

    def rate_limit_updates(self):
        """Ensure we do not exceed 25 updates/sec."""
        current_time = time.time()
        if current_time - self.last_update_timestamp >= 1:
            # Reset every second
            self.updates_in_last_second = 0
            self.last_update_timestamp = current_time

        if self.updates_in_last_second >= UPDATE_LIMIT_PER_SEC:
            # If at or beyond limit, wait until we can send more updates
            sleep_time = 1 - (current_time - self.last_update_timestamp)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self.updates_in_last_second = 0
            self.last_update_timestamp = time.time()

    def safe_insert_order(self, instrument_id, price, volume, side):
        """Insert an order while respecting update rate and position limits."""
        self.rate_limit_updates()
        if self.trade_would_breach_position_limit(instrument_id, volume, side):
            # In a competitive environment, skip this trade rather than waiting.
            return None

        self.updates_in_last_second += 1
        return self.exchange.insert_order(
            instrument_id=instrument_id,
            price=price,
            volume=volume,
            side=side,
            order_type='ioc'
        )

    def trade_would_breach_position_limit(self, instrument_id, volume, side):
        positions = self.exchange.get_positions()
        pos = positions.get(instrument_id, 0)
        if side == 'bid':  # buying
            return pos + volume > POSITION_LIMIT
        elif side == 'ask':  # selling
            return pos - volume < -POSITION_LIMIT
        else:
            raise ValueError("Invalid side")

    def get_best_prices(self, instrument_id):
        """Get best bid/ask if available."""
        book = self.exchange.get_last_price_book(instrument_id)
        if not (book and book.bids and book.asks):
            return None, None
        return book.bids[0].price, book.asks[0].price

    def print_positions_and_pnl(self):
        positions = self.exchange.get_positions()
        pnl = self.exchange.get_pnl()
        print('Positions:')
        for instrument_id, pos in positions.items():
            print(f'  {instrument_id:10s}: {pos:4d}')
        print(f'\nPnL: {pnl:.2f}')

    def check_hedge_compliance(self):
        """Check if current hedge position is within [-40,40]. If not, correct after 3s grace."""
        positions = self.exchange.get_positions()
        pos_a = positions.get(STOCK_A_ID, 0)
        pos_b = positions.get(STOCK_B_ID, 0)
        combined = pos_a + pos_b

        if -HEDGE_LIMIT <= combined <= HEDGE_LIMIT:
            self.hedge_violation_start = None
            return True
        else:
            if self.hedge_violation_start is None:
                self.hedge_violation_start = time.time()
            else:
                if (time.time() - self.hedge_violation_start) > HEDGE_GRACE_PERIOD:
                    print("Hedge limit violated for more than 3 seconds! Correcting now...")
                    self.correct_hedge_positions()
            # After attempting correction, re-check
            positions = self.exchange.get_positions()
            pos_a = positions.get(STOCK_A_ID, 0)
            pos_b = positions.get(STOCK_B_ID, 0)
            combined = pos_a + pos_b
            return -HEDGE_LIMIT <= combined <= HEDGE_LIMIT

    def correct_hedge_positions(self):
        """Try to quickly restore hedge compliance by flattening positions."""
        positions = self.exchange.get_positions()
        pos_a = positions.get(STOCK_A_ID, 0)
        pos_b = positions.get(STOCK_B_ID, 0)
        combined = pos_a + pos_b

        a_best_bid, a_best_ask = self.get_best_prices(STOCK_A_ID)
        b_best_bid, b_best_ask = self.get_best_prices(STOCK_B_ID)
        if None in (a_best_bid, a_best_ask, b_best_bid, b_best_ask):
            # Can't correct without full market data.
            return

        # Simple correction strategy: reduce the largest absolute position first
        while not (-HEDGE_LIMIT <= combined <= HEDGE_LIMIT):
            self.rate_limit_updates()
            if combined > HEDGE_LIMIT:
                # Too positive: need to sell something
                if pos_a > 0:
                    vol = min(pos_a, combined - HEDGE_LIMIT, 5)
                    self.safe_insert_order(STOCK_A_ID, a_best_bid, vol, 'ask')
                    pos_a -= vol
                elif pos_b > 0:
                    vol = min(pos_b, combined - HEDGE_LIMIT, 5)
                    self.safe_insert_order(STOCK_B_ID, b_best_bid, vol, 'ask')
                    pos_b -= vol
                else:
                    break
            else:
                # combined < -HEDGE_LIMIT
                # Too negative: need to buy something
                if pos_a < 0:
                    vol = min(-pos_a, HEDGE_LIMIT - combined, 5)
                    self.safe_insert_order(STOCK_A_ID, a_best_ask, vol, 'bid')
                    pos_a += vol
                elif pos_b < 0:
                    vol = min(-pos_b, HEDGE_LIMIT - combined, 5)
                    self.safe_insert_order(STOCK_B_ID, b_best_ask, vol, 'bid')
                    pos_b += vol
                else:
                    break
            combined = pos_a + pos_b

    def find_opportunities(self):
        """Check if there's a profitable arbitrage opportunity."""
        a_best_bid, a_best_ask = self.get_best_prices(STOCK_A_ID)
        b_best_bid, b_best_ask = self.get_best_prices(STOCK_B_ID)

        if None in (a_best_bid, a_best_ask, b_best_bid, b_best_ask):
            return None

        # Opportunity 1: Buy B at b_best_ask, Sell A at a_best_bid (profit_ba)
        profit_ba = a_best_bid - b_best_ask
        # Opportunity 2: Buy A at a_best_ask, Sell B at b_best_bid (profit_ab)
        profit_ab = b_best_bid - a_best_ask

        # Return the best profitable opportunity
        if profit_ba > 0 and profit_ba >= profit_ab:
            return ('BA', a_best_bid, b_best_ask)
        elif profit_ab > 0:
            return ('AB', b_best_bid, a_best_ask)
        else:
            return None

    def execute_hedged_trade(self, direction, price_sell, price_buy):
        """Execute the hedged trade (1 lot) immediately."""
        volume = 1
        positions = self.exchange.get_positions()
        pos_a = positions.get(STOCK_A_ID, 0)
        pos_b = positions.get(STOCK_B_ID, 0)

        if direction == 'BA':
            # Buy B at price_buy, Sell A at price_sell
            # Sell A first:
            self.safe_insert_order(STOCK_A_ID, price_sell, volume, 'ask')
            # Then buy B:
            self.safe_insert_order(STOCK_B_ID, price_buy, volume, 'bid')
        else:
            # direction == 'AB'
            # Buy A at price_buy, Sell B at price_sell
            # Sell B first:
            self.safe_insert_order(STOCK_B_ID, price_sell, volume, 'ask')
            # Then buy A:
            self.safe_insert_order(STOCK_A_ID, price_buy, volume, 'bid')

    def run(self):
        # In a competitive environment, we try to loop quickly:
        while True:
            start_time = time.time()

            print('-----------------------------------------------------------------')
            print(f'TRADE LOOP ITERATION ENTERED AT {str(dt.datetime.now()):18s} UTC')
            print('-----------------------------------------------------------------')
            self.print_positions_and_pnl()

            # Ensure hedge compliance before trading
            if not self.check_hedge_compliance():
                print("Out of hedge compliance, corrected. Re-checking next iteration.")
                # Quickly re-check conditions after correction
                time.sleep(0.1)
                continue

            opportunity = self.find_opportunities()
            if opportunity:
                direction, price_sell, price_buy = opportunity

                # Check hedge limit impact of this trade
                positions = self.exchange.get_positions()
                pos_a = positions.get(STOCK_A_ID, 0)
                pos_b = positions.get(STOCK_B_ID, 0)

                if direction == 'BA':
                    new_combined = (pos_a - 1) + (pos_b + 1)
                else:
                    new_combined = (pos_a + 1) + (pos_b - 1)

                if -HEDGE_LIMIT <= new_combined <= HEDGE_LIMIT:
                    print(f"Executing hedged trade: {direction}")
                    self.execute_hedged_trade(direction, price_sell, price_buy)
                else:
                    print("Potential hedge breach by this trade. Skipping.")
            else:
                print("No immediate arbitrage opportunity detected.")

            # Minimal sleep to avoid busy-waiting and to allow other participants to move the market.
            # Sleep less if we can. For high responsiveness, sleep a tiny amount, but ensure not to exceed 25 updates/sec.
            # Since we mostly placed few orders, a short sleep is enough.
            loop_duration = time.time() - start_time
            # If we performed multiple updates, we might need to wait to avoid going over update limit.
            # If not, just rest a tiny bit.
            time.sleep(max(0.05, 0.1 - loop_duration))


# Initialize and run:
exchange = Exchange()
exchange.connect()

trader = CompetitiveTrader(exchange)
trader.run()
