from django.apps import AppConfig


class ExecutorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ops_platform.apps.executors"
    label = "executors"
    verbose_name = "执行器"

    def ready(self):
        # 注册内置执行器(本地进程 / Docker 隔离)
        from .registry import ExecutorRegistry  # noqa: F401
        from .local import LocalProcessExecutor  # noqa: F401
        from .docker import DockerExecutor  # noqa: F401

        ExecutorRegistry.register(LocalProcessExecutor())
        ExecutorRegistry.register(DockerExecutor())
