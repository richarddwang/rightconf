# Priority
SWEEP > Omegaconf CLI > YAML file later > YAML file earlier
疊加: 透過 --config 記述多個 YAML 檔案，其 configuration 將疊加。在碰到相同的 key 時，越後面的檔案優先度越高。

# Special Keywords
## `OBJECT`
應記述 class path。代表其所在的 group 中的 key 會對應至該 class 的 `__init__` 的參數。使用者應參考該 class 的 documentation 或其 parent class 的 documentation 對該 group 進行設置。
```
logger:
    OBJECT: rl_trading.experiment.callback.WandbLogger
    run_name: test_run
    freq: 2_000
    timeunit: timestep
```
例如上面的設置代表 `WandbLogger(run_name="test_run", freq=2000, timeunit="timestep")`。
## `SWEEP`
hyperparameter sweep。For 迴圈執行不同設置下的程序。
```
SWEEP:
    experiment.seed_base: [1,2,3]
    environment.window_length: [10, 20]
```
例如以上的設置會依序執行 `experiment.seed_base=1 environment.window_length=10`、`experiment.seed_base=1 environment.window_length=20`、`experiment.seed_base=2 environment.window_length=10`、`experiment.seed_base=2 environment.window_length=20` ...的設置。
## `GROUP`
可以指定某個 key 為某個 value 時，另個 key 為需為對應的 value。 
```
SWEEP:
    experiment.seed_base: [1,2,3]
    GROUP:
        logger.name: [large-lr, small-lr]
        agent.learning_rate: [0.01, 0.0001]
```
例如以上的設置會依序執行 
1. `experiment.seed_base=1 logger.name=large-lr agent.learning_rate=0.01`
2. `experiment.seed_base=1 logger.name=small-lr agent.learning_rate=0.0001`
3. `experiment.seed_base=2 logger.name=large-lr agent.learning_rate=0.01`
...的設置。

## `${}`
access 才會取用 類似 softlink 
使用方式可參考: Config node interpolation (https://omegaconf.readthedocs.io/en/2.3_branch/usage.html#variable-interpolation)
```
server:
  host: localhost
  port: 80

client:
  url: http://${server.host}:${server.port}/
  server_port: ${server.port}
  # relative interpolation
  description: Client of ${.url}
``` 
例如以上的設定，`client.url` 即為 http://localhost:80/。
若 `server.host` 後來改為 localhost1，則 `client.url` 自動變更為 http://localhost1:80/。

# Signature
所有的 kwargs expansion，包含自定義的參數與繼承 parent class 的參數。
``` 
# 定義 ParentClass
class ParentClass:
    def __init__(self, parent_param1: str, parent_param2: str ='DefaultValue', parent_param3: Optional[np.ndarray] = None):
        self.parent_param1 = parent_param1
        self.parent_param2 = parent_param2

# 定義繼承自 ParentClass 的 CustomizedClass
class CustomizedClass(ParentClass):
    def __init__(self, child_param1: str, child_param2: int, **kwargs): 
        super().__init__(parent_param1=child_param1, **kwargs)  
        self.child_param2 = child_param2
``` 
例如以上的設定，Signature 包含 parent_param2, parent_param3, child_param1, child_param2。

## 檢查
檢查使用者設定的參數有沒有都在 Signature 裡，如果是使用者設定的參數未在 Signature 裡，會出現以下錯誤。
```
KeyError: '"aaa" does not match any arguments for "<class 'trade.common.data.window.WindowData'>": ['data', 'features', 'window_length']'
```

## Automatical value insertion
預設值: 即使沒有記述，帶有 `OBJECT` 的 group 也會自動代入對應的 class 的 default 參數值。
```
policy:
    OBJECT: CustomizedClass
    child_param1: NonDefaultValue
    child_param2: ChildValue
```
上面的記述會等同於下面的記述。
```
policy:
    OBJECT: CustomizedClass
    parent_param2: DefaultValue
    child_param1: NonDefaultValue
    child_param2: ChildValue
```
- `parent_param2` 會自動被補上，因為 `ParentClass` 的 `parent_param2` 的參數預設是 "DefaultValue"。
- 但 `parent_param3` 不會自動被補上，因為參數 type 不支援。(其中支援的 type 只限 NoneType, bool, str, int, float, tuple, frozenset, list, dict, set, PathLike)