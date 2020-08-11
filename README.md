# TQ_trader: China's Futures Market Automatic Trader for Trend-following strategies

## Basic trading strategy

This trader trades a given set of futures contracts using the **Don-Chian** breakout strategy. It will open position if there is a breakout from either the upper or lower band, and it will forcely close this position when it reached the middle band (MA). 

## Advanced features

This trader is originated from the public TQSDK's demo trader script [(Link)](https://doc.shinnytech.com/tqsdk/latest/demo/strategy.html#id10), but it has been improved in various ways so it is better fit for production-level usage and/or future development.
Some of the implemented features are:

1. Automatic Chandelier Exit
2. Variable open hand: the more a contract diviate from MA, the less we will open it
3. Automatically close existing position when certain contract is no longer selected
4. Failsafe, automatically save critical trading parameter to json, can restore afterward if program hault during trading hour.
5. Logginng: implemented a custom logger to log all trade-relevent data to file, provide record for open/close action with theoretical and actual price comparison.

There are also some features that have not been implemented:

1. Using contract-level customized order mechanisim instead of the TargetPosTask, better monitor open cost and implement friction controls
2. Risk management system including position monitoring, abnormal order warnings and comfirmation.

## Usage and License

This is a customized use of TQSDK, please refer to their doc for detailed usage and account-related problem. [(link)](https://doc.shinnytech.com/tqsdk/latest/index.html). 

This code itself is free to use under the MIT license. please leave message if there are any questions.

### Disclaimer

Be advised that this script has been tested various times and runned successfully for over 10 days on simulation account, but there could be bugs and failures of logics that may cause **SERIOUS** problems and loss of money.

请注意，此代码虽然经过多次测试并在模拟盘中按预期运行了多日，这并不代表此代码无任何问题，严重的逻辑错误与代码bug可能导致实盘资金的大额损失，本人不对此负责。