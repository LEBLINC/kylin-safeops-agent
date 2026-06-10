"""API 层：把 orchestrator 内核包装为 B/S 服务。

模块结构：
- app.py           : FastAPI 实例 + lifespan + fake 装配
- event_bus.py     : 按 trace_id 分发的内存事件总线 + SSEEventSink
- session_registry.py : Orchestrator 实例存活注册表
- deps.py          : 共享依赖（认证占位等）
"""
