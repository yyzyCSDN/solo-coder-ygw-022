# GreenhouseClimate Python

这是一个可运行的温室环控与灌溉服务，当前提供以下能力：

- 领域资产：zone、crop_batch、probe、heater、dehumidifier、co2_unit、fan、irrigation_valve、pump、grow_light
- 测点历史：air_temperature、humidity、co2、soil_moisture、manifold_pressure、power_kw，包含质量、来源、校准版本和观测时间
- 可审计动作：heat、dehumidify、ventilate、inject_co2、open_valve、close_valve、manual_hold，相同幂等键不会重复登记
- 基础流程：climate_cycle、zone_irrigation、crop_stage_plan，支持请求去重和状态推进
- 版本配置：probe_calibration、climate_targets、irrigation_limits、power_budget，保留历史版本和当前激活标记

当前版本侧重设备台账、测点留存、动作审计和基础流程，高级协调与复杂故障恢复尚未覆盖。

```powershell
python -m greenhouse --demo
python -m unittest discover -s tests -v
```
