import mysql.connector as sqlconnector
# import pwds
from datetime import date
import datetime
from tqsdk import TqApi, TargetPosTask, TqBacktest, TqSim

# mydb = sqlconnector.connect(
#     host = pwds.host,
#     user = pwds.user,
#     password=pwds.password,
#     db=pwds.default_db,
#     port=pwds.port,
#     auth_plugin = 'mysql_native_password'
# )
# mycursor = mydb.cursor()

def get_symbols():
    """
    Get trading symbols from a remote server (detailed server obfuscated)

    Returns:
        contract_names (list): a list of traded contract, in TQSDK's standard naming format
    """
    contract_names = []
    sql = 'SELECT exchange,instrument_id FROM speedtrade.selected'
    mycursor.execute(sql)
    result = mycursor.fetchall()
    for i in result:
        exchange = i[0].decode()
        inst_id = i[1].decode()
        actual_name = str(exchange) + '.' + str(inst_id)
        contract_names.append(actual_name)
    return contract_names

def pprint_positions(position):
    """
    custom print for TQSDK positions 

    Args:
        position (tqsdk's position object)

    Returns:
        str: the formated string
    """
    open_cost = 0
    if position.pos > 0:
        open_cost = position.open_price_long
    elif position.pos < 0 :
        open_cost = position.open_price_short
    s = "Contract: {}, Net Holding: {}, pos long : {}, pos short: {}, open cost (avg): {}".format(position.instrument_id, position.pos, position.pos_long, position.pos_short, open_cost)
    return s

def pprint_trades(trade):
    """
    custom print for TQSDK trade log 

    Args:
        trade (tqsdk's trade object)

    Returns:
        str: the formated string
    """
    s = 'Contract: {}, direction: {}, offset: {}, price: {}, volume: {}, time: {}'.format(trade.instrument_id, trade.direction, trade.offset, str(trade.price), str(trade.volume), datetime.datetime.fromtimestamp(trade.trade_date_time // 1000000000).strftime('%Y-%m-%d %H:%M:%S.%f'))
    return s

if __name__ == '__main__':
    # Testing code
    api = TqApi()
    pos = api.get_position()
    order = api.insert_order(symbol = "CZCE.AP010", direction='BUY', offset='OPEN', volume=3)
    trades = api.get_trade()
    while True:
        api.wait_update()
        for i in pos:
           print(pprint_positions(pos[i])) 
        for i in trades:
            print(pprint_trades(trades[i]))