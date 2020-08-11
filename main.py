import json
import time
import datetime
from datetime import date
from tqsdk import TqApi, TargetPosTask, TqBacktest, TqKq, TqSim
from tqsdk.tafunc import ma
from tqsdk import api
import helper
import logging
import math

# logger system setup
custom_logger = logging.getLogger("custom_logger")
custom_handler = logging.FileHandler('trade-related.log', mode='w')
formater = logging.Formatter(fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
custom_handler.setFormatter(formater)
custom_logger.addHandler(custom_handler)

class DonMA(object):
    """
    A Real-market trading class mirroring the piecewise-cta strategy 
    """
    def __init__(self, symbols:list, account = None, window_ma = 22, window_hl = 17, market_cap = 1e6, cost_percentage = 0.06, backtest = True, debug = False, kq = None, tq_chan = None):
        self.debug = debug # debug开关
        self.account = account # 交易账号
        self.symbols = symbols # 今日活跃交易品种
        self.units = {} # 买卖单位dict
        self.states = {} # 记录每个品种持仓和最新价格，和吊灯参数，入场ma，持仓最高/最低
        self.t_0trades = {} # 当日只能对一个品种进行一个大操作
        self.curr_kline_updated = {} # 当日首次启动时只在收到bar update之后开始交易
        self.pendant_trades = {} # 当日只能吊灯出一次
        self.window_ma = window_ma # D-C参数
        self.window_hl = window_hl # D-C参数
        self.market_cap = market_cap # 单个品种最大市值
        self.cost_percentage = cost_percentage # 单个品种最大亏损

        self.channel_up = {} # 各个品种上轨
        self.channel_down = {} # 下轨
        self.ma = {} # 各个品种中轨

        # Initialze tqsdk API for various use
        if backtest:
            self.api =  TqApi(self.account, backtest=TqBacktest(start_dt=date(2020, 7, 28), end_dt=date(2020, 8, 3)), web_gui= True)
        elif kq != None:
            self.api = kq
        elif self.account!=None:
            self.api = TqApi(self.account, web_gui= True)
        else:
            self.api = TqApi(TqSim(),  web_gui= True)

        self.quote = {} # tick 收听频道dict
        self.kline = {} # 日线数据收听频道dict
        self.target_pos = {} # 目标仓位调整系统dict

        self.existing_positions = self.api.get_position() # 现有持仓（账户端获取，自动更新）
        self.trades = self.api.get_trade() # 今交易日交易，（账户获取，随时更新）
        self.symbols_old = []

        for i in self.existing_positions:
            # 获取所有之前有持仓但是现在不在选择池里的品种, 初始化
            if (not (i in self.symbols)) and self.existing_positions[i].pos != 0:
                self.symbols_old.append(i)
                self.quote[i] = self.api.get_quote(i)
                self.target_pos[i] = TargetPosTask(self.api,symbol=i, trade_chan=tq_chan)

        kline_length = max(self.window_hl + 1,self.window_ma + 1) # 设定k线周期

        for symbol in self.symbols:
            # 对各个活跃交易品种初始化，从账户中获取持仓和开仓价格（入场均线和极端值默认重制为入场价格）
            cloud_pos = 0
            cloud_last_pricce = 0
            if symbol in self.existing_positions:
                cloud_pos = self.existing_positions[symbol].pos
                if cloud_pos > 0 :
                    cloud_last_pricce = self.existing_positions[symbol].open_price_long
                elif cloud_pos < 0:
                    cloud_last_pricce = self.existing_positions[symbol].open_price_short     
            self.quote[symbol] = self.api.get_quote(symbol)
            self.units[symbol] = self.quote[symbol].volume_multiple
            self.kline[symbol] = self.api.get_kline_serial(symbol,24*60*60,kline_length) #日线
            self.target_pos[symbol] = TargetPosTask(self.api,symbol=symbol)
            self.t_0trades[symbol] = False
            self.pendant_trades[symbol] = False
            self.curr_kline_updated[symbol] = False
            self.states[symbol] = {'position' : cloud_pos, "last_price" : cloud_last_pricce, 'pendant_coef' : 1, 'extreme_since_entry' : cloud_last_pricce, 'open_ma' : cloud_last_pricce}

        self.account = self.api.get_account()

        custom_logger.warning("Initialization finished")

    def load_from_json(self,json_dict, interday_restore = False):
        """
        load local data from json to object dict

        Args:
            json_dict (dict): json read input
            interday_restore (bool, optional): whether load t0trade and pendant_trade from json, 
                should only be loaded when continuing from interday breakpoint. Defaults to False.
        """
        for i in json_dict:
            if i in self.states:
                self.states[i]['pendant_coef'] = json_dict[i]['pendant_coef']
                self.states[i]['extreme_since_entry'] = json_dict[i]['extreme_since_entry']
                self.states[i]['open_ma'] = json_dict[i]['open_ma']
                if interday_restore:
                    self.t_0trades[i] = json_dict[i]['t0_trade']
                    self.pendant_trades[i] = json_dict[i]['pendant_trade']
    
    def save_to_json(self):
        """
        Dump all settings to json file, use together with load_from_json
        """
        output_dict = {}
        for i in self.states:
            output_dict[i] = {'pendant_coef' : self.states[i]['pendant_coef'], 'extreme_since_entry' : self.states[i]['extreme_since_entry'], 'open_ma' : self.states[i]['open_ma']}
        for i in self.t_0trades:
            output_dict[i]['t0_trade'] = self.t_0trades[i]
            output_dict[i]['pendant_trade'] = self.pendant_trades[i]
        json.dump(output_dict, open("donma_state.json", "w"),sort_keys=True,indent=4)  # 保存数据

    def recalc_parameter(self,s:str):
        """
        recalculate ma, mh, ml for new daily kline

        Args:
            s (str): the contract name

        Returns:
            result (bool): indicating it is done
        """
        symbol = s
        self.channel_up[symbol] = max(self.kline[symbol].high[-self.window_hl - 1:-1])
        self.channel_down[symbol] = min(self.kline[symbol].low[-self.window_hl - 1:-1])
        self.ma[symbol] = ma(self.kline[symbol].close, self.window_ma).iloc[-2]
        custom_logger.warning("Don-chian {} upper middle low: {}, {}, {}".format( symbol, str(self.channel_up[symbol]), str(self.ma[symbol]) ,str(self.channel_down[symbol])))
        return True
    
    def set_position(self, symbol:str, pos:float, is_pendant = False):
        """
        update state dict & put in order for a given symbol toward a given pos

        Args:
            symbol (str): name of contract
            pos (float): targeting amount
            is_pendant (bool): whether this is a pendant exit, default is False
        """
        prev_pos = self.states[symbol]['position']
        self.states[symbol]['position'] = pos
        if prev_pos == 0 and pos!=0:
            self.states[symbol]['last_price'] = self.quote[symbol]['last_price']

        if is_pendant or (abs(prev_pos) > abs(pos) and abs(pos) != 0) :
            # 是减仓
            self.states[symbol]['pendant_coef'] += 1
        elif prev_pos != 0 and pos == 0:
            # 是完全平仓，reset
            self.states[symbol]['pendant_coef'] = 0
        elif prev_pos == 0 and pos != 0:
            # 新开仓，resets
            self.states[symbol]['pendant_coef'] = 1
            self.states[symbol]['open_ma'] = self.ma[symbol]
            self.states[symbol]['extreme_since_entry'] = self.quote[symbol]['last_price']

        self.target_pos[symbol].set_target_volume(pos)

    def update_holding_extremes(self, symbol : str, curr_price : float):
        """
        update extremes along the tick

        Args:
            symbol (str): name of contract
            curr_price (float): current "last price" from tick
        """
        pos = self.states[symbol]['position']
        if  pos > 0:
            # 更新最高收益
            self.states[symbol]['extreme_since_entry']  =  max([self.states[symbol]['extreme_since_entry'],curr_price])
        elif pos < 0:
            # 更新最高收益
            self.states[symbol]['extreme_since_entry']  =  min([self.states[symbol]['extreme_since_entry'], curr_price])
        else:
            #完全平仓，reset
            self.states[symbol]['extreme_since_entry'] = 0

    def check_open_close(self, interday_restore = False):
        """
        trading strategy
        """
        # initialize autosave reference time
        last_save_time = datetime.datetime.now()

        for old_s in self.symbols_old:
            # set target positions to zero for inactive contracts
            custom_logger.warning(old_s + " target to 0")
            self.target_pos[old_s].set_target_volume(0)
        
        for s in self.symbols:
            # Calculate initial daily K line
            self.recalc_parameter(s)
        
        while True:
            # Main loop, guarded by the wait_update function from api
            if not self.debug:
                curr_time = datetime.datetime.now()
                if curr_time.hour == 14 and curr_time.minute >= 59:
                    custom_logger.warning("Program exit")
                    # 临近收盘，今日推出
                    return
                if curr_time > last_save_time + datetime.timedelta(minutes=10):
                    last_save_time = curr_time
                    custom_logger.warning("save curr dict to json")
                    self.save_to_json()
            self.api.wait_update()
            for s in self.symbols:
                if self.api.is_changing(self.kline[s].iloc[-1], 'datetime') :
                    custom_logger.warning(s + " calculated")
                    self.t_0trades[s] = False
                    self.pendant_trades[s] = False
                    self.curr_kline_updated[s] = True
                    self.recalc_parameter(s)
                if self.api.is_changing(self.quote[s], 'last_price'):
                    if not interday_restore:
                        if self.curr_kline_updated[s] == False:
                            custom_logger.warning(s + 'skipped due to lack of updated kline')
                            # Skip tick without previou day's daily k-line
                            continue 
                    curr_price = self.quote[s].last_price
                    curr_time = self.quote[s].datetime
                    if math.isnan(curr_price):
                        continue
                    self.update_holding_extremes(s, curr_price)
                    if self.states[s]['position'] == 0 and not self.t_0trades[s]:
                        #当前无仓位，考虑是否开仓
                        if curr_price == self.ma[s]:
                            op_quantity = self.market_cap/(self.quote[s].last_price * self.units[s])
                        else:
                            op_quantity = min([(self.market_cap * self.cost_percentage)/(abs(curr_price - self.ma[s])* self.units[s]), self.market_cap/(self.quote[s].last_price * self.units[s])])
                        if math.isnan(op_quantity):
                            op_quantity = 0
                        op_quantity = int(op_quantity)
                        if  curr_price >= self.channel_up[s]:
                            # 达到开多仓条件
                            if op_quantity == 0:
                                op_quantity = 1
                            custom_logger.warning("@ "+curr_time)
                            custom_logger.warning("curr_price>upper_band (hold long): %d hand" % op_quantity)
                            custom_logger.warning(" %s curr price: %f" % (s, curr_price))
                            self.set_position(s,op_quantity)
                            self.t_0trades[s] = True
                        elif  curr_price <= self.channel_down[s]:
                            # 达到开空仓条件
                            op_quantity = op_quantity * -1
                            if op_quantity == 0:
                                op_quantity = -1
                            custom_logger.warning("@ "+curr_time)
                            custom_logger.warning("curr_price<upper_band(hold short): %d hand" % op_quantity)
                            custom_logger.warning(" %s curr price: %f" % (s, curr_price))
                            self.set_position(s,op_quantity)
                            self.t_0trades[s] = True
                    elif self.states[s]['position'] != 0:
                        # 考虑是否平仓
                        if self.states[s]['position'] > 0:
                            # 考虑多仓
                            open_cost = self.states[s]['last_price']
                            max_profit = self.states[s]['extreme_since_entry'] / open_cost - 1
                            
                            actual_ma = max([self.ma[s],self.states[s]['open_ma']])
                            if max_profit > 0 and not self.t_0trades[s]:
                                pendant_temp_coef = 1 - (self.states[s]['pendant_coef']*0.001/max_profit)
                                pendant_boundary = self.states[s]['extreme_since_entry'] * pendant_temp_coef
                                if curr_price <= pendant_boundary and not curr_price <= actual_ma:
                                    
                                    if pendant_boundary > actual_ma:
                                        if (self.states[s]['position'] >=3) and not self.pendant_trades[s]:
                                            custom_logger.warning("@ "+curr_time)
                                            custom_logger.warning(s + 'open cost(theory)' + str(open_cost))
                                            custom_logger.warning(s + 'max profit(theory)' + str(max_profit))
                                            custom_logger.warning(s + 'pendant line(theory)' + str(pendant_boundary))
                                            custom_logger.warning(" %s curr price: %f" % (s, curr_price))
                                            custom_logger.warning('pos change: {}, {}'.format(self.states[s]['position'], self.states[s]['position'] - (int(self.states[s]['position']/3))))
                                            self.set_position(s,self.states[s]['position'] - (int(self.states[s]['position']/3)),True)
                                            self.pendant_trades[s] = True
                                            
                            if curr_price <= actual_ma and not self.t_0trades[s]:
                                custom_logger.warning("@ "+curr_time)
                                custom_logger.warning(s + 'open cost:' + str(open_cost))
                                custom_logger.warning(s + 'actual ma: ' + str(actual_ma))
                                custom_logger.warning(s + 'curr price:' + str(curr_price))
                                self.set_position(s,0)
                                self.t_0trades[s] = True
                        else:
                            #考虑空仓
                            open_cost = self.states[s]['last_price']
                            max_profit = open_cost / self.states[s]['extreme_since_entry']  - 1
                            actual_ma = min([self.ma[s],self.states[s]['open_ma']])
                            if max_profit > 0 and not self.t_0trades[s]:
                                pendant_temp_coef = 1 + (self.states[s]['pendant_coef']*0.001/max_profit)
                                pendant_boundary = self.states[s]['extreme_since_entry'] * pendant_temp_coef
                                if curr_price >= pendant_boundary and not curr_price >= actual_ma:
                                    if pendant_boundary < actual_ma:
                                        if (abs(self.states[s]['position']) >=3) and not self.pendant_trades[s]:
                                            custom_logger.warning("@ "+curr_time)
                                            custom_logger.warning(s + 'open cost(theory)' + str(open_cost))
                                            custom_logger.warning(s + 'max profit(theory)' + str(max_profit))
                                            custom_logger.warning(s + 'pendant line(theory)' + str(pendant_boundary))
                                            custom_logger.warning('pos change: {}, {}'.format(self.states[s]['position'], self.states[s]['position'] - (int(self.states[s]['position']/3))))
                                            custom_logger.warning(" %s curr price: %f" % (s, curr_price))
                                            self.set_position(s,self.states[s]['position'] - (int(self.states[s]['position']/3)), True)
                                            self.pendant_trades[s] = True
                                            
                            if curr_price >= actual_ma and not self.t_0trades[s]:
                                custom_logger.warning("@ "+curr_time)
                                custom_logger.warning(s + 'open cost:' + str(open_cost))
                                custom_logger.warning(s + 'actual ma: ' + str(actual_ma))
                                custom_logger.warning(s + 'curr price:' + str(curr_price))
                                self.set_position(s,0)
                                self.t_0trades[s] = True
            if self.debug:
                # Exit all pos immediatly afterward in debug mode
                for s in self.symbols:
                    if self.existing_positions[s].pos != 0:
                        self.set_position(s,0)
                        while True:
                            self.api.wait_update()
                            if self.existing_positions[s].pos == 0:
                                return
    def run_strategy(self, interday_restore = False):
        """
        main function (trigger function)
        """
        custom_logger.warning("start monitoring ticks")
        self.check_open_close(interday_restore=interday_restore)

   
if __name__ == "__main__":
        
    # 手动写入今日活跃合约们 / 自动获取
    lst_of_contracts = helper.get_symbols()
    # lst_of_contracts = ['CZCE.AP010']
    donma = DonMA(lst_of_contracts, market_cap = 1e6 , backtest = False, debug=False, kq = None)
    
    try:
        custom_logger.warning('start loading json')
        donma.load_from_json(json.load(open('donma_state.json', 'r')), interday_restore = False)
    except FileNotFoundError:
        pass

    custom_logger.warning("strategy started")

    for i in donma.symbols:
        custom_logger.warning("curr active: %s pos: %d, open c: %f,  open ma: %f, pendant coef: %f, extreme since entry: %f" % (i, donma.states[i]['position'], donma.states[i]["last_price"], donma.states[i]['open_ma'],donma.states[i]['pendant_coef'],donma.states[i]['extreme_since_entry']))
    
    for i in donma.symbols_old:
        custom_logger.warning("curr inactive: %s " % (i))

    try:
        donma.run_strategy(interday_restore = False)
    finally:
        for i in donma.existing_positions:
            custom_logger.critical(helper.pprint_positions(donma.existing_positions[i]))
        custom_logger.warning('------------------------------')
        for i in donma.trades:
            custom_logger.critical(helper.pprint_trades(donma.trades[i]))
        donma.api.close()
        donma.save_to_json()
        