#!/usr/bin/env python
import os
import sys
import logging

ROOT_PATH = os.path.abspath( os.path.join(os.path.dirname(__file__), "../../"))
sys.path.insert( 0, os.path.join(ROOT_PATH, 'libs'))

from bitex.client import BitExThreadedClient
import pusherclient
import json
from order_book_processor import OrderBookProcessor
from util import get_funded_entries

import datetime
import hmac
import hashlib

class BitstampArbitrator(object):
  def __init__(self, bitex_username, bitex_password,  bitex_ws_url='wss://api.blinktrade.com/trade/', bid_fee=0, ask_fee=0, api_key=None, api_secret=None):
    self.pusher = pusherclient.Pusher(key= 'de504dc5763aeef9ff52', log_level=logging.ERROR)
    self.order_book_bid_processor = OrderBookProcessor('1', 'BTCUSD')
    self.order_book_ask_processor = OrderBookProcessor('2', 'BTCUSD')
    self.bid_fee = bid_fee
    self.ask_fee = ask_fee
    self.api_key = api_key
    self.api_secret = api_secret

    self.ws = BitExThreadedClient( bitex_ws_url )
    self.bitex_username = bitex_username
    self.bitex_password = bitex_password

    self.order_book_bid_processor.send_new_order_signal.connect(self.on_send_buy_new_order)
    self.order_book_ask_processor.send_new_order_signal.connect(self.on_send_sell_new_order)
    self.order_book_bid_processor.cancel_order_signal.connect(self.on_send_cancel_order)
    self.order_book_ask_processor.cancel_order_signal.connect(self.on_send_cancel_order)

    self.usd_balance = 0
    self.btc_balance = 0
    self.bitex_broker = None
    self.bitex_profile = None

  def on_bitex_execution_report(self, sender, msg):
    if msg['ExecType'] == '0' or msg['ExecType'] == '4': # cancel
      return


    print datetime.datetime.now(), msg

    nonce = datetime.datetime.now().strftime('%s')
    message = str(nonce) + '.blinktrade.' + str(self.api_key)
    signature = hmac.new(self.api_secret, msg=message, digestmod=hashlib.sha256).hexdigest().upper()

    post_params = {
      'key': self.api_key,
      'signature': signature,
      'nonce': nonce,
      'amount': float(msg['LastShares']/1.e8),
      'price': float( msg['Price'] / 1.e8)
    }

    if msg['Side'] == '1':
      print datetime.datetime.now(), 'POST https://www.bitstamp.net/api/sell/', str(post_params)
    elif msg['Side'] == '2':
      print datetime.datetime.now(), 'POST https://www.bitstamp.net/api/buy/', str(post_params)

  def on_bitex_balance(self, sender, msg):
    if str(self.bitex_broker['BrokerID']) in msg:
      if 'USD' in msg[str(self.bitex_broker['BrokerID'])]:
        self.usd_balance = msg[str(self.bitex_broker['BrokerID'])]['USD']
      if 'BTC' in msg[str(self.bitex_broker['BrokerID'])]:
        self.btc_balance = msg[str(self.bitex_broker['BrokerID'])]['BTC']

  def on_bitex_connected(self, sender, msg):
    print 'connected to blinktrade'
    self.bitex_broker = msg['Broker']
    self.bitex_profile = msg['Profile']

    self.pusher.connection.bind('pusher:connection_established', self.on_bitstamp_connect_handler)
    self.pusher.connect()
    self.ws.send(json.dumps({ 'MsgType':'F'}))  # Cancel all open orders for this user
    self.ws.requestBalances()


  def on_send_buy_new_order(self,sender, msg):
    print datetime.datetime.now(), msg
    self.ws.sendMsg(msg)

  def on_send_sell_new_order(self,sender, msg):
    print datetime.datetime.now(), msg
    self.ws.sendMsg(msg)

  def on_send_cancel_order(self,sender, msg):
    print datetime.datetime.now(), msg
    self.ws.sendMsg(msg)

  def on_bitstamp_connect_handler(self, data):
    print 'connected to bitstamp'
    channel = self.pusher.subscribe('order_book')
    channel.bind('data', self.on_bitstamp_order_book_handler )

  def on_bitstamp_order_book_handler(self, data):
    data = json.loads(data)
    bid_list = [  [  int(float(usd)*1e8 * (1. - self.bid_fee) ), int(float(btc) * 1e8) ]  for usd,btc in data['bids'] ]
    ask_list = [  [  int(float(usd)*1e8 * (1. + self.ask_fee) ), int(float(btc) * 1e8) ]  for usd,btc in data['asks'] ]
    bid_list = get_funded_entries(bid_list, self.usd_balance, True)
    ask_list = get_funded_entries(ask_list, self.btc_balance, False)
    self.order_book_bid_processor.process_order_list(bid_list)
    self.order_book_ask_processor.process_order_list(ask_list)

  def run(self):
    self.ws.signal_logged.connect(self.on_bitex_connected)
    self.ws.signal_balance.connect(self.on_bitex_balance )
    self.ws.signal_execution_report.connect(self.on_bitex_execution_report)

    self.ws.connect()
    self.ws.login(self.bitex_username, self.bitex_password )


    try:
      self.ws.run_forever()
    except Exception, e:
      self.ws.send(json.dumps({'MsgType':'F'}))  # Cancel all open orders for this user
      self.ws.close()
      pass



def main():
  import getpass
  print "BlinkTrade <-> Bitstamp arbitrator"
  websocket_url = raw_input('BlinkTrade Websocket api server: ')
  username = raw_input('Username: ')
  password = getpass.getpass()

  buy_fee =  float(raw_input('buy fee [0 - 100]: ')) / 100
  sell_fee =  float(raw_input('sell fee [0 - 100]: ')) / 100


  arbitrator = BitstampArbitrator(username,
                                  password,
                                  websocket_url,
                                  buy_fee,
                                  sell_fee,
                                  'XXXX',
                                  'YYYY')
  arbitrator.run()

main()

